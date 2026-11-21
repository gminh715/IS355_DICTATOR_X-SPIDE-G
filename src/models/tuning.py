"""Leakage-free nested CV, Optuna tuning parity, and in-fold RFE pipeline."""

from __future__ import annotations

import hashlib
import json
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

import lightgbm as lgb
import numpy as np
import optuna
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin, clone
from sklearn.feature_selection import RFE
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold
from sklearn.pipeline import Pipeline

from src.models.data_prep import load_split_indices
from src.models.metrics import evaluate_predictions, find_best_f1_threshold

optuna.logging.set_verbosity(optuna.logging.WARNING)

RFE_FEATURE_COUNTS: tuple[int, ...] = (24, 29, 34, 39, 44, 49, 54, 59, 64, 69, 74, 79, 84, 89, 94, 99)


def _array_signature(X: np.ndarray, y: np.ndarray) -> str:
    h = hashlib.blake2b(digest_size=16)
    h.update(str(X.shape).encode("ascii"))
    h.update(np.ascontiguousarray(X).view(np.uint8)[: min(X.nbytes, 65536)])
    h.update(np.ascontiguousarray(y).view(np.uint8))
    return h.hexdigest()


class CachedRFESelector(BaseEstimator, TransformerMixin):
    """sklearn-compatible RFE transformer fit strictly on the training slice.

    Because sklearn's deterministic RFE with step=5 eliminates features in an identical
    prefix sequence from 99 down to `min_features`, caching the fitted `ranking_` per
    exact `(X_train_slice, y_train_slice)` guarantees zero leakage across folds while
    avoiding 30x redundant RFE recomputation inside Optuna trials.
    """

    def __init__(
        self,
        n_features_to_select: int = 44,
        step: int = 5,
        min_features: int = 19,
        random_state: int = 42,
        n_jobs: int = 2,
        ranking_cache: dict[str, np.ndarray] | None = None,
    ) -> None:
        self.n_features_to_select = n_features_to_select
        self.step = step
        self.min_features = min_features
        self.random_state = random_state
        self.n_jobs = n_jobs
        self.ranking_cache = ranking_cache

    def fit(self, X: Any, y: Any) -> "CachedRFESelector":
        X_arr = np.asarray(X, dtype=np.float64)
        y_arr = np.asarray(y, dtype=int).ravel()
        n_total = X_arr.shape[1]
        target_k = max(1, min(int(self.n_features_to_select), n_total))

        if target_k == n_total:
            self.ranking_ = np.ones(n_total, dtype=int)
            self.support_ = np.ones(n_total, dtype=bool)
            return self

        sig = _array_signature(X_arr, y_arr)
        ranking: np.ndarray | None = None
        if self.ranking_cache is not None and sig in self.ranking_cache:
            ranking = self.ranking_cache[sig]

        if ranking is None:
            min_k = min(int(self.min_features), target_k)
            base_est = lgb.LGBMClassifier(
                boosting_type="gbdt",
                objective="binary",
                n_estimators=60,
                num_leaves=31,
                max_depth=10,
                learning_rate=0.1,
                random_state=self.random_state,
                n_jobs=self.n_jobs,
                verbose=-1,
            )
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                rfe = RFE(estimator=base_est, n_features_to_select=min_k, step=self.step)
                rfe.fit(X_arr, y_arr)
            ranking = rfe.ranking_.astype(int)
            if self.ranking_cache is not None:
                self.ranking_cache[sig] = ranking

        self.ranking_ = ranking
        # Select top `target_k` features by deterministic rank (tie-break by index).
        if int((ranking == 1).sum()) >= target_k:
            support = np.zeros(n_total, dtype=bool)
            ones = np.flatnonzero(ranking == 1)[:target_k]
            support[ones] = True
        else:
            order = np.argsort(ranking, kind="mergesort")
            support = np.zeros(n_total, dtype=bool)
            support[order[:target_k]] = True
        self.support_ = support
        return self

    def transform(self, X: Any) -> np.ndarray:
        X_arr = np.asarray(X, dtype=np.float64)
        return X_arr[:, self.support_]

    def get_support(self, indices: bool = False) -> np.ndarray:
        return np.flatnonzero(self.support_) if indices else self.support_.copy()


