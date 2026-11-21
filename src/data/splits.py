"""Frozen leakage-controlled split generation (group_near, group_exact, temporal, E0)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold

DEFAULT_SEEDS = (42, 43, 44, 45, 46)


def generate_grouped_cv_splits(
    df: pd.DataFrame,
    *,
    group_col: str,
    split_prefix: str,
    out_dir: Path,
    n_splits: int = 5,
    seeds: tuple[int, ...] = DEFAULT_SEEDS,
) -> list[Path]:
    """Create deterministic repeated StratifiedGroupKFold JSON split files."""
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []

    y = df["label"].to_numpy(dtype=int)
    groups = df[group_col].astype(str).to_numpy()
    sample_ids = df["sample_id"].astype(str).to_numpy()
    addresses = df["address"].astype(str).to_numpy()

    for seed in seeds:
        cv = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
        for fold_idx, (tr_idx, te_idx) in enumerate(cv.split(np.zeros(len(df)), y, groups)):
            tr_groups = set(groups[tr_idx])
            te_groups = set(groups[te_idx])
            overlap = tr_groups & te_groups
            if overlap:
                raise AssertionError(
                    f"Group leakage in {split_prefix} seed={seed} fold={fold_idx}: {len(overlap)} groups"
                )

            payload: dict[str, Any] = {
                "split_name": f"{split_prefix}_seed{seed}_fold{fold_idx}",
                "group_col": group_col,
                "seed": seed,
                "fold": fold_idx,
                "n_splits": n_splits,
                "n_train": int(len(tr_idx)),
                "n_test": int(len(te_idx)),
                "train_pos": int(y[tr_idx].sum()),
                "test_pos": int(y[te_idx].sum()),
                "train_sample_ids": sample_ids[tr_idx].tolist(),
                "test_sample_ids": sample_ids[te_idx].tolist(),
                "train_addresses": addresses[tr_idx].tolist(),
                "test_addresses": addresses[te_idx].tolist(),
            }
            fp = out_dir / f"{split_prefix}_seed{seed}_fold{fold_idx}.json"
            fp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            saved.append(fp)
    return saved


def generate_temporal_holdout(
    df: pd.DataFrame,
    *,
    out_dir: Path,
    test_fraction: float = 0.20,
    split_name: str = "S_code_temporal_holdout",
) -> Path | None:
    """Create latest-20% deployment-block holdout when reliable block_number exists."""
    valid = df[df["block_number"].notna()].copy()
    if len(valid) < 100 or len(valid) < 0.5 * len(df):
        return None
    valid = valid.sort_values(["block_number", "sample_id"], kind="mergesort")
    cutoff_idx = int((1.0 - test_fraction) * len(valid))
    cutoff_block = int(valid.iloc[cutoff_idx]["block_number"])

    # Assign all contracts deployed at or after cutoff_block to test so identical blocks stay clean.
    train_df = valid[valid["block_number"] < cutoff_block]
    test_df = valid[valid["block_number"] >= cutoff_block]
    if train_df.empty or test_df.empty or test_df["label"].sum() == 0:
        return None

    payload = {
        "split_name": split_name,
        "cutoff_block": cutoff_block,
        "coverage_rows": int(len(valid)),
        "total_rows": int(len(df)),
        "n_train": int(len(train_df)),
        "n_test": int(len(test_df)),
        "train_pos": int(train_df["label"].sum()),
        "test_pos": int(test_df["label"].sum()),
        "train_sample_ids": train_df["sample_id"].astype(str).tolist(),
        "test_sample_ids": test_df["sample_id"].astype(str).tolist(),
        "train_addresses": train_df["address"].astype(str).tolist(),
        "test_addresses": test_df["address"].astype(str).tolist(),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    fp = out_dir / f"{split_name}.json"
    fp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return fp


def generate_random_cv_splits(
    df: pd.DataFrame,
    *,
    split_prefix: str = "S_code_random",
    out_dir: Path,
    n_splits: int = 5,
    seeds: tuple[int, ...] = DEFAULT_SEEDS,
) -> list[Path]:
    """Create deterministic repeated StratifiedKFold JSON split files (controlled random baseline)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []

    y = df["label"].to_numpy(dtype=int)
    sample_ids = df["sample_id"].astype(str).to_numpy()
    addresses = df["address"].astype(str).to_numpy()

    for seed in seeds:
        cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
        for fold_idx, (tr_idx, te_idx) in enumerate(cv.split(np.zeros(len(df)), y)):
            payload: dict[str, Any] = {
                "split_name": f"{split_prefix}_seed{seed}_fold{fold_idx}",
                "group_col": None,
                "seed": seed,
                "fold": fold_idx,
                "n_splits": n_splits,
                "n_train": int(len(tr_idx)),
                "n_test": int(len(te_idx)),
                "train_pos": int(y[tr_idx].sum()),
                "test_pos": int(y[te_idx].sum()),
                "train_sample_ids": sample_ids[tr_idx].tolist(),
                "test_sample_ids": sample_ids[te_idx].tolist(),
                "train_addresses": addresses[tr_idx].tolist(),
                "test_addresses": addresses[te_idx].tolist(),
            }
            fp = out_dir / f"{split_prefix}_seed{seed}_fold{fold_idx}.json"
            fp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            saved.append(fp)
    return saved


def generate_e0_random_splits(
    df_full: pd.DataFrame,
    *,
    out_dir: Path,
    n_splits: int = 5,
    seed: int = 42,
) -> list[Path]:
    """Random stratified split for E0 paper reproduction only (never used for E1–E4d)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    y = df_full["label"].to_numpy(dtype=int)
    sample_ids = df_full["sample_id"].astype(str).to_numpy()
    addresses = df_full["address"].astype(str).to_numpy()

    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    for fold_idx, (tr_idx, te_idx) in enumerate(cv.split(np.zeros(len(df_full)), y)):
        payload = {
            "split_name": f"S_full_E0_random_seed{seed}_fold{fold_idx}",
            "seed": seed,
            "fold": fold_idx,
            "n_train": int(len(tr_idx)),
            "n_test": int(len(te_idx)),
            "train_pos": int(y[tr_idx].sum()),
            "test_pos": int(y[te_idx].sum()),
            "train_sample_ids": sample_ids[tr_idx].tolist(),
            "test_sample_ids": sample_ids[te_idx].tolist(),
            "train_addresses": addresses[tr_idx].tolist(),
            "test_addresses": addresses[te_idx].tolist(),
        }
        fp = out_dir / f"S_full_E0_random_seed{seed}_fold{fold_idx}.json"
        fp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        saved.append(fp)
    return saved
