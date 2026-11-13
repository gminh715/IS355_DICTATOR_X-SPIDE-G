"""E0 paper reproduction runner matching X-SPIDE's official notebooks and random 5-fold splits."""

from __future__ import annotations

import json
import time
import warnings
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import GridSearchCV, StratifiedKFold, train_test_split

from src.models.data_prep import (
    PAPER_43_FEATURES,
    PAPER_47_FEATURES,
    PAPER_PUBLISHED_E0_METRICS,
    load_contracts_dataset,
    load_split_indices,
    prepare_xspide_99_features,
)
from src.models.metrics import evaluate_predictions


def _deltas_vs_published(metrics: dict[str, Any]) -> dict[str, float]:
    return {
        "delta_Accuracy": float(metrics["accuracy"] - PAPER_PUBLISHED_E0_METRICS["accuracy"]),
        "delta_P": float(metrics["precision"] - PAPER_PUBLISHED_E0_METRICS["precision"]),
        "delta_R": float(metrics["recall"] - PAPER_PUBLISHED_E0_METRICS["recall"]),
        "delta_F1": float(metrics["f1"] - PAPER_PUBLISHED_E0_METRICS["f1"]),
        "delta_ROC-AUC": float(metrics["roc_auc"] - PAPER_PUBLISHED_E0_METRICS["roc_auc"]),
    }


def _eval_single_fit(
    clf: lgb.LGBMClassifier,
    X_tr: pd.DataFrame,
    y_tr: np.ndarray,
    X_te: pd.DataFrame,
    y_te: np.ndarray,
    *,
    run_id: str,
    split_type: str,
    seed: int,
    fold: int | str,
    notes: str = "",
) -> dict[str, Any]:
    t0 = time.perf_counter()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        clf.fit(X_tr, y_tr)
        proba = clf.predict_proba(X_te)[:, 1]
    elapsed = time.perf_counter() - t0
    m = evaluate_predictions(y_te, proba, threshold=0.5)
    row: dict[str, Any] = {
        "run_id": run_id,
        "split_type": split_type,
        "seed": seed,
        "fold": str(fold),
        "n_features": int(X_tr.shape[1]),
        "n_train": int(len(y_tr)),
        "n_test": int(len(y_te)),
        "PR-AUC": m["pr_auc"],
        "ROC-AUC": m["roc_auc"],
        "F1": m["f1"],
        "P": m["precision"],
        "R": m["recall"],
        "Accuracy": m["accuracy"],
        "Recall@P>=0.9": m["recall_at_p90"],
        "tp": m["tp"],
        "fp": m["fp"],
        "tn": m["tn"],
        "fn": m["fn"],
        "train_time": float(elapsed),
        **_deltas_vs_published(m),
        "notes": notes,
    }
    return row


