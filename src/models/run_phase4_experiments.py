"""Execute Phase 4 experiments (E3-E4d), sensitivity analyses (S1-S4), E6 sanity check, and statistical tests."""

from __future__ import annotations

import argparse
import json
import time
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import optuna
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import average_precision_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline

from src.data.splits import DEFAULT_SEEDS
from src.models.data_prep import load_split_indices
from src.models.metrics import evaluate_predictions, find_best_f1_threshold
from src.models.phase4_features import load_e6_ponziguard_sanity_datasets, load_phase4_dataset
from src.models.tuning import build_lgbm_classifier, run_25fold_experiment, suggest_lgbm_params
from src.stats.tests import load_fold_sizes, run_pairwise_suite, stratified_bootstrap_ci

MAIN_EXPERIMENTS: tuple[str, ...] = ("E3", "E3b", "E3c", "E4", "E4b", "E4c", "E4d")

EXPERIMENT_DESCRIPTIONS: dict[str, str] = {
    "E1": "99 X-SPIDE baseline (S_code)",
    "E2": "In-fold RFE over 99 X-SPIDE features",
    "E3": "F-GSTAT transition statistics only (16)",
    "E3b": "F-BIGRAM opcode bigrams only (top-200 in-fold)",
    "E3c": "F-GSEM CFG + SCC + opcode PageRank only (15)",
    "E4": "99 X-SPIDE + F-GSTAT",
    "E4b": "99 X-SPIDE + F-BIGRAM (top-200 in-fold)",
    "E4c": "99 X-SPIDE + F-GSEM",
    "E4d": "99 X-SPIDE + F-BIGRAM + F-GSEM",
}

SENSITIVITY_SPECS: tuple[tuple[str, str, str | None], ...] = (
    ("E1_S0_random_5x5", "S_code_random", None),
    ("E1_S1_group_exact", "S_code_group_exact", "group_exact"),
    ("E4c_S1_group_exact", "S_code_group_exact", "group_exact"),
    ("E1_S2_cbor_stripped", "S_code_group_near", "group_near"),
    ("E4c_S2_raw_cbor", "S_code_group_near", "group_near"),
    ("E4c_S2_cbor_stripped", "S_code_group_near", "group_near"),
    ("E4b_S4_raw_opcodes", "S_code_group_near", "group_near"),
    ("E4c_S4_raw_opcodes", "S_code_group_near", "group_near"),
)

PREREGISTERED_COMPARISONS: tuple[tuple[str, str, str], ...] = (
    ("vs_E1", "E4", "E1"),
    ("vs_E1", "E4b", "E1"),
    ("vs_E1", "E4c", "E1"),
    ("vs_E1", "E2", "E1"),
    ("novelty_critical", "E4c", "E4b"),
    ("novelty_critical", "E4d", "E4b"),
    ("code_only", "E3c", "E3b"),
    ("code_only", "E3c", "E3"),
)

AUXILIARY_COMPARISONS: tuple[tuple[str, str, str], ...] = (
    ("auxiliary_vs_E1", "E4d", "E1"),
    ("auxiliary_vs_E1", "E3", "E1"),
    ("auxiliary_vs_E1", "E3b", "E1"),
    ("auxiliary_vs_E1", "E3c", "E1"),
    ("auxiliary_structural", "E3b", "E3"),
    ("auxiliary_incremental", "E4", "E4c"),
)


def _list_split_paths(splits_dir: Path, prefix: str) -> list[Path]:
    paths: list[Path] = []
    for seed in DEFAULT_SEEDS:
        for fold in range(5):
            sp = splits_dir / f"{prefix}_seed{seed}_fold{fold}.json"
            if not sp.exists():
                raise FileNotFoundError(f"Missing frozen split file: {sp}")
            paths.append(sp)
    return paths