def suggest_lgbm_params(trial: optuna.Trial) -> dict[str, Any]:
    """Sample LightGBM hyperparameters inside the pre-registered Phase 2/4 space."""
    imbalance_mode = trial.suggest_categorical(
        "imbalance_mode", ["none", "is_unbalance", "scale_pos_weight"]
    )
    params: dict[str, Any] = {
        "num_leaves": trial.suggest_int("num_leaves", 15, 127),
        "max_depth": trial.suggest_int("max_depth", 4, 20),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
        "n_estimators": trial.suggest_int("n_estimators", 80, 350, step=10),
        "min_child_samples": trial.suggest_int("min_child_samples", 10, 80),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.4, 1.0),
        "reg_alpha": trial.suggest_float("reg_alpha", 1e-4, 5.0, log=True),
        "reg_lambda": trial.suggest_float("reg_lambda", 1e-4, 10.0, log=True),
        "imbalance_mode": imbalance_mode,
    }
    if imbalance_mode == "scale_pos_weight":
        params["scale_pos_weight"] = trial.suggest_float("scale_pos_weight", 1.5, 9.0)
    return params


def build_lgbm_classifier(
    params: dict[str, Any],
    *,
    random_state: int,
    n_jobs: int = 3,
) -> lgb.LGBMClassifier:
    """Instantiate LGBMClassifier from sampled hyperparameter dict."""
    subsample = float(params["subsample"])
    imbalance_mode = params.get("imbalance_mode", "none")

    kwargs: dict[str, Any] = {
        "boosting_type": "gbdt",
        "objective": "binary",
        "num_leaves": int(params["num_leaves"]),
        "max_depth": int(params["max_depth"]),
        "learning_rate": float(params["learning_rate"]),
        "n_estimators": int(params["n_estimators"]),
        "min_child_samples": int(params["min_child_samples"]),
        "subsample": subsample,
        "subsample_freq": 1 if subsample < 1.0 else 0,
        "colsample_bytree": float(params["colsample_bytree"]),
        "reg_alpha": float(params["reg_alpha"]),
        "reg_lambda": float(params["reg_lambda"]),
        "random_state": int(random_state),
        "n_jobs": int(n_jobs),
        "importance_type": "split",
        "verbose": -1,
    }
    if imbalance_mode == "is_unbalance":
        kwargs["is_unbalance"] = True
    elif imbalance_mode == "scale_pos_weight":
        kwargs["scale_pos_weight"] = float(params["scale_pos_weight"])
    return lgb.LGBMClassifier(**kwargs)


def make_pipeline_from_params(
    params: dict[str, Any],
    *,
    random_state: int,
    n_jobs: int = 3,
    use_rfe: bool = False,
    rfe_cache: dict[str, np.ndarray] | None = None,
) -> Pipeline:
    """Build a scikit-learn Pipeline (optionally with in-fold RFE selection)."""
    steps: list[tuple[str, Any]] = []
    if use_rfe:
        steps.append(
            (
                "rfe",
                CachedRFESelector(
                    n_features_to_select=int(params["n_features_to_select"]),
                    step=5,
                    min_features=19,
                    random_state=random_state,
                    n_jobs=n_jobs,
                    ranking_cache=rfe_cache,
                ),
            )
        )
    steps.append(("clf", build_lgbm_classifier(params, random_state=random_state, n_jobs=n_jobs)))
    return Pipeline(steps)


