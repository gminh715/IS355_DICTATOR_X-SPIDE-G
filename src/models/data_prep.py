"""Dataset loading, X-SPIDE 99-feature preparation, and frozen split index resolution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from src.data.parquet_io import read_parquet

METADATA_COLUMNS = frozenset(
    {
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
)

# Published IEEE Access (2025) X-SPIDE 47-feature LightGBM metrics [1].
PAPER_PUBLISHED_E0_METRICS: dict[str, float] = {
    "accuracy": 0.969,
    "precision": 0.870,
    "recall": 0.864,
    "f1": 0.867,
    "roc_auc": 0.977,
}

# Exact 47-feature subset from X-SPIDE official repo: code/1009_best_features_SHAP.ipynb
PAPER_47_FEATURES: tuple[str, ...] = (
    "lifetime",
    "tx_in",
    "investment_to_contract/tx_in",
    "mean_v1",
    "sdev_v1",
    "sdev_v2",
    "paid_one",
    "sdev_tx_in",
    "PUSH",
    "DUP",
    "JUMPDEST",
    "STOP",
    "MSTORE",
    "JUMPI",
    "REVERT",
    "CALLVALUE",
    "CODECOPY",
    "RETURN",
    "LOG",
    "SHA3",
    "MSTORE8",
    "SWAP",
    "POP",
    "ADD",
    "MLOAD",
    "AND",
    "SUB",
    "CALLDATALOAD",
    "EXP",
    "MUL",
    "SLOAD",
    "EQ",
    "DIV",
    "CALLER",
    "CALLDATACOPY",
    "SSTORE",
    "NOT",
    "CALL",
    "LT",
    "ADDRESS",
    "GASLIMIT",
    "GAS",
    "ORIGIN",
    "BALANCE",
    "COINBASE",
    "MULMOD",
    "SGT",
)

# Exact 43-feature subset from X-SPIDE official repo: code/2710_best_features_SHAP.ipynb
PAPER_43_FEATURES: tuple[str, ...] = (
    "tx_in",
    "investment_to_contract/tx_in",
    "mean_v1",
    "sdev_v1",
    "paid_one",
    "PUSH",
    "DUP",
    "JUMPDEST",
    "STOP",
    "MSTORE",
    "JUMPI",
    "REVERT",
    "CALLVALUE",
    "CODECOPY",
    "RETURN",
    "LOG",
    "SHA3",
    "MSTORE8",
    "SWAP",
    "POP",
    "ADD",
    "MLOAD",
    "AND",
    "SUB",
    "CALLDATALOAD",
    "EXP",
    "MUL",
    "SLOAD",
    "EQ",
    "DIV",
    "CALLER",
    "CALLDATACOPY",
    "SSTORE",
    "NOT",
    "CALL",
    "LT",
    "ADDRESS",
    "GASLIMIT",
    "GAS",
    "ORIGIN",
    "BALANCE",
    "MULMOD",
    "SGT",
)


def load_contracts_dataset(
    repo_root: Path,
    *,
    subset: Literal["S_full", "S_code"] = "S_code",
) -> pd.DataFrame:
    """Load Phase 1 contracts.parquet and optionally filter to valid bytecode rows (S_code)."""
    parquet_path = repo_root / "data" / "processed" / "contracts.parquet"
    df = read_parquet(parquet_path)
    if subset == "S_code":
        df = df[df["bytecode_source"] != "missing"].copy()
    df = df.reset_index(drop=True)
    return df


def get_xspide_feature_columns(df: pd.DataFrame) -> tuple[list[str], list[str], list[str]]:
    """Return (all_99_features, account_23_features, opcode_76_features) in schema order."""
    feat_cols = [c for c in df.columns if c not in METADATA_COLUMNS]
    if len(feat_cols) != 99:
        raise ValueError(f"Expected 99 X-SPIDE features, found {len(feat_cols)}")
    account_cols = feat_cols[:23]
    opcode_cols = feat_cols[23:]
    return feat_cols, account_cols, opcode_cols


def prepare_xspide_99_features(
    df: pd.DataFrame,
    *,
    normalize_opcodes: bool = True,
) -> pd.DataFrame:
    """Build the X-SPIDE 99-feature matrix matching official weighted-opcode preprocessing.

    Each row's 76 opcode counts are divided by their row sum (`all_opcode`) with 0/0 filled to 0.0,
    which is strictly a per-row deterministic transform (zero cross-sample leakage).
    """
    feat_cols, _, opcode_cols = get_xspide_feature_columns(df)
    X = df[feat_cols].astype("float64").fillna(0.0).copy()
    if normalize_opcodes:
        op_sum = X[opcode_cols].sum(axis=1).replace(0.0, np.nan)
        X[opcode_cols] = X[opcode_cols].div(op_sum, axis=0).fillna(0.0)
    return X


def load_split_indices(df: pd.DataFrame, split_path: Path) -> tuple[np.ndarray, np.ndarray, dict]:
    """Resolve frozen split JSON sample_ids to positional integer indices on `df`."""
    payload = json.loads(split_path.read_text(encoding="utf-8"))
    id_to_idx = {str(sid): idx for idx, sid in enumerate(df["sample_id"].astype(str))}

    train_ids = payload["train_sample_ids"]
    test_ids = payload["test_sample_ids"]
    if set(train_ids) & set(test_ids):
        raise AssertionError(f"Overlap between train and test IDs in {split_path.name}")

    tr_idx = np.array([id_to_idx[str(sid)] for sid in train_ids], dtype=np.int64)
    te_idx = np.array([id_to_idx[str(sid)] for sid in test_ids], dtype=np.int64)
    return tr_idx, te_idx, payload