def _run_or_load_experiment(
    repo_root: Path,
    results_dir: Path,
    *,
    config_name: str,
    split_prefix: str,
    group_col: str | None,
    n_trials: int,
    n_inner_splits: int,
    max_workers: int,
    lgbm_jobs: int,
    skip_existing: bool,
) -> pd.DataFrame:
    out_csv = results_dir / f"{config_name}_folds.csv"
    if skip_existing and out_csv.exists():
        df_existing = pd.read_csv(out_csv)
        if len(df_existing) == 25:
            print(f"[{config_name}] Using existing 25-fold results at {out_csv}", flush=True)
            return df_existing

    df_meta, X, pre_steps = load_phase4_dataset(repo_root, config_name)
    split_paths = _list_split_paths(repo_root / "splits", split_prefix)
    print(
        f"[{config_name}] Running 25-fold CV ({split_prefix}, X.shape={X.shape}, pre_steps={bool(pre_steps)})...",
        flush=True,
    )
    res_df = run_25fold_experiment(
        df_meta,
        X,
        split_paths=split_paths,
        group_col=group_col,
        experiment_id=config_name,
        n_trials=n_trials,
        n_inner_splits=n_inner_splits,
        use_rfe=False,
        pipeline_pre_steps=pre_steps,
        max_workers=max_workers,
        lgbm_jobs=lgbm_jobs,
    )
    res_df.to_csv(out_csv, index=False)
    print(
        f"[{config_name}] Done -> {out_csv.name}: "
        f"PR-AUC={res_df['PR-AUC'].mean():.4f}+/-{res_df['PR-AUC'].std(ddof=1):.4f}, "
        f"F1={res_df['F1'].mean():.4f}+/-{res_df['F1'].std(ddof=1):.4f}",
        flush=True,
    )
    return res_df


def run_e6_sanity_check(
    repo_root: Path,
    results_dir: Path,
    *,
    n_trials: int = 30,
    n_inner_splits: int = 3,
    lgbm_jobs: int = 4,
    seed: int = 42,
    skip_existing: bool = True,
) -> pd.DataFrame:
    """Run conditional Dataset 2 (PonziGuard) code-only sanity check under Risk R6."""
    out_csv = results_dir / "E6_sanity_check.csv"
    pred_csv = results_dir / "E6_predictions.csv"
    if skip_existing and out_csv.exists() and pred_csv.exists():
        print(f"[E6] Using existing sanity-check results at {out_csv}", flush=True)
        return pd.read_csv(out_csv)

    t_start = time.perf_counter()
    df_s_code, X_train, df_pg, X_pg, pre_steps = load_e6_ponziguard_sanity_datasets(repo_root)
    y_train = df_s_code["label"].to_numpy(dtype=int)
    groups = df_s_code["group_near"].astype(str).to_numpy()
    y_pg = df_pg["label"].to_numpy(dtype=int)

    inner_cv = StratifiedGroupKFold(n_splits=n_inner_splits, shuffle=True, random_state=seed)
    inner_splits = list(inner_cv.split(np.zeros(len(y_train)), y_train, groups))

    def build_pipe(params: dict[str, Any]) -> Pipeline:
        steps = [(name, clone(est)) for name, est in pre_steps]
        steps.append(("clf", build_lgbm_classifier(params, random_state=seed, n_jobs=lgbm_jobs)))
        return Pipeline(steps)

    def objective(trial: optuna.Trial) -> float:
        params = suggest_lgbm_params(trial)
        scores: list[float] = []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for in_tr, in_va in inner_splits:
                pipe = build_pipe(params)
                pipe.fit(X_train.iloc[in_tr], y_train[in_tr])
                proba = pipe.predict_proba(X_train.iloc[in_va])[:, 1]
                scores.append(float(average_precision_score(y_train[in_va], proba)))
        return float(np.mean(scores))

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    best_params = dict(study.best_trial.params)
    best_inner_pr_auc = float(study.best_value)

    oof_proba = np.zeros(len(y_train), dtype=float)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for in_tr, in_va in inner_splits:
            pipe = build_pipe(best_params)
            pipe.fit(X_train.iloc[in_tr], y_train[in_tr])
            oof_proba[in_va] = pipe.predict_proba(X_train.iloc[in_va])[:, 1]

    tau_star = find_best_f1_threshold(y_train, oof_proba)

    final_pipe = build_pipe(best_params)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        final_pipe.fit(X_train, y_train)
        pg_proba = final_pipe.predict_proba(X_pg)[:, 1]

    train_time = time.perf_counter() - t_start
    point_metrics = evaluate_predictions(y_pg, pg_proba, tau_star)
    boot_ci = stratified_bootstrap_ci(y_pg, pg_proba, threshold=tau_star, n_resamples=1000, seed=seed)
    n_features = int(final_pipe.named_steps["clf"].n_features_in_)

    pred_df = df_pg[["sample_id", "code_hash", "label"]].copy()
    pred_df["y_proba"] = pg_proba
    pred_df["y_pred"] = (pg_proba >= tau_star).astype(int)
    pred_df["threshold"] = tau_star
    pred_df.to_csv(pred_csv, index=False)

    rows: list[dict[str, Any]] = []
    for metric_name, stats in boot_ci.items():
        rows.append(
            {
                "experiment": "E6_sanity_check",
                "risk_flag": "R6_SANITY_CHECK_ONLY (<30 non-overlapping Ponzi contracts)",
                "metric": metric_name,
                "point": stats["point"],
                "ci95_low": stats["ci_low"],
                "ci95_high": stats["ci_high"],
                "boot_std": stats["boot_std"],
                "n_resamples": 1000,
                "n_train": int(len(y_train)),
                "n_train_ponzi": int(y_train.sum()),
                "n_test": int(len(y_pg)),
                "n_test_ponzi": int(y_pg.sum()),
                "n_test_nonponzi": int((y_pg == 0).sum()),
                "n_features": n_features,
                "threshold": float(tau_star),
                "inner_cv_pr_auc": best_inner_pr_auc,
                "tp": point_metrics["tp"],
                "fp": point_metrics["fp"],
                "tn": point_metrics["tn"],
                "fn": point_metrics["fn"],
                "train_time_s": float(train_time),
                "best_params_json": json.dumps(best_params, sort_keys=True),
            }
        )
    res_df = pd.DataFrame(rows)
    res_df.to_csv(out_csv, index=False)
    print(
        f"[E6] PonziGuard sanity check (n={len(y_pg)}, ponzi={int(y_pg.sum())}): "
        f"PR-AUC={point_metrics['pr_auc']:.4f}, F1={point_metrics['f1']:.4f}, "
        f"P={point_metrics['precision']:.4f}, R={point_metrics['recall']:.4f}",
        flush=True,
    )
    return res_df


