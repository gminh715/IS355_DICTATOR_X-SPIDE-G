"""Unit tests for clone clustering and leakage-free grouped splitting."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.data.bytecode import strip_cbor_metadata
from src.data.clones import cluster_clones
from src.data.splits import generate_grouped_cv_splits, generate_random_cv_splits


def test_clone_clustering_exact_near_and_missing() -> None:
    # Build a long base opcode sequence (~40 instructions) and a 1-instruction variant
    base = bytes.fromhex("5f3415600a5760016002016003026004036005046006055b00" * 2)
    near_variant = base[:-1] + bytes.fromhex("fd")  # last STOP -> REVERT (very high 5-gram Jaccard)
    unrelated = bytes.fromhex("333230315455f1f3ff" * 4)

    s1 = strip_cbor_metadata(base)
    s2 = strip_cbor_metadata(base)
    s3 = strip_cbor_metadata(near_variant)
    s4 = strip_cbor_metadata(unrelated)

    res = cluster_clones(
        [s1.code_hash, s2.code_hash, s3.code_hash, s4.code_hash, None],
        [s1.stripped_bytes, s2.stripped_bytes, s3.stripped_bytes, s4.stripped_bytes, b""],
    )
    assert res.group_exact[0] == res.group_exact[1]
    assert res.group_exact[0] != res.group_exact[2]
    assert res.group_near[0] == res.group_near[1] == res.group_near[2]
    assert res.group_near[3] != res.group_near[0]
    assert res.group_near[4].startswith("missing_")


def test_grouped_splits_have_zero_group_overlap(tmp_path: Path) -> None:
    rows = []
    # Create 10 near-groups (5 Ponzi groups, 5 non-Ponzi groups), 3 clones each
    for g in range(10):
        label = 1 if g < 5 else 0
        for m in range(3):
            idx = len(rows)
            rows.append(
                {
                    "sample_id": f"s_{idx:03d}",
                    "address": f"0x{idx:040x}",
                    "label": label,
                    "group_near": f"near_{g:05d}",
                }
            )
    df = pd.DataFrame(rows)
    files = generate_grouped_cv_splits(
        df,
        group_col="group_near",
        split_prefix="test_group_near",
        out_dir=tmp_path,
        n_splits=5,
        seeds=(42, 43),
    )
    assert len(files) == 10
    id_to_group = dict(zip(df["sample_id"], df["group_near"]))
    for fp in files:
        data = json.loads(fp.read_text(encoding="utf-8"))
        tr_groups = {id_to_group[s] for s in data["train_sample_ids"]}
        te_groups = {id_to_group[s] for s in data["test_sample_ids"]}
        assert tr_groups.isdisjoint(te_groups)


def test_random_cv_splits_stratified_and_disjoint(tmp_path: Path) -> None:
    rows = [
        {
            "sample_id": f"s_{i:03d}",
            "address": f"0x{i:040x}",
            "label": 1 if i < 10 else 0,
        }
        for i in range(50)
    ]
    df = pd.DataFrame(rows)
    files = generate_random_cv_splits(
        df,
        split_prefix="test_random",
        out_dir=tmp_path,
        n_splits=5,
        seeds=(42, 43),
    )
    assert len(files) == 10
    for fp in files:
        data = json.loads(fp.read_text(encoding="utf-8"))
        assert data["group_col"] is None
        tr_ids = set(data["train_sample_ids"])
        te_ids = set(data["test_sample_ids"])
        assert tr_ids.isdisjoint(te_ids)
        assert len(tr_ids) + len(te_ids) == 50
        assert data["test_pos"] == 2
        assert data["train_pos"] == 8
