"""End-to-end Phase 1 pipeline: manifest, schema audit, bytecode recovery, CBOR strip, clones, splits."""

from __future__ import annotations

import argparse
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.audit import audit_clone_groups, check_cross_dataset_overlap, compute_ks_bias_table, render_data_audit_md
from src.data.bytecode import parse_hex_bytecode, strip_cbor_metadata
from src.data.clones import cluster_clones
from src.data.download import run_download, verify_manifest
from src.data.parquet_io import write_parquet
from src.data.recovery import batch_eth_get_code, has_bigquery_credentials
from src.data.splits import (
    DEFAULT_SEEDS,
    generate_e0_random_splits,
    generate_grouped_cv_splits,
    generate_random_cv_splits,
    generate_temporal_holdout,
)

ADDR_RE = re.compile(r"^0x[0-9a-f]{40}$")


def _load_xspide_deployed_bytecodes(xspide_ds_dir: Path) -> dict[str, str]:
    depl_map: dict[str, str] = {}
    with zipfile.ZipFile(xspide_ds_dir / "depl_bytecode_list.zip") as zf:
        with zf.open("depl_bytecode_list.csv") as f:
            df_bc = pd.read_csv(f, dtype=str).fillna("")
    for addr, bc in zip(df_bc["address"], df_bc["depl_bytecode"]):
        norm = str(addr).strip().lower()
        val = str(bc).strip()
        if val and val.lower() not in {"0x", "nan", "none", "null"}:
            depl_map[norm] = val if val.startswith("0x") else "0x" + val
    return depl_map


def _summarize_csv_schema(path: Path, *, sep: str = ",", addr_col: str = "address", target_col: str = "target") -> dict[str, Any]:
    df = pd.read_csv(path, sep=sep)
    addrs = df[addr_col].astype(str).str.strip().str.lower()
    valid_addrs = addrs[addrs.str.match(ADDR_RE, na=False)]
    conflicts = 0
    ponzi = 0
    non_ponzi = 0
    if target_col in df.columns:
        lbl = pd.to_numeric(df[target_col], errors="coerce")
        ponzi = int((lbl == 1).sum())
        non_ponzi = int((lbl == 0).sum())
        conflicts = int((pd.DataFrame({"a": addrs, "y": lbl}).groupby("a")["y"].nunique() > 1).sum())
    return {
        "file": path.name,
        "rows": int(len(df)),
        "cols": int(df.shape[1]),
        "ponzi": ponzi,
        "non_ponzi": non_ponzi,
        "unique_valid_addrs": int(valid_addrs.nunique()),
        "label_conflicts": conflicts,
    }


def _load_or_update_rpc_cache(cache_path: Path, addresses: list[str], *, skip_rpc: bool) -> dict[str, str]:
    cache: dict[str, str] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    if skip_rpc:
        return cache
    todo = [a for a in addresses if a not in cache]
    if todo:
        fetched = batch_eth_get_code(todo)
        cache.update(fetched)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, sort_keys=True), encoding="utf-8")
    return cache