def compute_phase4_summaries(repo_root: Path, results_dir: Path) -> None:
    """Build model_comparison.csv, stat_tests.csv, and sensitivity_summary.csv."""
    all_main = ("E1", "E2", "E3", "E3b", "E3c", "E4", "E4b", "E4c", "E4d")
    fold_tables: dict[str, pd.DataFrame] = {}
    for exp_id in all_main:
        p = results_dir / f"{exp_id}_folds.csv"
        if not p.exists():
            raise FileNotFoundError(f"Missing fold table required for comparison: {p}")
        fold_tables[exp_id] = pd.read_csv(p).sort_values(["seed", "fold"]).reset_index(drop=True)

    e1_pr = float(fold_tables["E1"]["PR-AUC"].mean())
    e1_f1 = float(fold_tables["E1"]["F1"].mean())

    comp_rows: list[dict[str, Any]] = []
    for exp_id in all_main:
        df_f = fold_tables[exp_id]
        n_feats_vals = df_f["n_features"].astype(float)
        n_feats_str = (
            str(int(n_feats_vals.iloc[0]))
            if n_feats_vals.nunique() == 1
            else f"{n_feats_vals.mean():.1f} [{int(n_feats_vals.min())}-{int(n_feats_vals.max())}]"
        )
        comp_rows.append(
            {
                "experiment": exp_id,
                "feature_set": EXPERIMENT_DESCRIPTIONS[exp_id],
                "n_folds": len(df_f),
                "n_features": n_feats_str,
                "PR_AUC_mean": float(df_f["PR-AUC"].mean()),
                "PR_AUC_std": float(df_f["PR-AUC"].std(ddof=1)),
                "Delta_PR_AUC_vs_E1": float(df_f["PR-AUC"].mean() - e1_pr),
                "F1_mean": float(df_f["F1"].mean()),
                "F1_std": float(df_f["F1"].std(ddof=1)),
                "Delta_F1_vs_E1": float(df_f["F1"].mean() - e1_f1),
                "P_mean": float(df_f["P"].mean()),
                "P_std": float(df_f["P"].std(ddof=1)),
                "R_mean": float(df_f["R"].mean()),
                "R_std": float(df_f["R"].std(ddof=1)),
                "ROC_AUC_mean": float(df_f["ROC-AUC"].mean()),
                "ROC_AUC_std": float(df_f["ROC-AUC"].std(ddof=1)),
                "Recall_at_P90_mean": float(df_f["Recall@P>=0.9"].mean()),
                "Recall_at_P90_std": float(df_f["Recall@P>=0.9"].std(ddof=1)),
                "p90_fallback_folds": int(df_f["p90_fallback"].sum()),
                "Accuracy_mean": float(df_f["Accuracy"].mean()),
                "Accuracy_std": float(df_f["Accuracy"].std(ddof=1)),
                "threshold_mean": float(df_f["threshold"].mean()),
                "train_time_mean_s": float(df_f["train_time"].mean()),
            }
        )
    comp_df = pd.DataFrame(comp_rows)
    comp_df.to_csv(results_dir / "model_comparison.csv", index=False)

    fold_sizes_near = load_fold_sizes(repo_root / "splits", split_prefix="S_code_group_near")

    stat_parts: list[pd.DataFrame] = []

    df_prereg = run_pairwise_suite(
        fold_tables,
        PREREGISTERED_COMPARISONS,
        fold_sizes_near,
        metric="PR-AUC",
        apply_holm=True,
        mde=0.02,
        alpha=0.05,
    )
    df_prereg["test_suite"] = "preregistered_holm_8"
    df_prereg["paired_same_splits"] = True
    stat_parts.append(df_prereg)

    df_aux = run_pairwise_suite(
        fold_tables,
        AUXILIARY_COMPARISONS,
        fold_sizes_near,
        metric="PR-AUC",
        apply_holm=False,
    )
    df_aux["test_suite"] = "auxiliary_pr_auc"
    df_aux["paired_same_splits"] = True
    stat_parts.append(df_aux)

    df_f1_sec = run_pairwise_suite(
        fold_tables,
        (*PREREGISTERED_COMPARISONS, *AUXILIARY_COMPARISONS),
        fold_sizes_near,
        metric="F1",
        apply_holm=False,
    )
    df_f1_sec["test_suite"] = "secondary_f1_unadjusted"
    df_f1_sec["paired_same_splits"] = True
    stat_parts.append(df_f1_sec)

    # Sensitivity suites (S2, S4 strictly paired on S_code_group_near)
    sens_tables = dict(fold_tables)
    for cfg_name, _, _ in SENSITIVITY_SPECS:
        p = results_dir / f"{cfg_name}_folds.csv"
        if p.exists():
            sens_tables[cfg_name] = pd.read_csv(p).sort_values(["seed", "fold"]).reset_index(drop=True)

    paired_sens_pairs: list[tuple[str, str, str]] = []
    for grp, a, b in [
        ("S2_cbor", "E1_S2_cbor_stripped", "E1"),
        ("S2_cbor", "E4c_S2_raw_cbor", "E4c"),
        ("S2_cbor", "E4c_S2_cbor_stripped", "E4c"),
        ("S4_norm", "E4b_S4_raw_opcodes", "E4b"),
        ("S4_norm", "E4c_S4_raw_opcodes", "E4c"),
    ]:
        if a in sens_tables and b in sens_tables:
            paired_sens_pairs.append((grp, a, b))

    if paired_sens_pairs:
        for metric_name in ("PR-AUC", "F1"):
            df_sp = run_pairwise_suite(
                sens_tables,
                paired_sens_pairs,
                fold_sizes_near,
                metric=metric_name,
                apply_holm=False,
            )
            df_sp["test_suite"] = f"sensitivity_paired_{metric_name.lower()}"
            df_sp["paired_same_splits"] = True
            stat_parts.append(df_sp)

    stat_df = pd.concat(stat_parts, ignore_index=True)
    stat_df.to_csv(results_dir / "stat_tests.csv", index=False)

    # Build concise sensitivity summary CSV covering S1, S2, S3 (N/A), S4.
    sens_rows: list[dict[str, Any]] = []

    def _add_sens_row(study: str, variant: str, ref: str, *, paired: bool, notes: str) -> None:
        if variant not in sens_tables or ref not in sens_tables:
            return
        dv = sens_tables[variant]
        dr = sens_tables[ref]
        sens_rows.append(
            {
                "study": study,
                "variant": variant,
                "reference": ref,
                "paired_same_splits": paired,
                "variant_PR_AUC_mean": float(dv["PR-AUC"].mean()),
                "variant_PR_AUC_std": float(dv["PR-AUC"].std(ddof=1)),
                "ref_PR_AUC_mean": float(dr["PR-AUC"].mean()),
                "Delta_PR_AUC": float(dv["PR-AUC"].mean() - dr["PR-AUC"].mean()),
                "variant_F1_mean": float(dv["F1"].mean()),
                "variant_F1_std": float(dv["F1"].std(ddof=1)),
                "ref_F1_mean": float(dr["F1"].mean()),
                "Delta_F1": float(dv["F1"].mean() - dr["F1"].mean()),
                "notes": notes,
            }
        )

    _add_sens_row(
        "S0_clone_leakage_control",
        "E1_S0_random_5x5",
        "E1",
        paired=False,
        notes="random 5x5 nested vs group_near 5x5 nested under identical Optuna+tau* protocol (total pure clone leakage)",
    )
    _add_sens_row(
        "S0_exact_clone_control",
        "E1_S0_random_5x5",
        "E1_S1_group_exact",
        paired=False,
        notes="random 5x5 nested vs group_exact 5x5 nested under identical Optuna+tau* protocol (pure exact-clone leakage)",
    )
    _add_sens_row("S1_split_granularity", "E1_S1_group_exact", "E1", paired=False, notes="group_exact vs group_near (unpaired split partitions)")
    _add_sens_row("S1_split_granularity", "E4c_S1_group_exact", "E4c", paired=False, notes="group_exact vs group_near (unpaired split partitions)")
    _add_sens_row("S2_cbor_metadata", "E1_S2_cbor_stripped", "E1", paired=True, notes="76 opcodes recomputed from stripped_bytecode_hex vs raw CSV 99")
    _add_sens_row("S2_cbor_metadata", "E4c_S2_raw_cbor", "E4c", paired=True, notes="F-GSEM from raw bytecode_hex vs stripped_bytecode_hex")
    _add_sens_row("S2_cbor_metadata", "E4c_S2_cbor_stripped", "E4c", paired=True, notes="Both 76 opcodes and F-GSEM from stripped_bytecode_hex")
    sens_rows.append(
        {
            "study": "S3_temporal_holdout",
            "variant": "N/A",
            "reference": "E1/E4c",
            "paired_same_splits": False,
            "variant_PR_AUC_mean": float("nan"),
            "variant_PR_AUC_std": float("nan"),
            "ref_PR_AUC_mean": float("nan"),
            "Delta_PR_AUC": float("nan"),
            "variant_F1_mean": float("nan"),
            "variant_F1_std": float("nan"),
            "ref_F1_mean": float("nan"),
            "Delta_F1": float("nan"),
            "notes": "Not feasible: block_number is 100% <NA> (bq_available=False in Phase 1; no temporal holdout split)",
        }
    )
    _add_sens_row("S4_mnemonic_norm", "E4b_S4_raw_opcodes", "E4b", paired=True, notes="Raw unnormalized opcodes (PUSH1..32) vs normalized families in F-BIGRAM")
    _add_sens_row("S4_mnemonic_norm", "E4c_S4_raw_opcodes", "E4c", paired=True, notes="Raw unnormalized opcodes in F-GSEM transition PageRank vs normalized")

    pd.DataFrame(sens_rows).to_csv(results_dir / "sensitivity_summary.csv", index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Phase 4 experiments, sensitivity analyses, E6, and stats.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--n-trials", type=int, default=30)
    parser.add_argument("--n-inner-splits", type=int, default=3)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--lgbm-jobs", type=int, default=3)
    parser.add_argument("--no-skip", action="store_true", help="Re-run even if 25-fold CSV already exists.")
    parser.add_argument("--only", nargs="*", default=None, help="Subset of tasks: main, sens, e6, stats")
    parser.add_argument("--configs", nargs="*", default=None, help="Optional filter of exact config names")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    results_dir = repo_root / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    skip_existing = not args.no_skip
    selected = set(args.only) if args.only else {"main", "sens", "e6", "stats"}
    config_filter = set(args.configs) if args.configs else None

    if "main" in selected:
        for exp_id in MAIN_EXPERIMENTS:
            if config_filter is not None and exp_id not in config_filter:
                continue
            _run_or_load_experiment(
                repo_root,
                results_dir,
                config_name=exp_id,
                split_prefix="S_code_group_near",
                group_col="group_near",
                n_trials=args.n_trials,
                n_inner_splits=args.n_inner_splits,
                max_workers=args.max_workers,
                lgbm_jobs=args.lgbm_jobs,
                skip_existing=skip_existing,
            )

    if "sens" in selected:
        for cfg_name, split_prefix, group_col in SENSITIVITY_SPECS:
            if config_filter is not None and cfg_name not in config_filter:
                continue
            _run_or_load_experiment(
                repo_root,
                results_dir,
                config_name=cfg_name,
                split_prefix=split_prefix,
                group_col=group_col,
                n_trials=args.n_trials,
                n_inner_splits=args.n_inner_splits,
                max_workers=args.max_workers,
                lgbm_jobs=args.lgbm_jobs,
                skip_existing=skip_existing,
            )

    if "e6" in selected:
        run_e6_sanity_check(
            repo_root,
            results_dir,
            n_trials=args.n_trials,
            n_inner_splits=args.n_inner_splits,
            lgbm_jobs=min(args.lgbm_jobs * 2, 6),
            skip_existing=skip_existing,
        )

    if "stats" in selected:
        compute_phase4_summaries(repo_root, results_dir)


if __name__ == "__main__":
    main()
