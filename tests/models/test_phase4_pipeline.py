"""Tests for Phase 4 feature assembly, pipeline pre-steps, S2/S4 builders, and E6 loader."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.models.data_prep import get_xspide_feature_columns, load_contracts_dataset, load_split_indices
from src.models.phase4_features import (
    TabularBigramAssembler,
    extract_bytecode_features_single_pass,
    load_e6_ponziguard_sanity_datasets,
    load_phase4_dataset,
)
from src.models.tuning import run_nested_cv_fold

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_tabular_bigram_assembler_zero_test_leakage() -> None:
    X_tr = pd.DataFrame(
        {
            "f1": [1.0, 2.0, 3.0],
            "bigram_freq_payload": [
                {"PUSH|JUMPI": 0.5, "ADD|STOP": 0.5},
                {"PUSH|JUMPI": 0.8},
                {"DUP|SWAP": 1.0},
            ],
        }
    )
    X_te = pd.DataFrame(
        {
            "f1": [4.0, 5.0],
            "bigram_freq_payload": [
                {"TEST_ONLY|TOKEN": 1.0, "PUSH|JUMPI": 0.25},
                {"TEST_ONLY|TOKEN": 1.0},
            ],
        }
    )

    asm = TabularBigramAssembler(tabular_cols=("f1",), bigram_column="bigram_freq_payload", top_k=2)
    out_tr = asm.fit_transform(X_tr)
    out_te = asm.transform(X_te)

    assert list(out_tr.columns) == list(out_te.columns)
    assert out_tr.shape == (3, 3)
    assert out_te.shape == (2, 3)
    assert all("TEST_ONLY|TOKEN" not in col for col in out_te.columns)
    assert out_te.loc[0, "bigram__PUSH|JUMPI"] == 0.25


def test_nested_cv_fold_with_pipeline_pre_steps_reports_exact_n_features() -> None:
    df_meta, X, pre_steps = load_phase4_dataset(REPO_ROOT, "E4d")
    split_path = REPO_ROOT / "splits" / "S_code_group_near_seed42_fold0.json"
    tr_idx, te_idx, _ = load_split_indices(df_meta, split_path)

    row, final_pipe = run_nested_cv_fold(
        X,
        df_meta["label"].to_numpy(dtype=int),
        df_meta["group_near"].astype(str).to_numpy(),
        tr_idx,
        te_idx,
        seed=42,
        fold=0,
        experiment_id="E4d_smoke",
        n_trials=2,
        n_inner_splits=2,
        n_jobs=3,
        use_rfe=False,
        pipeline_pre_steps=pre_steps,
    )

    assert row["n_features"] == 314
    assert final_pipe.named_steps["clf"].n_features_in_ == 314
    assert 0.5 <= row["PR-AUC"] <= 1.0


def test_phase4_feature_builders_no_nans_and_expected_shapes() -> None:
    expected_cached_cols = {
        "E3": 16,
        "E3b": 1,
        "E3c": 15,
        "E4": 115,
        "E4b": 100,
        "E4c": 114,
        "E4d": 115,
        "E4b_S4_raw_opcodes": 100,
    }
    for cfg, ncols in expected_cached_cols.items():
        df_meta, X, pre_steps = load_phase4_dataset(REPO_ROOT, cfg)
        assert len(df_meta) == 7446
        assert X.shape == (7446, ncols), f"{cfg} shape {X.shape}"
        num_cols = [c for c in X.columns if c != "bigram_freq_payload"]
        if num_cols:
            assert not X[num_cols].isna().any().any(), f"NaN in {cfg}"
        if cfg in ("E3b", "E4b", "E4d", "E4b_S4_raw_opcodes"):
            assert pre_steps is not None

    # Validate S2/S4 single-pass extractor directly on a representative subset.
    df_sub = load_contracts_dataset(REPO_ROOT, subset="S_code").head(25)
    _, _, op_76 = get_xspide_feature_columns(df_sub)
    bundle_norm = extract_bytecode_features_single_pass(
        df_sub["stripped_bytecode_hex"],
        op_76,
        compute_op76=True,
        compute_bigram=True,
        compute_gsem=True,
        normalize_opcodes=True,
    )
    assert bundle_norm["op76"].shape == (25, 76)
    assert bundle_norm["gsem"].shape == (25, 15)
    assert not bundle_norm["op76"].isna().any().any()
    assert not bundle_norm["gsem"].isna().any().any()

    bundle_raw = extract_bytecode_features_single_pass(
        df_sub["bytecode_hex"],
        op_76,
        compute_op76=False,
        compute_bigram=False,
        compute_gsem=True,
        normalize_opcodes=False,
    )
    assert bundle_raw["gsem"].shape == (25, 15)
    assert not bundle_raw["gsem"].isna().any().any()


def test_e6_ponziguard_sanity_loader_disjoint_and_consistent() -> None:
    df_train, X_train, df_pg, X_pg, pre_steps = load_e6_ponziguard_sanity_datasets(REPO_ROOT)
    assert len(df_train) == 7446
    assert list(X_train.columns) == list(X_pg.columns)
    assert int(df_pg["label"].sum()) == 10
    assert int((df_pg["label"] == 0).sum()) == 97
    assert not (set(df_pg["code_hash"].str.lower()) & set(df_train["code_hash"].dropna().str.lower()))
    assert pre_steps is not None
