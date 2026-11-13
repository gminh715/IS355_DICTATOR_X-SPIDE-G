"""Parquet I/O helpers with automatic fallback when pyarrow.parquet is blocked."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Literal

import pandas as pd

ParquetEngine = Literal["pyarrow", "fastparquet"]


def select_parquet_engine() -> ParquetEngine:
    """Return 'pyarrow' when usable, otherwise fall back to 'fastparquet'."""
    try:
        import pyarrow.parquet  # noqa: F401

        return "pyarrow"
    except (ImportError, OSError):
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*future\\.infer_string.*")
            import fastparquet  # noqa: F401

        return "fastparquet"


def write_parquet(df: pd.DataFrame, path: Path, *, index: bool = False) -> ParquetEngine:
    """Write a DataFrame to Parquet using the active engine and return its name."""
    engine = select_parquet_engine()
    path.parent.mkdir(parents=True, exist_ok=True)
    with warnings.catch_warnings():
        if engine == "fastparquet":
            warnings.filterwarnings("ignore", message=".*fastparquet.*")
            warnings.filterwarnings("ignore", message=".*future\\.infer_string.*")
        df.to_parquet(path, engine=engine, index=index)
    return engine


def read_parquet(path: Path) -> pd.DataFrame:
    """Read a Parquet file using the active engine."""
    engine = select_parquet_engine()
    with warnings.catch_warnings():
        if engine == "fastparquet":
            warnings.filterwarnings("ignore", message=".*fastparquet.*")
            warnings.filterwarnings("ignore", message=".*future\\.infer_string.*")
        return pd.read_parquet(path, engine=engine)
