"""Tests for Parquet I/O engine fallback and schema preservation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.parquet_io import read_parquet, select_parquet_engine, write_parquet


def test_parquet_roundtrip_preserves_nullable_int_and_strings(tmp_path: Path) -> None:
    df = pd.DataFrame(
        {
            "sample_id": ["xspide_00000", "xspide_00001"],
            "address": ["0x" + "1" * 40, "0x" + "2" * 40],
            "label": pd.Series([0, 1], dtype="int64"),
            "code_hash": [None, "0x" + "a" * 64],
            "block_number": pd.Series([pd.NA, 123456], dtype="Int64"),
        }
    )
    out_path = tmp_path / "sample.parquet"
    used_engine = write_parquet(df, out_path, index=False)
    assert used_engine == select_parquet_engine()
    assert out_path.exists()

    loaded = read_parquet(out_path)
    assert list(loaded.columns) == list(df.columns)
    assert len(loaded) == 2
    assert loaded["label"].tolist() == [0, 1]
    assert pd.isna(loaded["block_number"].iloc[0])
    assert int(loaded["block_number"].iloc[1]) == 123456