def run_nested_cv_fold(
    X: pd.DataFrame | np.ndarray,
    y: np.ndarray,
    groups: np.ndarray | None,
    tr_idx: np.ndarray,
    te_idx: np.ndarray,
    *,
    seed: int,
    fold: int,
    experiment_id: str,
    n_trials: int = 30,
    n_inner_splits: int = 3,
    n_jobs: int = 3,
    use_rfe: bool = False,
    extra_pipeline_steps: Callable[[optuna.Trial, int], list[tuple[str, Any]]] | None = None,
    pipeline_pre_steps: tuple[tuple[str, Any], ...] | list[tuple[str, Any]] | None = None,
    cache_pre_steps: bool = True,
) -> tuple[dict[str, Any], Pipeline]:
    """Run inner CV (StratifiedGroupKFold if groups given else StratifiedKFold), Optuna, OOF F1, and outer eval."""
    t_start = time.perf_counter()
    is_df = isinstance(X, pd.DataFrame)
    X_tr = X.iloc[tr_idx] if is_df else X[tr_idx]
    X_te = X.iloc[te_idx] if is_df else X[te_idx]
    y_tr = y[tr_idx]
    y_te = y[te_idx]

    if groups is not None:
        g_tr = groups[tr_idx]
        inner_cv = StratifiedGroupKFold(
            n_splits=n_inner_splits,
            shuffle=True,
            random_state=seed * 10 + fold,
        )
        inner_splits = list(inner_cv.split(np.zeros(len(y_tr)), y_tr, g_tr))
    else:
        inner_cv = StratifiedKFold(
            n_splits=n_inner_splits,
            shuffle=True,
            random_state=seed * 10 + fold,
        )
        inner_splits = list(inner_cv.split(np.zeros(len(y_tr)), y_tr))
    rfe_cache: dict[str, np.ndarray] = {}

    inner_transformed: dict[int, tuple[Any, Any]] = {}
    if pipeline_pre_steps is not None and cache_pre_steps and extra_pipeline_steps is None:
        for s_idx, (in_tr, in_va) in enumerate(inner_splits):
            X_in_tr = X_tr.iloc[in_tr] if is_df else X_tr[in_tr]
            X_in_va = X_tr.iloc[in_va] if is_df else X_tr[in_va]
            pre_pipe = Pipeline([(nm, clone(est)) for nm, est in pipeline_pre_steps])
            pre_pipe.fit(X_in_tr, y_tr[in_tr])
            inner_transformed[s_idx] = (pre_pipe.transform(X_in_tr), pre_pipe.transform(X_in_va))

    def build_pipe(params: dict[str, Any], trial_obj: optuna.Trial | None = None) -> Pipeline:
        steps: list[tuple[str, Any]] = []
        if pipeline_pre_steps is not None:
            for step_name, estimator in pipeline_pre_steps:
                steps.append((step_name, clone(estimator)))
        if extra_pipeline_steps is not None and trial_obj is not None:
            steps.extend(extra_pipeline_steps(trial_obj, seed))
        if use_rfe:
            steps.append(
                (
                    "rfe",
                    CachedRFESelector(
                        n_features_to_select=int(params["n_features_to_select"]),
                        step=5,
                        min_features=19,
                        random_state=seed,
                        n_jobs=n_jobs,
                        ranking_cache=rfe_cache,
                    ),
                )
            )
        steps.append(("clf", build_lgbm_classifier(params, random_state=seed, n_jobs=n_jobs)))
        return Pipeline(steps)

    def objective(trial: optuna.Trial) -> float:
        params = suggest_lgbm_params(trial)
        if use_rfe:
            params["n_features_to_select"] = trial.suggest_categorical(
                "n_features_to_select", list(RFE_FEATURE_COUNTS)
            )
        scores: list[float] = []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for s_idx, (in_tr, in_va) in enumerate(inner_splits):
                if s_idx in inner_transformed:
                    X_in_tr, X_in_va = inner_transformed[s_idx]
                    pipe = make_pipeline_from_params(
                        params,
                        random_state=seed,
                        n_jobs=n_jobs,
                        use_rfe=use_rfe,
                        rfe_cache=rfe_cache,
                    )
                else:
                    X_in_tr = X_tr.iloc[in_tr] if is_df else X_tr[in_tr]
                    X_in_va = X_tr.iloc[in_va] if is_df else X_tr[in_va]
                    pipe = build_pipe(params, trial)
                pipe.fit(X_in_tr, y_tr[in_tr])
                proba = pipe.predict_proba(X_in_va)[:, 1]
                from sklearn.metrics import average_precision_score

                scores.append(float(average_precision_score(y_tr[in_va], proba)))
        return float(np.mean(scores))

    sampler = optuna.samplers.TPESampler(seed=seed * 100 + fold)
    study = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best_params = dict(study.best_trial.params)
    best_inner_pr_auc = float(study.best_value)

    # Compute strictly out-of-fold validation probabilities on outer train to choose tau*.
    oof_proba = np.zeros(len(y_tr), dtype=float)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for s_idx, (in_tr, in_va) in enumerate(inner_splits):
            if s_idx in inner_transformed:
                X_in_tr, X_in_va = inner_transformed[s_idx]
                pipe = make_pipeline_from_params(
                    best_params,
                    random_state=seed,
                    n_jobs=n_jobs,
                    use_rfe=use_rfe,
                    rfe_cache=rfe_cache,
                )
            else:
                X_in_tr = X_tr.iloc[in_tr] if is_df else X_tr[in_tr]
                X_in_va = X_tr.iloc[in_va] if is_df else X_tr[in_va]
                pipe = build_pipe(best_params)
            pipe.fit(X_in_tr, y_tr[in_tr])
            oof_proba[in_va] = pipe.predict_proba(X_in_va)[:, 1]

    tau_star = find_best_f1_threshold(y_tr, oof_proba)

    # Refit final pipeline on the full outer training slice and evaluate on outer test.
    final_pipe = build_pipe(best_params)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        final_pipe.fit(X_tr, y_tr)
        test_proba = final_pipe.predict_proba(X_te)[:, 1]

    train_time = time.perf_counter() - t_start
    metrics = evaluate_predictions(y_te, test_proba, tau_star)

    if use_rfe:
        n_selected = int(final_pipe.named_steps["rfe"].support_.sum())
    else:
        n_selected = int(final_pipe.named_steps["clf"].n_features_in_)

    row = {
        "experiment": experiment_id,
        "seed": int(seed),
        "fold": int(fold),
        "PR-AUC": metrics["pr_auc"],
        "F1": metrics["f1"],
        "P": metrics["precision"],
        "R": metrics["recall"],
        "ROC-AUC": metrics["roc_auc"],
        "Recall@P>=0.9": metrics["recall_at_p90"],
        "p90_fallback": metrics["p90_fallback"],
        "Accuracy": metrics["accuracy"],
        "threshold": metrics["threshold"],
        "train_time": float(train_time),
        "n_features": n_selected,
        "tp": metrics["tp"],
        "fp": metrics["fp"],
        "tn": metrics["tn"],
        "fn": metrics["fn"],
        "inner_cv_pr_auc": best_inner_pr_auc,
        "best_params_json": json.dumps(best_params, sort_keys=True),
    }
    return row, final_pipe


