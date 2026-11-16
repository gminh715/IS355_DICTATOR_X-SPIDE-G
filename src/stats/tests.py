"""Statistical testing utilities aligned with docs/preregistration.md."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
from scipy import stats

from src.models.metrics import evaluate_predictions


@dataclass(frozen=True)
class NadeauBengioResult:
    """Output of a Nadeau-Bengio corrected resampled paired t-test."""

    n_folds: int
    mean_delta: float
    sd_delta: float
    nb_se: float
    rho: float
    t_stat: float
    p_value: float
    ci_low: float
    ci_high: float


def load_fold_sizes(
    splits_dir: Path,
    *,
    split_prefix: str = "S_code_group_near",
    seeds: Sequence[int] = (42, 43, 44, 45, 46),
    n_splits: int = 5,
) -> dict[tuple[int, int], tuple[int, int]]:
    """Load ``(n_train, n_test)`` per ``(seed, fold)`` from frozen split JSONs."""
    sizes: dict[tuple[int, int], tuple[int, int]] = {}
    for seed in seeds:
        for fold in range(n_splits):
            fp = splits_dir / f"{split_prefix}_seed{seed}_fold{fold}.json"
            payload = json.loads(fp.read_text(encoding="utf-8"))
            sizes[(int(seed), int(fold))] = (int(payload["n_train"]), int(payload["n_test"]))
    return sizes


def nadeau_bengio_test(
    scores_a: Sequence[float] | np.ndarray,
    scores_b: Sequence[float] | np.ndarray,
    n_train: Sequence[int] | np.ndarray | int,
    n_test: Sequence[int] | np.ndarray | int,
    *,
    alpha: float = 0.05,
) -> NadeauBengioResult:
    """Compute Nadeau-Bengio (2003) corrected resampled paired t-test and CI."""
    a = np.asarray(scores_a, dtype=np.float64)
    b = np.asarray(scores_b, dtype=np.float64)
    if a.shape != b.shape or a.ndim != 1:
        raise ValueError(f"Expected matching 1D arrays, got {a.shape} and {b.shape}")
    j = len(a)
    if j < 2:
        raise ValueError(f"Need at least 2 folds for paired test, got {j}")

    deltas = a - b
    mean_delta = float(np.mean(deltas))
    sd_delta = float(np.std(deltas, ddof=1))
    var_delta = float(np.var(deltas, ddof=1))

    n_tr = np.asarray(n_train, dtype=np.float64)
    n_te = np.asarray(n_test, dtype=np.float64)
    if np.any(n_tr <= 0.0):
        raise ValueError("n_train must be strictly positive")
    rho = float(np.mean(n_te / n_tr))

    nb_var = (1.0 / float(j) + rho) * var_delta
    nb_se = float(math.sqrt(max(nb_var, 0.0)))
    t_crit = float(stats.t.ppf(1.0 - alpha / 2.0, df=j - 1))

    ci_low = mean_delta - t_crit * nb_se
    ci_high = mean_delta + t_crit * nb_se

    if nb_se == 0.0:
        if mean_delta == 0.0:
            t_stat = 0.0
            p_val = 1.0
        else:
            t_stat = math.copysign(float("inf"), mean_delta)
            p_val = 0.0
    else:
        t_stat = mean_delta / nb_se
        p_val = float(2.0 * stats.t.sf(abs(t_stat), df=j - 1))

    return NadeauBengioResult(
        n_folds=j,
        mean_delta=mean_delta,
        sd_delta=sd_delta,
        nb_se=nb_se,
        rho=rho,
        t_stat=t_stat,
        p_value=p_val,
        ci_low=ci_low,
        ci_high=ci_high,
    )


def wilcoxon_signed_rank(
    scores_a: Sequence[float] | np.ndarray,
    scores_b: Sequence[float] | np.ndarray,
) -> tuple[float, float]:
    """Run paired two-sided Wilcoxon signed-rank test on fold deltas."""
    deltas = np.asarray(scores_a, dtype=np.float64) - np.asarray(scores_b, dtype=np.float64)
    if np.allclose(deltas, 0.0, rtol=0.0, atol=1e-15):
        return 0.0, 1.0
    res = stats.wilcoxon(deltas, zero_method="wilcox", alternative="two-sided")
    return float(res.statistic), float(res.pvalue)


def holm_bonferroni(p_values: Sequence[float]) -> list[float]:
    """Apply Holm step-down adjustment across a family of p-values."""
    m = len(p_values)
    if m == 0:
        return []
    arr = np.asarray(p_values, dtype=np.float64)
    order = np.argsort(arr, kind="mergesort")
    adj_sorted = np.empty(m, dtype=np.float64)
    running_max = 0.0
    for rank, idx in enumerate(order):
        scaled = min(1.0, (m - rank) * float(arr[idx]))
        running_max = max(running_max, scaled)
        adj_sorted[rank] = running_max

    adjusted = np.empty(m, dtype=np.float64)
    adjusted[order] = adj_sorted
    return [float(x) for x in adjusted]


def classify_preregistered_outcome(
    mean_delta: float,
    ci_low: float,
    ci_high: float,
    p_holm: float,
    *,
    mde: float = 0.02,
    alpha: float = 0.05,
) -> tuple[str, str]:
    """Classify comparison strictly per docs/preregistration.md Section 4.3."""
    if mean_delta >= mde and ci_low > 0.0 and p_holm < alpha:
        return "Confirmed Improvement", f"mean_delta >= {mde:.2f}, CI_low > 0, p_Holm < {alpha:.2f}"
    if ci_low <= 0.0 <= ci_high:
        return "No Significant Difference", "95% Nadeau-Bengio CI contains 0"
    if ci_high < 0.0:
        return "Inconclusive", "95% NB CI strictly < 0 (degradation relative to baseline)"
    if mean_delta < mde:
        return "Inconclusive", f"CI_low > 0 but mean_delta ({mean_delta:+.4f}) < MDE ({mde:.2f})"
    return "Inconclusive", f"p_Holm ({p_holm:.4f}) >= {alpha:.2f} despite CI_low > 0"


def run_pairwise_suite(
    fold_tables: dict[str, pd.DataFrame],
    comparisons: Sequence[tuple[str, str, str]],
    fold_sizes: dict[tuple[int, int], tuple[int, int]],
    *,
    metric: str = "PR-AUC",
    apply_holm: bool = True,
    mde: float = 0.02,
    alpha: float = 0.05,
) -> pd.DataFrame:
    """Evaluate a family of paired comparisons `(group, model_a, model_b)` across 25 folds."""
    raw_rows: list[dict[str, Any]] = []
    p_nb_list: list[float] = []
    p_wilcoxon_list: list[float] = []

    for family_group, model_a, model_b in comparisons:
        df_a = fold_tables[model_a].sort_values(["seed", "fold"]).reset_index(drop=True)
        df_b = fold_tables[model_b].sort_values(["seed", "fold"]).reset_index(drop=True)

        keys_a = list(zip(df_a["seed"].astype(int), df_a["fold"].astype(int)))
        keys_b = list(zip(df_b["seed"].astype(int), df_b["fold"].astype(int)))
        if keys_a != keys_b:
            raise ValueError(f"Mismatched (seed, fold) keys between {model_a} and {model_b}")

        n_tr = [fold_sizes[k][0] for k in keys_a]
        n_te = [fold_sizes[k][1] for k in keys_a]

        scores_a = df_a[metric].to_numpy(dtype=np.float64)
        scores_b = df_b[metric].to_numpy(dtype=np.float64)
        nb = nadeau_bengio_test(scores_a, scores_b, n_tr, n_te, alpha=alpha)
        w_stat, p_wilc = wilcoxon_signed_rank(scores_a, scores_b)
        p_nb_list.append(nb.p_value)
        p_wilcoxon_list.append(p_wilc)

        raw_rows.append(
            {
                "family": family_group,
                "comparison": f"{model_a} vs {model_b}",
                "model_a": model_a,
                "model_b": model_b,
                "metric": metric,
                "n_folds": nb.n_folds,
                "mean_a": float(np.mean(scores_a)),
                "mean_b": float(np.mean(scores_b)),
                "mean_delta": nb.mean_delta,
                "sd_delta": nb.sd_delta,
                "nb_se": nb.nb_se,
                "rho": nb.rho,
                "ci95_low": nb.ci_low,
                "ci95_high": nb.ci_high,
                "nb_t_stat": nb.t_stat,
                "nb_p_value": nb.p_value,
                "wilcoxon_stat": w_stat,
                "wilcoxon_p_value": p_wilc,
            }
        )

    p_holm_nb_list = holm_bonferroni(p_nb_list) if apply_holm else [float("nan")] * len(raw_rows)
    p_holm_wilc_list = holm_bonferroni(p_wilcoxon_list) if apply_holm else [float("nan")] * len(raw_rows)
    for row, p_holm_nb, p_holm_wilc in zip(raw_rows, p_holm_nb_list, p_holm_wilc_list):
        row["nb_p_holm"] = p_holm_nb
        row["wilcoxon_p_holm"] = p_holm_wilc
        row["p_holm"] = p_holm_nb
        if apply_holm:
            verdict, note = classify_preregistered_outcome(
                row["mean_delta"],
                row["ci95_low"],
                row["ci95_high"],
                p_holm_nb,
                mde=mde,
                alpha=alpha,
            )
        else:
            verdict = "Descriptive Only"
            note = "Auxiliary comparison outside pre-registered 8-test Holm family"
        row["conclusion"] = verdict
        row["decision_note"] = note

    return pd.DataFrame(raw_rows)


def stratified_bootstrap_ci(
    y_true: Sequence[int] | np.ndarray,
    y_score: Sequence[float] | np.ndarray,
    *,
    threshold: float,
    n_resamples: int = 1000,
    seed: int = 42,
    alpha: float = 0.05,
) -> dict[str, dict[str, float]]:
    """Compute point estimates and stratified percentile bootstrap CIs."""
    y_t = np.asarray(y_true, dtype=int)
    y_s = np.asarray(y_score, dtype=np.float64)

    point = evaluate_predictions(y_t, y_s, threshold=threshold)
    pos_idx = np.flatnonzero(y_t == 1)
    neg_idx = np.flatnonzero(y_t == 0)
    if len(pos_idx) == 0 or len(neg_idx) == 0:
        raise ValueError("Both classes must be present for stratified bootstrap")

    rng = np.random.default_rng(seed)
    metric_keys = ("pr_auc", "roc_auc", "f1", "precision", "recall", "accuracy")
    samples: dict[str, list[float]] = {k: [] for k in metric_keys}

    for _ in range(n_resamples):
        b_pos = rng.choice(pos_idx, size=len(pos_idx), replace=True)
        b_neg = rng.choice(neg_idx, size=len(neg_idx), replace=True)
        b_idx = np.concatenate([b_pos, b_neg])
        m = evaluate_predictions(y_t[b_idx], y_s[b_idx], threshold=threshold)
        for k in metric_keys:
            samples[k].append(float(m[k]))

    low_q = 100.0 * (alpha / 2.0)
    high_q = 100.0 * (1.0 - alpha / 2.0)
    summary: dict[str, dict[str, float]] = {}
    for k in metric_keys:
        arr = np.asarray(samples[k], dtype=np.float64)
        summary[k] = {
            "point": float(point[k]),
            "ci_low": float(np.percentile(arr, low_q)),
            "ci_high": float(np.percentile(arr, high_q)),
            "boot_std": float(np.std(arr, ddof=1)),
        }
    return summary