def run_e0_reproduction(repo_root: Path) -> pd.DataFrame:
    """Run all E0 paper-style evaluations on S_full and return results DataFrame."""
    df_full = load_contracts_dataset(repo_root, subset="S_full")
    X_99 = prepare_xspide_99_features(df_full, normalize_opcodes=True)
    y = df_full["label"].to_numpy(dtype=int)

    rows: list[dict[str, Any]] = [
        {
            "run_id": "published_xspide_paper",
            "split_type": "paper_reported",
            "seed": 42,
            "fold": "reported",
            "n_features": 47,
            "n_train": 6329,
            "n_test": 1117,
            "PR-AUC": np.nan,
            "ROC-AUC": PAPER_PUBLISHED_E0_METRICS["roc_auc"],
            "F1": PAPER_PUBLISHED_E0_METRICS["f1"],
            "P": PAPER_PUBLISHED_E0_METRICS["precision"],
            "R": PAPER_PUBLISHED_E0_METRICS["recall"],
            "Accuracy": PAPER_PUBLISHED_E0_METRICS["accuracy"],
            "Recall@P>=0.9": np.nan,
            "tp": np.nan,
            "fp": np.nan,
            "tn": np.nan,
            "fn": np.nan,
            "train_time": 0.0,
            "delta_Accuracy": 0.0,
            "delta_P": 0.0,
            "delta_R": 0.0,
            "delta_F1": 0.0,
            "delta_ROC-AUC": 0.0,
            "notes": "Pennella et al., IEEE Access 2025 [1]",
        }
    ]

    # Exact 85/15 stratified holdout used in X-SPIDE's notebooks (2210, 2510, 1009, 2710).
    idx = np.arange(len(df_full))
    tr_85, te_15 = train_test_split(idx, test_size=0.15, random_state=42, stratify=y)

    # 1. Exact 1009_best_features_SHAP.ipynb (47 features, is_unbalance=True)
    clf_1009 = lgb.LGBMClassifier(
        boosting_type="gbdt",
        objective="binary",
        is_unbalance=True,
        learning_rate=0.1,
        n_estimators=140,
        max_depth=15,
        colsample_bytree=0.5,
        reg_alpha=0.2,
        reg_lambda=1.0,
        random_state=42,
        n_jobs=4,
        importance_type="split",
        verbose=-1,
    )
    rows.append(
        _eval_single_fit(
            clf_1009,
            X_99.iloc[tr_85][list(PAPER_47_FEATURES)],
            y[tr_85],
            X_99.iloc[te_15][list(PAPER_47_FEATURES)],
            y[te_15],
            run_id="E0_1009_47feats_unbal",
            split_type="random_85_15_stratified",
            seed=42,
            fold="holdout_15pct",
            notes="Exact code/1009_best_features_SHAP.ipynb config (47 feats, is_unbalance=True)",
        )
    )

    # 2. Same 47 features with is_unbalance=False
    clf_1009_no_unbal = lgb.LGBMClassifier(
        boosting_type="gbdt",
        objective="binary",
        is_unbalance=False,
        learning_rate=0.1,
        n_estimators=140,
        max_depth=15,
        colsample_bytree=0.5,
        reg_alpha=0.2,
        reg_lambda=1.0,
        random_state=42,
        n_jobs=4,
        importance_type="split",
        verbose=-1,
    )
    rows.append(
        _eval_single_fit(
            clf_1009_no_unbal,
            X_99.iloc[tr_85][list(PAPER_47_FEATURES)],
            y[tr_85],
            X_99.iloc[te_15][list(PAPER_47_FEATURES)],
            y[te_15],
            run_id="E0_1009_47feats_default",
            split_type="random_85_15_stratified",
            seed=42,
            fold="holdout_15pct",
            notes="47 feats with is_unbalance=False at 0.5 threshold",
        )
    )

    # 3. Exact 2710_best_features_SHAP.ipynb (43 features)
    clf_2710 = lgb.LGBMClassifier(
        boosting_type="gbdt",
        objective="binary",
        learning_rate=0.1,
        n_estimators=140,
        max_depth=20,
        colsample_bytree=0.8,
        reg_alpha=0.0,
        reg_lambda=1.0,
        random_state=42,
        n_jobs=4,
        importance_type="split",
        verbose=-1,
    )
    rows.append(
        _eval_single_fit(
            clf_2710,
            X_99.iloc[tr_85][list(PAPER_43_FEATURES)],
            y[tr_85],
            X_99.iloc[te_15][list(PAPER_43_FEATURES)],
            y[te_15],
            run_id="E0_2710_43feats",
            split_type="random_85_15_stratified",
            seed=42,
            fold="holdout_15pct",
            notes="Exact code/2710_best_features_SHAP.ipynb config (43 feats)",
        )
    )

    # 4. Paper GridSearchCV (10-fold CV, scoring='roc_auc') on 99 features (85/15 train split)
    t_grid0 = time.perf_counter()
    param_grid = {
        "learning_rate": [0.1, 0.01],
        "n_estimators": [100, 140],
        "max_depth": [10, 15, 20],
        "colsample_bytree": [0.5, 0.8],
        "reg_alpha": [0.0, 0.2],
        "reg_lambda": [1.0, 10.0],
    }
    gs = GridSearchCV(
        estimator=lgb.LGBMClassifier(
            boosting_type="gbdt",
            objective="binary",
            random_state=42,
            n_jobs=2,
            importance_type="split",
            verbose=-1,
        ),
        param_grid=param_grid,
        cv=StratifiedKFold(n_splits=10, shuffle=False),
        scoring="roc_auc",
        n_jobs=4,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        gs.fit(X_99.iloc[tr_85], y[tr_85])
        grid_proba = gs.best_estimator_.predict_proba(X_99.iloc[te_15])[:, 1]
    grid_time = time.perf_counter() - t_grid0
    m_grid = evaluate_predictions(y[te_15], grid_proba, threshold=0.5)
    rows.append(
        {
            "run_id": "E0_gridsearch10cv_99feats",
            "split_type": "random_85_15_stratified",
            "seed": 42,
            "fold": "holdout_15pct",
            "n_features": 99,
            "n_train": int(len(tr_85)),
            "n_test": int(len(te_15)),
            "PR-AUC": m_grid["pr_auc"],
            "ROC-AUC": m_grid["roc_auc"],
            "F1": m_grid["f1"],
            "P": m_grid["precision"],
            "R": m_grid["recall"],
            "Accuracy": m_grid["accuracy"],
            "Recall@P>=0.9": m_grid["recall_at_p90"],
            "tp": m_grid["tp"],
            "fp": m_grid["fp"],
            "tn": m_grid["tn"],
            "fn": m_grid["fn"],
            "train_time": float(grid_time),
            **_deltas_vs_published(m_grid),
            "notes": f"10-fold GridSearchCV(roc_auc) best={json.dumps(gs.best_params_, sort_keys=True)}",
        }
    )

    # 5. Frozen 5-fold random CV (S_full_E0_random_seed42_fold{0..4}.json) for 47 feats & 99 feats
    splits_dir = repo_root / "splits"
    for label_run, cols, clf_proto in (
        (
            "E0_random5fold_47feats_unbal",
            list(PAPER_47_FEATURES),
            lgb.LGBMClassifier(
                boosting_type="gbdt",
                objective="binary",
                is_unbalance=True,
                learning_rate=0.1,
                n_estimators=140,
                max_depth=15,
                colsample_bytree=0.5,
                reg_alpha=0.2,
                reg_lambda=1.0,
                random_state=42,
                n_jobs=4,
                importance_type="split",
                verbose=-1,
            ),
        ),
        (
            "E0_random5fold_99feats_gridbest",
            list(X_99.columns),
            lgb.LGBMClassifier(
                boosting_type="gbdt",
                objective="binary",
                random_state=42,
                n_jobs=4,
                importance_type="split",
                verbose=-1,
                **gs.best_params_,
            ),
        ),
    ):
        fold_rows: list[dict[str, Any]] = []
        for fold_idx in range(5):
            sp = splits_dir / f"S_full_E0_random_seed42_fold{fold_idx}.json"
            tr_idx, te_idx, _ = load_split_indices(df_full, sp)
            clf_clone = lgb.LGBMClassifier(**clf_proto.get_params())
            r = _eval_single_fit(
                clf_clone,
                X_99.iloc[tr_idx][cols],
                y[tr_idx],
                X_99.iloc[te_idx][cols],
                y[te_idx],
                run_id=label_run,
                split_type="S_full_E0_random_5fold",
                seed=42,
                fold=fold_idx,
                notes=f"Frozen S_full_E0_random_seed42_fold{fold_idx}",
            )
            fold_rows.append(r)
            rows.append(r)

        mean_metrics = {
            "accuracy": float(np.mean([r["Accuracy"] for r in fold_rows])),
            "precision": float(np.mean([r["P"] for r in fold_rows])),
            "recall": float(np.mean([r["R"] for r in fold_rows])),
            "f1": float(np.mean([r["F1"] for r in fold_rows])),
            "roc_auc": float(np.mean([r["ROC-AUC"] for r in fold_rows])),
        }
        rows.append(
            {
                "run_id": f"{label_run}_mean",
                "split_type": "S_full_E0_random_5fold_mean",
                "seed": 42,
                "fold": "mean",
                "n_features": len(cols),
                "n_train": int(np.mean([r["n_train"] for r in fold_rows])),
                "n_test": int(np.mean([r["n_test"] for r in fold_rows])),
                "PR-AUC": float(np.mean([r["PR-AUC"] for r in fold_rows])),
                "ROC-AUC": mean_metrics["roc_auc"],
                "F1": mean_metrics["f1"],
                "P": mean_metrics["precision"],
                "R": mean_metrics["recall"],
                "Accuracy": mean_metrics["accuracy"],
                "Recall@P>=0.9": float(np.mean([r["Recall@P>=0.9"] for r in fold_rows])),
                "tp": float(np.sum([r["tp"] for r in fold_rows])),
                "fp": float(np.sum([r["fp"] for r in fold_rows])),
                "tn": float(np.sum([r["tn"] for r in fold_rows])),
                "fn": float(np.sum([r["fn"] for r in fold_rows])),
                "train_time": float(np.sum([r["train_time"] for r in fold_rows])),
                **_deltas_vs_published(mean_metrics),
                "notes": "Mean across 5 frozen random stratified folds (seed=42)",
            }
        )

    return pd.DataFrame(rows)