def _run_fold_worker(task: dict[str, Any]) -> dict[str, Any]:
    df_X = task["X"]
    y = task["y"]
    groups = task["groups"]
    split_path = Path(task["split_path"])
    tr_idx, te_idx, payload = load_split_indices(task["df_meta"], split_path)
    row, _ = run_nested_cv_fold(
        df_X,
        y,
        groups,
        tr_idx,
        te_idx,
        seed=int(payload["seed"]),
        fold=int(payload["fold"]),
        experiment_id=task["experiment_id"],
        n_trials=task["n_trials"],
        n_inner_splits=task["n_inner_splits"],
        n_jobs=task["lgbm_jobs"],
        use_rfe=task["use_rfe"],
        pipeline_pre_steps=task.get("pipeline_pre_steps"),
    )
    return row


def run_25fold_experiment(
    df_meta: pd.DataFrame,
    X: pd.DataFrame,
    *,
    split_paths: list[Path],
    group_col: str | None,
    experiment_id: str,
    n_trials: int = 30,
    n_inner_splits: int = 3,
    use_rfe: bool = False,
    pipeline_pre_steps: tuple[tuple[str, Any], ...] | list[tuple[str, Any]] | None = None,
    max_workers: int = 4,
    lgbm_jobs: int = 3,
) -> pd.DataFrame:
    """Execute a 25-fold CV experiment (grouped or stratified random) across frozen split JSON files."""
    y = df_meta["label"].to_numpy(dtype=int)
    groups = df_meta[group_col].astype(str).to_numpy() if group_col is not None else None
    meta_minimal = df_meta[["sample_id"]].copy()

    tasks = [
        {
            "df_meta": meta_minimal,
            "X": X,
            "y": y,
            "groups": groups,
            "split_path": str(sp),
            "experiment_id": experiment_id,
            "n_trials": n_trials,
            "n_inner_splits": n_inner_splits,
            "use_rfe": use_rfe,
            "pipeline_pre_steps": pipeline_pre_steps,
            "lgbm_jobs": lgbm_jobs,
        }
        for sp in split_paths
    ]

    rows: list[dict[str, Any]] = []
    if max_workers <= 1:
        for t in tasks:
            row = _run_fold_worker(t)
            rows.append(row)
            print(
                f"[{experiment_id}] seed={row['seed']} fold={row['fold']} "
                f"PR-AUC={row['PR-AUC']:.4f} F1={row['F1']:.4f} "
                f"feats={row['n_features']} time={row['train_time']:.1f}s",
                flush=True,
            )
    else:
        with ProcessPoolExecutor(max_workers=max_workers) as ex:
            futs = [ex.submit(_run_fold_worker, t) for t in tasks]
            for fut in as_completed(futs):
                row = fut.result()
                rows.append(row)
                print(
                    f"[{experiment_id}] seed={row['seed']} fold={row['fold']} "
                    f"PR-AUC={row['PR-AUC']:.4f} F1={row['F1']:.4f} "
                    f"feats={row['n_features']} time={row['train_time']:.1f}s",
                    flush=True,
                )

    res_df = pd.DataFrame(rows).sort_values(["seed", "fold"]).reset_index(drop=True)
    return res_df
