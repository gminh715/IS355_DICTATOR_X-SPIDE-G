"""Verification tests for Phase 4 outputs, statistical tests, figures, XAI, and report."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = REPO_ROOT / "results"
FIGURES_DIR = REPO_ROOT / "figures"
REPORTS_DIR = REPO_ROOT / "reports"

EXPECTED_MAIN_FEATURES: dict[str, int | None] = {
    "E1": 99,
    "E2": None,
    "E3": 16,
    "E3b": 200,
    "E3c": 15,
    "E4": 115,
    "E4b": 299,
    "E4c": 114,
    "E4d": 314,
}


def test_all_main_and_sensitivity_fold_csvs_present_with_25_folds() -> None:
    for exp_id, exp_nfeats in EXPECTED_MAIN_FEATURES.items():
        p = RESULTS_DIR / f"{exp_id}_folds.csv"
        assert p.exists(), f"Missing {p}"
        df = pd.read_csv(p)
        assert len(df) == 25, f"{exp_id} expected 25 rows, got {len(df)}"
        assert set(df["seed"].unique()) == {42, 43, 44, 45, 46}
        assert set(df["fold"].unique()) == {0, 1, 2, 3, 4}
        assert (df["PR-AUC"] > 0.0).all() and (df["PR-AUC"] <= 1.0).all()
        if exp_nfeats is not None:
            assert (df["n_features"] == exp_nfeats).all(), f"{exp_id} feature mismatch"

    sens_cfgs = (
        "E1_S1_group_exact",
        "E4c_S1_group_exact",
        "E1_S2_cbor_stripped",
        "E4c_S2_raw_cbor",
        "E4c_S2_cbor_stripped",
        "E4b_S4_raw_opcodes",
        "E4c_S4_raw_opcodes",
    )
    for cfg in sens_cfgs:
        p = RESULTS_DIR / f"{cfg}_folds.csv"
        assert p.exists(), f"Missing sensitivity file {p}"
        assert len(pd.read_csv(p)) == 25


def test_model_comparison_and_stat_tests_follow_preregistration() -> None:
    comp_p = RESULTS_DIR / "model_comparison.csv"
    stat_p = RESULTS_DIR / "stat_tests.csv"
    sens_p = RESULTS_DIR / "sensitivity_summary.csv"
    assert comp_p.exists() and stat_p.exists() and sens_p.exists()

    comp_df = pd.read_csv(comp_p)
    assert set(comp_df["experiment"]) == set(EXPECTED_MAIN_FEATURES.keys())

    stat_df = pd.read_csv(stat_p)
    prereg = stat_df[stat_df["test_suite"] == "preregistered_holm_8"]
    assert len(prereg) == 8
    expected_pairs = {
        "E4 vs E1",
        "E4b vs E1",
        "E4c vs E1",
        "E2 vs E1",
        "E4c vs E4b",
        "E4d vs E4b",
        "E3c vs E3b",
        "E3c vs E3",
    }
    assert set(prereg["comparison"]) == expected_pairs
    assert (prereg["p_holm"] >= prereg["wilcoxon_p_value"] - 1e-12).all()
    assert (prereg["p_holm"] <= 1.0 + 1e-12).all()
    assert set(prereg["conclusion"]).issubset(
        {"Confirmed Improvement", "No Significant Difference", "Inconclusive"}
    )

    sens_df = pd.read_csv(sens_p)
    assert "S3_temporal_holdout" in set(sens_df["study"])


def test_e6_sanity_check_exists_and_logs_risk_r6() -> None:
    p = RESULTS_DIR / "E6_sanity_check.csv"
    assert p.exists()
    df = pd.read_csv(p)
    assert len(df) == 6
    assert "R6" in str(df["risk_flag"].iloc[0])
    assert int(df["n_test_ponzi"].iloc[0]) == 10
    assert (df["ci95_low"] <= df["point"] + 1e-12).all()
    assert (df["point"] <= df["ci95_high"] + 1e-12).all()


def test_figures_error_analysis_and_rq2_report_exist() -> None:
    expected_figs = (
        "pr_curves.png",
        "delta_pr_auc_ci.png",
        "shap_beeswarm_E1.png",
        "shap_beeswarm_E4c.png",
        "shap_gsem_importance.png",
        "shap_waterfall_tp.png",
        "shap_waterfall_fp.png",
        "shap_waterfall_fn.png",
        "cfg_tp.png",
        "cfg_fp.png",
        "cfg_fn.png",
    )
    for fname in expected_figs:
        fp = FIGURES_DIR / fname
        assert fp.exists(), f"Missing figure {fp}"
        assert fp.stat().st_size > 10_000, f"Figure too small: {fp}"

    err_p = RESULTS_DIR / "error_analysis_cases.csv"
    assert err_p.exists()
    err_df = pd.read_csv(err_p)
    assert int((err_df["error_type"] == "FP").sum()) >= 10
    assert int((err_df["error_type"] == "FN").sum()) >= 10

    report_p = REPORTS_DIR / "rq2_results.md"
    assert report_p.exists()
    txt = report_p.read_text(encoding="utf-8")
    assert "R6" in txt and "S3" in txt and "has_loop_with_call" in txt
