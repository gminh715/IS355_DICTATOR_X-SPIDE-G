"""Integration tests verifying Phase 3 outputs on S_code (7,446 contracts)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.data.parquet_io import read_parquet
from src.features.bigram import BigramTopKVectorizer
from src.features.gsem import GSEM_FEATURE_NAMES
from src.features.gstat import GSTAT_FEATURE_NAMES
from src.models.data_prep import load_contracts_dataset

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_phase3_parquet_outputs_complete_and_valid() -> None:
    contracts_df = load_contracts_dataset(REPO_ROOT, subset="S_code")
    n_expected = len(contracts_df)
    assert n_expected == 7446

    bigram_path = REPO_ROOT / "data" / "processed" / "features_bigram.parquet"
    gstat_path = REPO_ROOT / "data" / "processed" / "features_gstat.parquet"
    gsem_path = REPO_ROOT / "data" / "processed" / "features_gsem.parquet"

    for path in (bigram_path, gstat_path, gsem_path):
        assert path.exists(), f"Missing Phase 3 output: {path}"

    bigram_df = read_parquet(bigram_path)
    gstat_df = read_parquet(gstat_path)
    gsem_df = read_parquet(gsem_path)

    for df in (bigram_df, gstat_df, gsem_df):
        assert len(df) == n_expected
        assert list(df["sample_id"]) == list(contracts_df["sample_id"])
        assert list(df["address"]) == list(contracts_df["address"])

    expected_bigram_cols = {
        "sample_id",
        "address",
        "bigram_total_norm",
        "bigram_unique_norm",
        "bigram_freq_norm_json",
        "bigram_total_raw",
        "bigram_unique_raw",
        "bigram_freq_raw_json",
    }
    assert set(bigram_df.columns) == expected_bigram_cols
    assert (bigram_df["bigram_total_norm"] > 0).all()

    assert set(gstat_df.columns) == {"sample_id", "address", *GSTAT_FEATURE_NAMES}
    gstat_vals = gstat_df[list(GSTAT_FEATURE_NAMES)].to_numpy(dtype=np.float64)
    assert np.isfinite(gstat_vals).all()
    assert ((gstat_df["gstat_density"] >= 0.0) & (gstat_df["gstat_density"] <= 1.0)).all()
    assert (
        (gstat_df["gstat_self_loop_ratio"] >= 0.0) & (gstat_df["gstat_self_loop_ratio"] <= 1.0)
    ).all()

    assert set(gsem_df.columns) == {"sample_id", "address", *GSEM_FEATURE_NAMES}
    gsem_vals = gsem_df[list(GSEM_FEATURE_NAMES)].to_numpy(dtype=np.float64)
    assert np.isfinite(gsem_vals).all()
    assert (gsem_df["cyclomatic"] >= 1.0).all(), "Multi-component McCabe cyclomatic complexity must be >= 1.0"
    assert (
        (gsem_df["unresolved_jump_ratio"] >= 0.0) & (gsem_df["unresolved_jump_ratio"] <= 1.0)
    ).all()
    assert ((gsem_df["call_block_ratio"] >= 0.0) & (gsem_df["call_block_ratio"] <= 1.0)).all()
    for bin_col in (
        "has_loop_with_call",
        "path_callvalue_to_call",
        "has_selfdestruct",
        "selfdestruct_reachable",
    ):
        assert set(gsem_df[bin_col].unique()).issubset({0.0, 1.0})


def test_feature_extraction_cost_report_valid() -> None:
    cost_path = REPO_ROOT / "results" / "feature_extraction_cost.csv"
    assert cost_path.exists(), f"Missing extraction cost CSV: {cost_path}"
    cost_df = pd.read_csv(cost_path)
    assert list(cost_df["stage"]) == ["disasm", "bigram", "gstat", "gsem", "end_to_end"]
    assert (cost_df["n_contracts"] == 7446).all()
    assert (cost_df["error_rate_pct"] < 1.0).all()
    assert (cost_df["median_ms"] > 0.0).all()
    assert (cost_df["p95_ms"] >= cost_df["median_ms"]).all()
    assert (cost_df["ram_gb"] > 0.0).all()


def test_bigram_vectorizer_on_fold0_split() -> None:
    split_path = REPO_ROOT / "splits" / "S_code_group_exact_seed42_fold0.json"
    split = json.loads(split_path.read_text(encoding="utf-8"))

    bigram_df = read_parquet(REPO_ROOT / "data" / "processed" / "features_bigram.parquet").set_index(
        "sample_id"
    )
    train_ids = split["train_sample_ids"]
    test_ids = split["test_sample_ids"]

    train_df = bigram_df.loc[train_ids]
    test_df = bigram_df.loc[test_ids]

    vec_norm = BigramTopKVectorizer(top_k=200, column="bigram_freq_norm_json")
    X_train = vec_norm.fit_transform(train_df)
    X_test = vec_norm.transform(test_df)

    assert X_train.shape == (len(train_ids), 200)
    assert X_test.shape == (len(test_ids), 200)
    assert np.isfinite(X_train).all()
    assert np.isfinite(X_test).all()
    assert (X_train.sum(axis=1) <= 1.0 + 1e-9).all()
    assert (X_test.sum(axis=1) <= 1.0 + 1e-9).all()

    # Sensitivity S4: raw opcodes variant must also fit top-200 cleanly on fold 0
    vec_raw = BigramTopKVectorizer(top_k=200, column="bigram_freq_raw_json")
    X_raw_train = vec_raw.fit_transform(train_df)
    assert X_raw_train.shape == (len(train_ids), 200)