def run_phase1(repo_root: Path, *, skip_rpc: bool = False) -> None:
    """Execute Phase 1 end-to-end and write manifest, Parquet, splits, and data_audit.md."""
    raw_dir = repo_root / "data" / "raw"
    xspide_dir = raw_dir / "x-spide"
    xspide_ds_dir = xspide_dir / "dataset"

    if not (repo_root / "data" / "manifest.json").exists():
        run_download(repo_root, force=False)
    verify_manifest(repo_root)

    import subprocess

    xspide_commit = subprocess.run(
        ["git", "-C", str(xspide_dir), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    # 1.2 Schema & label audit
    schema_summary = [
        _summarize_csv_schema(xspide_ds_dir / "DS_deployed_bytecode.csv"),
        _summarize_csv_schema(xspide_ds_dir / "DS_full_bytecode.csv"),
        _summarize_csv_schema(xspide_ds_dir / "bytecode_opcode_8k.csv", sep=";"),
        _summarize_csv_schema(xspide_ds_dir / "address_without_byt.csv", target_col="__none__"),
    ]

    raw_df = pd.read_csv(xspide_ds_dir / "DS_deployed_bytecode.csv")
    addresses = raw_df["address"].astype(str).str.strip().str.lower()
    if not addresses.str.match(ADDR_RE).all():
        raise ValueError("Invalid Ethereum address format in DS_deployed_bytecode.csv")
    if addresses.duplicated().any():
        raise ValueError("Duplicate addresses found in DS_deployed_bytecode.csv")

    labels = pd.to_numeric(raw_df["target"], errors="raise").astype("int64")
    feature_df = raw_df.drop(columns=["address", "target"])
    sample_ids = pd.Series(
        [f"xspide_{i:05d}" for i in range(len(raw_df))],
        index=raw_df.index,
        name="sample_id",
    )
    df = pd.concat(
        [sample_ids, addresses.rename("address"), labels.rename("label"), feature_df],
        axis=1,
    )

    # 1.3 Priority bytecode recovery
    depl_map = _load_xspide_deployed_bytecodes(xspide_ds_dir)
    missing_from_repo = [a for a in df["address"] if a not in depl_map]

    rpc_cache_path = raw_dir / "rpc_cache.json"
    df_8k = pd.read_csv(xspide_ds_dir / "bytecode_opcode_8k.csv", sep=";")
    df_8k["address"] = df_8k["address"].astype(str).str.strip().str.lower()
    df_8k["label"] = pd.to_numeric(df_8k["target"], errors="raise").astype("int64")

    # Also gather Unica disjoint addresses + Ponzi sample + 8k missing for RPC check
    ponzi_addrs = df.loc[df["label"] == 1, "address"].tolist()
    nonponzi_sample = df.loc[df["label"] == 0, "address"].sample(n=len(ponzi_addrs), random_state=42).tolist()
    missing_8k_addrs = [a for a in df_8k["address"] if a not in depl_map]

    unica_addrs: list[str] = []
    with (raw_dir / "unica" / "ponzi-addresses.csv").open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            part = line.split(",")[0].strip().lower()
            if part.startswith("0x") and len(part) == 42:
                unica_addrs.append(part)
    x_addr_set = set(df["address"])
    unica_disjoint = [a for a in sorted(set(unica_addrs)) if a not in x_addr_set]

    rpc_targets = sorted(set(missing_from_repo + ponzi_addrs + nonponzi_sample + missing_8k_addrs + unica_disjoint))
    rpc_cache = _load_or_update_rpc_cache(rpc_cache_path, rpc_targets, skip_rpc=skip_rpc)

    bq_available = has_bigquery_credentials()
    bytecode_hex_list: list[str] = []
    bytecode_source_list: list[str] = []
    for addr in df["address"]:
        if addr in depl_map:
            bytecode_hex_list.append(depl_map[addr])
            bytecode_source_list.append("xspide_repo")
        elif addr in rpc_cache and rpc_cache[addr] not in ("", "0x", "rpc_error"):
            bytecode_hex_list.append(rpc_cache[addr])
            bytecode_source_list.append("rpc_latest")
        else:
            bytecode_hex_list.append("")
            bytecode_source_list.append("missing")

    # 1.4 CBOR metadata stripping & keccak256
    stripped_hex_list: list[str] = []
    stripped_bytes_list: list[bytes] = []
    meta_status_list: list[str] = []
    code_hash_list: list[str | None] = []
    for hx in bytecode_hex_list:
        raw = parse_hex_bytecode(hx)
        st = strip_cbor_metadata(raw)
        stripped_bytes_list.append(st.stripped_bytes)
        stripped_hex_list.append("0x" + st.stripped_bytes.hex() if st.stripped_bytes else "")
        meta_status_list.append(st.metadata_stripped)
        code_hash_list.append(st.code_hash)

    # 1.5 Two-level clone clustering
    clones = cluster_clones(code_hash_list, stripped_bytes_list)

    extra_df = pd.DataFrame(
        {
            "bytecode_hex": pd.Series(bytecode_hex_list, dtype="object"),
            "stripped_bytecode_hex": pd.Series(stripped_hex_list, dtype="object"),
            "bytecode_source": pd.Series(bytecode_source_list, dtype="object"),
            "metadata_stripped": pd.Series(meta_status_list, dtype="object"),
            "code_hash": pd.Series(code_hash_list, dtype="object"),
            "group_exact": pd.Series(clones.group_exact, dtype="object"),
            "group_near": pd.Series(clones.group_near, dtype="object"),
            "block_number": pd.Series([pd.NA] * len(df), dtype="Int64"),
        },
        index=df.index,
    )
    df = pd.concat([df, extra_df], axis=1)

    # Save contracts.parquet (S_full / S_code)
    processed_path = repo_root / "data" / "processed" / "contracts.parquet"
    write_parquet(df, processed_path, index=False)

    # S_code subset
    df_code = df[df["bytecode_source"] != "missing"].copy().reset_index(drop=True)
    s_code_ponzi = int((df_code["label"] == 1).sum())
    r1_triggered = s_code_ponzi < 400

    # 1.7 Frozen splits
    splits_dir = repo_root / "splits"
    near_files = generate_grouped_cv_splits(
        df_code,
        group_col="group_near",
        split_prefix="S_code_group_near",
        out_dir=splits_dir,
        n_splits=5,
        seeds=DEFAULT_SEEDS,
    )
    exact_files = generate_grouped_cv_splits(
        df_code,
        group_col="group_exact",
        split_prefix="S_code_group_exact",
        out_dir=splits_dir,
        n_splits=5,
        seeds=DEFAULT_SEEDS,
    )
    random_5x5_files = generate_random_cv_splits(
        df_code,
        split_prefix="S_code_random",
        out_dir=splits_dir,
        n_splits=5,
        seeds=DEFAULT_SEEDS,
    )
    e0_files = generate_e0_random_splits(df, out_dir=splits_dir, n_splits=5, seed=42)
    temporal_fp = generate_temporal_holdout(df_code, out_dir=splits_dir)

    splits_summary = [
        f"`S_code_group_near_seed{{42..46}}_fold{{0..4}}.json`: **{len(near_files)}** files (`StratifiedGroupKFold(5)` × 5 repeats on `group_near`, `|S_code|={len(df_code)}`).",
        f"`S_code_group_exact_seed{{42..46}}_fold{{0..4}}.json`: **{len(exact_files)}** files (for sensitivity analysis `S1`).",
        f"`S_code_random_seed{{42..46}}_fold{{0..4}}.json`: **{len(random_5x5_files)}** files (`StratifiedKFold(5)` × 5 repeats for controlled causal baseline `E1_S0_random_5x5`).",
        f"`S_full_E0_random_seed42_fold{{0..4}}.json`: **{len(e0_files)}** files (for `E0` paper-style random baseline reference only, `|S_full|={len(df)}`).",
        (
            f"`{temporal_fp.name}` generated for `S3`."
            if temporal_fp
            else f"`S_code_temporal_holdout.json` (`S3`): **not generated** — `block_number` is absent in X-SPIDE CSV/archives and Google BigQuery credentials (`bq_available={bq_available}`) are not configured locally."
        ),
    ]

    # Audit aggregations
    coverage_table = []
    for lbl, name in ((1, "Ponzi (`1`)"), (0, "non-Ponzi (`0`)")):
        sub_full = df[df["label"] == lbl]
        sub_code = df_code[df_code["label"] == lbl]
        coverage_table.append(
            {
                "class_name": name,
                "s_full": int(len(sub_full)),
                "s_code": int(len(sub_code)),
                "coverage_pct": (len(sub_code) / len(sub_full) * 100.0) if len(sub_full) else 0.0,
                "xspide_repo": int((sub_full["bytecode_source"] == "xspide_repo").sum()),
                "rpc_latest": int((sub_full["bytecode_source"] == "rpc_latest").sum()),
                "missing": int((sub_full["bytecode_source"] == "missing").sum()),
            }
        )

    live_rpc_audit = None
    if rpc_cache:
        p_checked = [a for a in ponzi_addrs if a in rpc_cache]
        np_checked = [a for a in nonponzi_sample if a in rpc_cache]
        p_0x = sum(1 for a in p_checked if rpc_cache[a] == "0x")
        np_0x = sum(1 for a in np_checked if rpc_cache[a] == "0x")
        m8k_df = df_8k[df_8k["address"].isin(missing_8k_addrs)]
        m8k_alive = sum(
            1
            for a in missing_8k_addrs
            if rpc_cache.get(a, "0x") not in ("0x", "rpc_error", "")
        )
        live_rpc_audit = {
            "ponzi_checked": len(p_checked),
            "ponzi_alive": len(p_checked) - p_0x,
            "ponzi_0x_pct": (p_0x / len(p_checked) * 100.0) if p_checked else 0.0,
            "nonponzi_checked": len(np_checked),
            "nonponzi_alive": len(np_checked) - np_0x,
            "nonponzi_0x_pct": (np_0x / len(np_checked) * 100.0) if np_checked else 0.0,
            "missing_8k_total": int(len(m8k_df)),
            "missing_8k_ponzi": int((m8k_df["label"] == 1).sum()),
            "missing_8k_nonponzi": int((m8k_df["label"] == 0).sum()),
            "missing_8k_rpc_alive": m8k_alive,
        }

    kept_mask = df_8k["address"].isin(x_addr_set)
    ks_8k = compute_ks_bias_table(df_8k, kept_mask, ~kept_mask)

    metadata_counts: dict[str, dict[str, int]] = {}
    for status in ("true", "false", "none"):
        sub = df[df["metadata_stripped"] == status]
        metadata_counts[status] = {
            "total": int(len(sub)),
            "ponzi": int((sub["label"] == 1).sum()),
            "non_ponzi": int((sub["label"] == 0).sum()),
        }

    clones_exact = audit_clone_groups(df_code, "group_exact")
    clones_near = audit_clone_groups(df_code, "group_near")
    overlap = check_cross_dataset_overlap(df_code, raw_dir, rpc_code_map=rpc_cache)

    audit_payload = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "xspide_commit": xspide_commit,
        "s_code_ponzi": s_code_ponzi,
        "r1_triggered": r1_triggered,
        "schema_summary": schema_summary,
        "coverage_table": coverage_table,
        "live_rpc_audit": live_rpc_audit,
        "ks_8k_kept_vs_dropped": ks_8k,
        "metadata_counts": metadata_counts,
        "clones_exact": clones_exact,
        "clones_near": clones_near,
        "overlap": overlap,
        "splits_summary": splits_summary,
    }

    report_path = repo_root / "reports" / "data_audit.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_data_audit_md(audit_payload, df_code), encoding="utf-8")

    # Save machine-readable audit JSON alongside Markdown for traceability
    (repo_root / "reports" / "data_audit_summary.json").write_text(
        json.dumps(audit_payload, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Phase 1 pipeline completed: |S_code|={len(df_code)} (Ponzi={s_code_ponzi}), report={report_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Phase 1 data audit, clone grouping, and splitting.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--skip-rpc", action="store_true", help="Use cached RPC results only.")
    args = parser.parse_args()
    run_phase1(args.root, skip_rpc=args.skip_rpc)


if __name__ == "__main__":
    main()
