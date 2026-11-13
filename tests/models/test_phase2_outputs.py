"""Integration verification tests for persisted Phase 2 outputs and model card."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from eth_utils import keccak

from src.models.data_prep import load_contracts_dataset, load_split_indices, prepare_xspide_99_features

REPO_ROOT = Path(__file__).resolve().parents[2]

REQUIRED_CV_COLUMNS = [
    "experiment",
    "seed",
    "fold",
    "PR-AUC",
    "F1",
    "P",
    "R",
    "ROC-AUC",
    "Recall@P>=0.9",
    "p90_fallback",
    "Accuracy",
    "threshold",
    "train_time",
    "n_features",
    "tp",
    "fp",
    "tn",
    "fn",
    "inner_cv_pr_auc",
    "best_params_json",
]


def test_e0_reproduction_csv() -> None:
    e0_path = REPO_ROOT / "results" / "E0_reproduction.csv"
    assert e0_path.exists()
    df = pd.read_csv(e0_path)
    run_ids = set(df["run_id"])
    for expected in (
        "published_xspide_paper",
        "E0_1009_47feats_unbal",
        "E0_2710_43feats",
        "E0_random5fold_47feats_unbal_mean",
        "E0_random5fold_99feats_gridbest_mean",
    ):
        assert expected in run_ids

    row_1009 = df.loc[df["run_id"] == "E0_1009_47feats_unbal"].iloc[0]
    assert int(row_1009["n_features"]) == 47
    assert abs(float(row_1009["delta_ROC-AUC"])) < 0.01


def test_e1_and_e2_fold_results_complete_and_consistent() -> None:
    expected_pairs = {(s, f) for s in (42, 43, 44, 45, 46) for f in range(5)}

    e1 = pd.read_csv(REPO_ROOT / "results" / "E1_folds.csv")
    e1_full = pd.read_csv(REPO_ROOT / "results" / "E1_full_folds.csv")
    e2 = pd.read_csv(REPO_ROOT / "results" / "E2_folds.csv")

    for name, df in (("E1", e1), ("E1-full", e1_full), ("E2", e2)):
        assert list(df.columns) == REQUIRED_CV_COLUMNS
        assert len(df) == 25, f"{name} expected 25 folds"
        pairs = set(zip(df["seed"].astype(int), df["fold"].astype(int)))
        assert pairs == expected_pairs
        numeric_cols = [
            "PR-AUC",
            "F1",
            "P",
            "R",
            "ROC-AUC",
            "Recall@P>=0.9",
            "Accuracy",
            "threshold",
            "train_time",
            "n_features",
            "tp",
            "fp",
            "tn",
            "fn",
            "inner_cv_pr_auc",
        ]
        assert not df[numeric_cols].isna().any().any()
        assert ((df["PR-AUC"] >= 0.0) & (df["PR-AUC"] <= 1.0)).all()
        assert ((df["tp"] + df["fn"]) == 176).all()

    assert (e1["n_features"] == 99).all()
    assert ((e2["n_features"] >= 24) & (e2["n_features"] <= 99)).all()
    assert np.allclose(e1["PR-AUC"].to_numpy(), e1_full["PR-AUC"].to_numpy(), atol=1e-12)


def test_baseline_model_artifact_and_hashes() -> None:
    model_dir = REPO_ROOT / "models" / "baseline_v1"
    model_path = model_dir / "model.joblib"
    lgb_path = model_dir / "model_lgb.txt"
    schema_path = model_dir / "feature_schema.json"
    card_path = model_dir / "model_card.json"

    for path in (model_path, lgb_path, schema_path, card_path):
        assert path.exists(), f"Missing {path}"

    schema_bytes = schema_path.read_bytes()
    model_bytes = model_path.read_bytes()
    schema = json.loads(schema_bytes.decode("utf-8"))
    card = json.loads(card_path.read_text(encoding="utf-8"))

    assert schema["n_features"] == 99
    assert len(schema["feature_order"]) == 99

    expected_schema_hash = "0x" + keccak(schema_bytes).hex()
    expected_version_hash = "0x" + keccak(model_bytes + schema_bytes).hex()
    expected_sha256 = hashlib.sha256(model_bytes).hexdigest()

    assert card["features"]["feature_schema_hash"] == expected_schema_hash
    assert card["artifacts"]["model_version_hash"] == expected_version_hash
    assert card["artifacts"]["model_sha256"] == expected_sha256

    e1 = pd.read_csv(REPO_ROOT / "results" / "E1_folds.csv")
    fold0 = e1[(e1["seed"] == 42) & (e1["fold"] == 0)].iloc[0]
    assert abs(float(card["demo_fold_metrics"]["pr_auc"]) - float(fold0["PR-AUC"])) < 1e-12

    pipe = joblib.load(model_path)
    df_code = load_contracts_dataset(REPO_ROOT, subset="S_code")
    X = prepare_xspide_99_features(df_code, normalize_opcodes=True)[schema["feature_order"]]
    _, te_idx, _ = load_split_indices(df_code, REPO_ROOT / "splits" / card["dataset"]["demo_split"])
    probs = pipe.predict_proba(X.iloc[te_idx[:5]])[:, 1]
    assert probs.shape == (5,)
    assert np.all((probs >= 0.0) & (probs <= 1.0))


def test_rq1_report_exists_and_matches_card() -> None:
    report_path = REPO_ROOT / "reports" / "rq1_reproduction.md"
    assert report_path.exists()
    text = report_path.read_text(encoding="utf-8")
    card = json.loads((REPO_ROOT / "models" / "baseline_v1" / "model_card.json").read_text(encoding="utf-8"))
    assert "E0_1009_47feats_unbal" in text
    assert "group_near" in text
    assert "E2" in text
    assert card["artifacts"]["model_version_hash"] in text
