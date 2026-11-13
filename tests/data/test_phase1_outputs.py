"""Integration verification tests for persisted Phase 1 artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from src.data.download import verify_manifest
from src.data.parquet_io import read_parquet
from src.data.splits import DEFAULT_SEEDS

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_manifest_and_contracts_parquet_schema() -> None:
    assert (REPO_ROOT / "data" / "manifest.json").exists()
    verify_manifest(REPO_ROOT)

    parquet_path = REPO_ROOT / "data" / "processed" / "contracts.parquet"
    assert parquet_path.exists()
    df = read_parquet(parquet_path)

    required = {
        "sample_id",
        "address",
        "label",
        "bytecode_hex",
        "stripped_bytecode_hex",
        "bytecode_source",
        "metadata_stripped",
        "code_hash",
        "group_exact",
        "group_near",
        "block_number",
    }
    assert required.issubset(df.columns)
    feature_cols = [c for c in df.columns if c not in required]
    assert len(feature_cols) == 99

    assert len(df) == 7446
    assert df["sample_id"].is_unique
    assert df["address"].is_unique
    assert set(df["label"].unique()) == {0, 1}


def test_frozen_splits_partition_and_zero_leakage() -> None:
    df = read_parquet(REPO_ROOT / "data" / "processed" / "contracts.parquet")
    df_code = df[df["bytecode_source"] != "missing"].copy()

    full_ids = set(df["sample_id"].astype(str))
    code_ids = set(df_code["sample_id"].astype(str))
    near_map = dict(zip(df_code["sample_id"].astype(str), df_code["group_near"].astype(str)))
    exact_map = dict(zip(df_code["sample_id"].astype(str), df_code["group_exact"].astype(str)))
    code_pos = int((df_code["label"] == 1).sum())
    full_pos = int((df["label"] == 1).sum())

    splits_dir = REPO_ROOT / "splits"
    for prefix, group_map in (
        ("S_code_group_near", near_map),
        ("S_code_group_exact", exact_map),
    ):
        for seed in DEFAULT_SEEDS:
            for fold in range(5):
                payload = json.loads(
                    (splits_dir / f"{prefix}_seed{seed}_fold{fold}.json").read_text(encoding="utf-8")
                )
                tr_ids = set(payload["train_sample_ids"])
                te_ids = set(payload["test_sample_ids"])
                assert tr_ids.isdisjoint(te_ids)
                assert (tr_ids | te_ids) == code_ids
                assert payload["train_pos"] + payload["test_pos"] == code_pos

                tr_groups = {group_map[sid] for sid in tr_ids}
                te_groups = {group_map[sid] for sid in te_ids}
                assert tr_groups.isdisjoint(te_groups), f"Leakage in {prefix} seed={seed} fold={fold}"

    for fold in range(5):
        payload = json.loads(
            (splits_dir / f"S_full_E0_random_seed42_fold{fold}.json").read_text(encoding="utf-8")
        )
        tr_ids = set(payload["train_sample_ids"])
        te_ids = set(payload["test_sample_ids"])
        assert tr_ids.isdisjoint(te_ids)
        assert (tr_ids | te_ids) == full_ids
        assert payload["train_pos"] + payload["test_pos"] == full_pos


def test_data_audit_reports_exist_and_consistent() -> None:
    md_path = REPO_ROOT / "reports" / "data_audit.md"
    json_path = REPO_ROOT / "reports" / "data_audit_summary.json"
    assert md_path.exists() and md_path.stat().st_size > 500
    summary = json.loads(json_path.read_text(encoding="utf-8"))
    assert summary["s_code_ponzi"] >= 400
    assert summary["r1_triggered"] is False
    assert "unica" in summary["overlap"]
    assert "ponziguard" in summary["overlap"]
    assert "decision" in summary["overlap"]["ponziguard"]
