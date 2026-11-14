"""Unit tests for Nadeau-Bengio t-test, Wilcoxon, Holm-Bonferroni, decision rules, and bootstrap."""

from __future__ import annotations

import numpy as np
import pytest

from src.stats.tests import (
    classify_preregistered_outcome,
    holm_bonferroni,
    nadeau_bengio_test,
    stratified_bootstrap_ci,
    wilcoxon_signed_rank,
)


def test_nadeau_bengio_hand_checked() -> None:
    a = np.array([0.90, 0.91, 0.89, 0.92, 0.90])
    b = np.array([0.85, 0.86, 0.84, 0.87, 0.85])
    # Constant +0.05 difference -> sd = 0, ci = [0.05, 0.05], p = 0
    res_const = nadeau_bengio_test(a, b, [80] * 5, [20] * 5)
    assert res_const.mean_delta == pytest.approx(0.05)
    assert res_const.nb_se == pytest.approx(0.0)
    assert res_const.p_value == 0.0

    # Varying positive deltas -> NB SE > naive SE because rho = 0.25 > 0
    a2 = np.array([0.90, 0.93, 0.88, 0.91, 0.92])
    b2 = np.array([0.85, 0.86, 0.84, 0.87, 0.85])
    res_var = nadeau_bengio_test(a2, b2, [80] * 5, [20] * 5)
    deltas = a2 - b2
    expected_se = np.sqrt((1.0 / 5.0 + 0.25) * np.var(deltas, ddof=1))
    assert res_var.rho == pytest.approx(0.25)
    assert res_var.nb_se == pytest.approx(expected_se)
    assert res_var.ci_low < res_var.mean_delta < res_var.ci_high


def test_holm_bonferroni_monotonic_and_bounded() -> None:
    raw_p = [0.01, 0.04, 0.03, 0.20]
    adj = holm_bonferroni(raw_p)
    # Sorted order: 0.01 (*4=0.04), 0.03 (*3=0.09), 0.04 (*2=0.08 -> clamped up to 0.09), 0.20 (*1=0.20)
    assert adj == pytest.approx([0.04, 0.09, 0.09, 0.20])

    # Exact zero delta guard in Wilcoxon
    stat, p = wilcoxon_signed_rank([0.8, 0.8, 0.8], [0.8, 0.8, 0.8])
    assert stat == 0.0
    assert p == 1.0


def test_preregistered_decision_rules() -> None:
    v1, _ = classify_preregistered_outcome(0.025, 0.005, 0.045, 0.01)
    assert v1 == "Confirmed Improvement"

    # Below MDE=0.02 even if CI > 0 and p < 0.05 -> Inconclusive
    v2, _ = classify_preregistered_outcome(0.012, 0.003, 0.021, 0.01)
    assert v2 == "Inconclusive"

    # CI contains 0 -> No Significant Difference
    v3, _ = classify_preregistered_outcome(0.022, -0.004, 0.048, 0.03)
    assert v3 == "No Significant Difference"

    # Meets MDE and CI > 0, but p_holm >= 0.05 -> Inconclusive
    v4, _ = classify_preregistered_outcome(0.025, 0.002, 0.048, 0.08)
    assert v4 == "Inconclusive"


def test_stratified_bootstrap_ci_preserves_bounds() -> None:
    y = np.array([1] * 20 + [0] * 80)
    rng = np.random.default_rng(0)
    scores = np.where(y == 1, rng.uniform(0.55, 0.99, size=100), rng.uniform(0.01, 0.45, size=100))
    res = stratified_bootstrap_ci(y, scores, threshold=0.5, n_resamples=100, seed=42)
    assert res["pr_auc"]["ci_low"] <= res["pr_auc"]["point"] <= res["pr_auc"]["ci_high"]
    assert res["f1"]["point"] == pytest.approx(1.0)
