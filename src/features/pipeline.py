"""End-to-end Phase 3 opcode feature extraction pipeline and cost benchmarking."""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import platform
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.data.bytecode import parse_hex_bytecode, strip_cbor_metadata
from src.data.parquet_io import write_parquet
from src.features.bigram import extract_bigram_row
from src.features.disasm import disassemble
from src.features.gsem import GSEM_FEATURE_NAMES, extract_gsem_features
from src.features.gstat import GSTAT_FEATURE_NAMES, extract_gstat_features
from src.models.data_prep import load_contracts_dataset

LOGGER = logging.getLogger(__name__)


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def get_hardware_specs() -> tuple[str, float]:
    """Return ``(cpu_description, total_ram_gb)`` without external subprocesses."""
    cpu_name = platform.processor() or "unknown"
    if platform.system() == "Windows":
        try:
            import winreg

            key_path = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                val, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                if isinstance(val, str) and val.strip():
                    cpu_name = val.strip()
        except OSError:
            pass

        try:
            stat = _MemoryStatusEx()
            stat.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                ram_gb = round(stat.ullTotalPhys / (1024**3), 2)
            else:
                ram_gb = 0.0
        except OSError:
            ram_gb = 0.0
    else:
        ram_gb = 0.0

    threads = os.cpu_count() or 0
    return f"{cpu_name} ({threads} logical threads)", ram_gb


@dataclass(frozen=True)
class PipelineSummary:
    """Structured summary of the Phase 3 extraction run."""

    n_contracts: int
    n_errors: int
    error_rate_pct: float
    bigram_path: Path | None
    gstat_path: Path | None
    gsem_path: Path | None
    cost_csv_path: Path | None
    cost_df: pd.DataFrame
    diagnostics: dict[str, int | float]


def _zero_bigram_row() -> dict[str, int | str]:
    return {
        "bigram_total_norm": 0,
        "bigram_unique_norm": 0,
        "bigram_freq_norm_json": "{}",
        "bigram_total_raw": 0,
        "bigram_unique_raw": 0,
        "bigram_freq_raw_json": "{}",
    }


def _zero_gstat_row() -> dict[str, float]:
    return {name: 0.0 for name in GSTAT_FEATURE_NAMES}


def _zero_gsem_row() -> dict[str, float]:
    return {name: 0.0 for name in GSEM_FEATURE_NAMES}


def _format_timing_row(
    stage: str,
    times_ms: list[float],
    *,
    n_errors: int,
    error_causes: Counter[str],
    cpu_info: str,
    ram_gb: float,
    notes: str = "",
) -> dict[str, Any]:
    arr = np.asarray(times_ms, dtype=np.float64)
    n = len(arr)
    causes_str = "; ".join(f"{k}:{v}" for k, v in sorted(error_causes.items())) if error_causes else "none"
    return {
        "stage": stage,
        "n_contracts": n,
        "n_errors": n_errors,
        "error_rate_pct": round((100.0 * n_errors / n) if n > 0 else 0.0, 4),
        "error_causes": causes_str,
        "median_ms": round(float(np.median(arr)) if n > 0 else 0.0, 4),
        "mean_ms": round(float(np.mean(arr)) if n > 0 else 0.0, 4),
        "p95_ms": round(float(np.percentile(arr, 95)) if n > 0 else 0.0, 4),
        "max_ms": round(float(np.max(arr)) if n > 0 else 0.0, 4),
        "total_s": round(float(np.sum(arr) / 1000.0) if n > 0 else 0.0, 4),
        "cpu_info": cpu_info,
        "ram_gb": ram_gb,
        "python_version": platform.python_version(),
        "notes": notes,
    }


def run_feature_extraction_pipeline(
    repo_root: Path,
    *,
    limit: int | None = None,
    write_outputs: bool = True,
) -> PipelineSummary:
    """Run F-BIGRAM, F-GSTAT, and F-GSEM extraction across ``S_code`` contracts."""
    df = load_contracts_dataset(repo_root, subset="S_code")
    if limit is not None:
        df = df.iloc[:limit].copy()

    n_contracts = len(df)
    bigram_rows: list[dict[str, Any]] = []
    gstat_rows: list[dict[str, Any]] = []
    gsem_rows: list[dict[str, Any]] = []

    stage_times: dict[str, list[float]] = {
        "disasm": [],
        "bigram": [],
        "gstat": [],
        "gsem": [],
        "end_to_end": [],
    }
    stage_errors: dict[str, int] = {k: 0 for k in stage_times}
    stage_causes: dict[str, Counter[str]] = {k: Counter() for k in stage_times}

    n_with_truncated_push = 0
    n_with_invalid_opcode = 0
    n_high_unresolved_jump = 0

    for row in df.itertuples(index=False):
        sample_id = str(row.sample_id)
        address = str(row.address)
        bytecode_hex = row.bytecode_hex

        t_start_all = time.perf_counter_ns()
        disasm_res = None

        t0 = time.perf_counter_ns()
        try:
            raw_bytes = parse_hex_bytecode(bytecode_hex)
            stripped = strip_cbor_metadata(raw_bytes)
            disasm_res = disassemble(stripped.stripped_bytes, log_truncated=False)
            if not disasm_res.instructions:
                raise ValueError("empty_disassembly")
        except Exception as exc:  # noqa: BLE001
            cause = type(exc).__name__ if str(exc) != "empty_disassembly" else "empty_disassembly"
            stage_errors["disasm"] += 1
            stage_causes["disasm"][cause] += 1
            disasm_res = None
        t1 = time.perf_counter_ns()
        disasm_ms = (t1 - t0) / 1e6

        if disasm_res is not None:
            if disasm_res.truncated_push_count > 0:
                n_with_truncated_push += 1
            if disasm_res.invalid_opcode_count > 0:
                n_with_invalid_opcode += 1

        # F-BIGRAM
        t_b0 = time.perf_counter_ns()
        if disasm_res is None:
            b_feat = _zero_bigram_row()
            stage_errors["bigram"] += 1
            stage_causes["bigram"]["upstream_disasm_failed"] += 1
        else:
            try:
                b_feat = extract_bigram_row(disasm_res)
            except Exception as exc:  # noqa: BLE001
                b_feat = _zero_bigram_row()
                stage_errors["bigram"] += 1
                stage_causes["bigram"][type(exc).__name__] += 1
        t_b1 = time.perf_counter_ns()
        bigram_ms = (t_b1 - t_b0) / 1e6

        # F-GSTAT
        t_s0 = time.perf_counter_ns()
        if disasm_res is None:
            s_feat = _zero_gstat_row()
            stage_errors["gstat"] += 1
            stage_causes["gstat"]["upstream_disasm_failed"] += 1
        else:
            try:
                s_feat = extract_gstat_features(disasm_res, normalize=True)
            except Exception as exc:  # noqa: BLE001
                s_feat = _zero_gstat_row()
                stage_errors["gstat"] += 1
                stage_causes["gstat"][type(exc).__name__] += 1
        t_s1 = time.perf_counter_ns()
        gstat_ms = (t_s1 - t_s0) / 1e6

        # F-GSEM
        t_g0 = time.perf_counter_ns()
        if disasm_res is None:
            g_feat = _zero_gsem_row()
            stage_errors["gsem"] += 1
            stage_causes["gsem"]["upstream_disasm_failed"] += 1
        else:
            try:
                g_feat = extract_gsem_features(disasm_res, normalize=True)
                if g_feat["unresolved_jump_ratio"] > 0.50:
                    n_high_unresolved_jump += 1
            except Exception as exc:  # noqa: BLE001
                g_feat = _zero_gsem_row()
                stage_errors["gsem"] += 1
                stage_causes["gsem"][type(exc).__name__] += 1
        t_g1 = time.perf_counter_ns()
        gsem_ms = (t_g1 - t_g0) / 1e6

        t_end_all = time.perf_counter_ns()
        end_to_end_ms = (t_end_all - t_start_all) / 1e6

        if disasm_res is None:
            stage_errors["end_to_end"] += 1
            stage_causes["end_to_end"]["disasm_failed"] += 1

        stage_times["disasm"].append(disasm_ms)
        stage_times["bigram"].append(bigram_ms)
        stage_times["gstat"].append(gstat_ms)
        stage_times["gsem"].append(gsem_ms)
        stage_times["end_to_end"].append(end_to_end_ms)

        key_cols = {"sample_id": sample_id, "address": address}
        bigram_rows.append({**key_cols, **b_feat})
        gstat_rows.append({**key_cols, **s_feat})
        gsem_rows.append({**key_cols, **g_feat})

    bigram_df = pd.DataFrame(bigram_rows)
    gstat_df = pd.DataFrame(gstat_rows)
    gsem_df = pd.DataFrame(gsem_rows)

    cpu_info, ram_gb = get_hardware_specs()
    high_unres_pct = (100.0 * n_high_unresolved_jump / n_contracts) if n_contracts > 0 else 0.0
    notes_by_stage = {
        "disasm": f"truncated_push_contracts={n_with_truncated_push};invalid_opcode_contracts={n_with_invalid_opcode}",
        "bigram": "stores sparse norm & raw relative frequencies; top-k=200 fit in-fold",
        "gstat": "16 transition-graph descriptors including /L normalized variants",
        "gsem": f"15 CFG descriptors; unresolved_jump_ratio>0.50: {n_high_unresolved_jump}/{n_contracts} ({high_unres_pct:.2f}%)",
        "end_to_end": "full S_code runtime extraction cost per contract",
    }

    cost_rows = [
        _format_timing_row(
            stage,
            stage_times[stage],
            n_errors=stage_errors[stage],
            error_causes=stage_causes[stage],
            cpu_info=cpu_info,
            ram_gb=ram_gb,
            notes=notes_by_stage[stage],
        )
        for stage in ("disasm", "bigram", "gstat", "gsem", "end_to_end")
    ]
    cost_df = pd.DataFrame(cost_rows)

    bigram_path: Path | None = None
    gstat_path: Path | None = None
    gsem_path: Path | None = None
    cost_csv_path: Path | None = None

    if write_outputs:
        processed_dir = repo_root / "data" / "processed"
        results_dir = repo_root / "results"
        results_dir.mkdir(parents=True, exist_ok=True)

        bigram_path = processed_dir / "features_bigram.parquet"
        gstat_path = processed_dir / "features_gstat.parquet"
        gsem_path = processed_dir / "features_gsem.parquet"
        cost_csv_path = results_dir / "feature_extraction_cost.csv"

        write_parquet(bigram_df, bigram_path)
        write_parquet(gstat_df, gstat_path)
        write_parquet(gsem_df, gsem_path)
        cost_df.to_csv(cost_csv_path, index=False)

    total_errors = stage_errors["end_to_end"]
    error_rate_pct = (100.0 * total_errors / n_contracts) if n_contracts > 0 else 0.0
    diagnostics: dict[str, int | float] = {
        "n_contracts": n_contracts,
        "n_with_truncated_push": n_with_truncated_push,
        "n_with_invalid_opcode": n_with_invalid_opcode,
        "n_high_unresolved_jump": n_high_unresolved_jump,
        "high_unresolved_jump_pct": round(high_unres_pct, 2),
        "unresolved_jump_median": round(float(gsem_df["unresolved_jump_ratio"].median()), 4)
        if n_contracts > 0
        else 0.0,
        "unresolved_jump_p95": round(float(gsem_df["unresolved_jump_ratio"].quantile(0.95)), 4)
        if n_contracts > 0
        else 0.0,
    }
    return PipelineSummary(
        n_contracts=n_contracts,
        n_errors=total_errors,
        error_rate_pct=error_rate_pct,
        bigram_path=bigram_path,
        gstat_path=gstat_path,
        gsem_path=gsem_path,
        cost_csv_path=cost_csv_path,
        cost_df=cost_df,
        diagnostics=diagnostics,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Extract Phase 3 opcode & graph features.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root directory.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional contract limit for smoke runs (default: all S_code).",
    )
    args = parser.parse_args()

    summary = run_feature_extraction_pipeline(args.repo_root, limit=args.limit, write_outputs=True)
    print(f"Processed contracts: {summary.n_contracts}, errors: {summary.n_errors} ({summary.error_rate_pct:.4f}%)")
    print("Diagnostics:", summary.diagnostics)
    print(summary.cost_df.to_string(index=False))


if __name__ == "__main__":
    main()
