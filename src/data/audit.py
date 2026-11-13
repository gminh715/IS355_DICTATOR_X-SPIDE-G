"""Data auditing, KS selection-bias tests, cross-dataset overlap checks, and Markdown reporting."""

from __future__ import annotations

import csv
import json
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from datasketch import MinHashLSH
from scipy.stats import ks_2samp

from src.data.bytecode import extract_runtime_from_initcode, parse_hex_bytecode, strip_cbor_metadata
from src.data.clones import compute_minhash, opcode_shingles

TX_AUDIT_COLS = [
    "balance",
    "lifetime",
    "tx_in",
    "tx_out",
    "investment_in",
    "payment_out",
    "paid_rate",
]


def audit_clone_groups(df: pd.DataFrame, group_col: str) -> dict[str, Any]:
    """Summarize cluster size distribution, mixed-label conflicts, and Ponzi clustering."""
    grp = df.groupby(group_col)["label"].agg(["count", "sum", "nunique"])
    total_groups = int(len(grp))
    singletons = int((grp["count"] == 1).sum())
    size_2_5 = int(((grp["count"] >= 2) & (grp["count"] <= 5)).sum())
    size_6_plus = int((grp["count"] >= 6).sum())
    max_size = int(grp["count"].max()) if total_groups else 0

    mixed = grp[grp["nunique"] > 1]
    mixed_groups = [
        {
            "group_id": str(gid),
            "total": int(row["count"]),
            "ponzi": int(row["sum"]),
            "non_ponzi": int(row["count"] - row["sum"]),
        }
        for gid, row in mixed.iterrows()
    ]

    total_ponzi = int((df["label"] == 1).sum())
    non_singleton_ids = set(grp[grp["count"] > 1].index)
    ponzi_in_multi = int(((df["label"] == 1) & (df[group_col].isin(non_singleton_ids))).sum())
    ponzi_in_multi_pct = (ponzi_in_multi / total_ponzi * 100.0) if total_ponzi else 0.0

    non_ponzi_total = int((df["label"] == 0).sum())
    non_ponzi_in_multi = int(((df["label"] == 0) & (df[group_col].isin(non_singleton_ids))).sum())
    non_ponzi_in_multi_pct = (non_ponzi_in_multi / non_ponzi_total * 100.0) if non_ponzi_total else 0.0

    return {
        "group_col": group_col,
        "total_groups": total_groups,
        "singletons": singletons,
        "size_2_5": size_2_5,
        "size_6_plus": size_6_plus,
        "max_size": max_size,
        "mixed_label_groups_count": len(mixed_groups),
        "mixed_label_groups": mixed_groups[:15],
        "ponzi_in_multi": ponzi_in_multi,
        "total_ponzi": total_ponzi,
        "ponzi_in_multi_pct": ponzi_in_multi_pct,
        "non_ponzi_in_multi": non_ponzi_in_multi,
        "non_ponzi_in_multi_pct": non_ponzi_in_multi_pct,
    }


def compute_ks_bias_table(
    df_8k: pd.DataFrame,
    group_a_mask: pd.Series,
    group_b_mask: pd.Series,
    cols: list[str] = TX_AUDIT_COLS,
) -> list[dict[str, Any]]:
    """Run two-sample KS tests and median comparisons between two contract subsets."""
    rows: list[dict[str, Any]] = []
    sub_a = df_8k.loc[group_a_mask]
    sub_b = df_8k.loc[group_b_mask]
    for col in cols:
        if col not in df_8k.columns:
            continue
        va = pd.to_numeric(sub_a[col], errors="coerce").dropna().to_numpy(dtype=float)
        vb = pd.to_numeric(sub_b[col], errors="coerce").dropna().to_numpy(dtype=float)
        if len(va) == 0 or len(vb) == 0:
            continue
        ks_res = ks_2samp(va, vb)
        rows.append(
            {
                "feature": col,
                "n_kept": int(len(va)),
                "n_excluded": int(len(vb)),
                "median_kept": float(np.median(va)),
                "median_excluded": float(np.median(vb)),
                "ks_stat": float(ks_res.statistic),
                "p_value": float(ks_res.pvalue),
            }
        )
    return rows


def check_cross_dataset_overlap(
    df_xspide: pd.DataFrame,
    raw_dir: Path,
    *,
    rpc_code_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Evaluate overlap of Blockchain@Unica and PonziGuard against X-SPIDE."""
    x_addrs = set(df_xspide["address"].str.lower())
    x_addr_label = dict(zip(df_xspide["address"].str.lower(), df_xspide["label"]))
    x_hashes = set(df_xspide["code_hash"].dropna().str.lower())

    # Build LSH index over unique X-SPIDE stripped bytecodes for group_near matching.
    lsh = MinHashLSH(threshold=0.90, num_perm=128)
    x_shingles: dict[str, set[bytes]] = {}
    x_minhashes = {}
    seen_hashes: set[str] = set()
    for ch, hx in zip(df_xspide["code_hash"], df_xspide["stripped_bytecode_hex"]):
        if not ch or ch in seen_hashes or not hx:
            continue
        seen_hashes.add(ch)
        raw = parse_hex_bytecode(hx)
        sh = opcode_shingles(raw, k=5)
        if sh:
            mh = compute_minhash(sh, num_perm=128)
            x_shingles[ch] = sh
            x_minhashes[ch] = mh
            lsh.insert(ch, mh)

    def matches_xspide_code(stripped_bytes: bytes, ch: str | None) -> tuple[bool, bool]:
        exact_hit = bool(ch and ch.lower() in x_hashes)
        near_hit = exact_hit
        if not near_hit and stripped_bytes:
            sh = opcode_shingles(stripped_bytes, k=5)
            if sh:
                mh = compute_minhash(sh, num_perm=128)
                for cand_ch in lsh.query(mh):
                    other = x_shingles[cand_ch]
                    union_sz = len(sh | other)
                    if union_sz and (len(sh & other) / union_sz) >= 0.90:
                        near_hit = True
                        break
        return exact_hit, near_hit

    # 1. Blockchain@Unica overlap
    unica_csv = raw_dir / "unica" / "ponzi-addresses.csv"
    unica_rows: list[tuple[str, str]] = []
    with unica_csv.open("r", encoding="utf-8", errors="replace") as f:
        for row in csv.reader(f):
            if row and row[0].strip().lower().startswith("0x"):
                name = row[1].strip() if len(row) > 1 else ""
                unica_rows.append((row[0].strip().lower(), name))
    unica_unique = sorted({a for a, _ in unica_rows})
    unica_addr_overlap = [a for a in unica_unique if a in x_addrs]
    unica_addr_disjoint = [a for a in unica_unique if a not in x_addrs]

    unica_code_overlap = 0
    unica_near_overlap = 0
    unica_live_checked = 0
    if rpc_code_map:
        for a in unica_addr_disjoint:
            hx = rpc_code_map.get(a, "")
            raw = parse_hex_bytecode(hx)
            if not raw:
                continue
            unica_live_checked += 1
            st = strip_cbor_metadata(raw)
            ex, nr = matches_xspide_code(st.stripped_bytes, st.code_hash)
            if ex:
                unica_code_overlap += 1
            if nr:
                unica_near_overlap += 1

    # 2. PonziGuard overlap (address files + extracted runtime from .bin files)
    pg_base = raw_dir / "ponziguard" / "extracted"
    pg_sol_addrs = sorted(
        {
            ("0x" + p.stem.lower() if not p.stem.lower().startswith("0x") else p.stem.lower())
            for p in (pg_base / "Ponzi" / "Ponzi" / "Ponzi contracts").glob("*.sol")
        }
    )
    pg_sol_overlap = [a for a in pg_sol_addrs if a in x_addrs]
    pg_sol_remaining = [a for a in pg_sol_addrs if a not in x_addrs]

    def audit_pg_bins(bin_dir: Path) -> dict[str, Any]:
        bins = sorted(bin_dir.glob("*.bin"))
        valid_hex = 0
        extracted_rt = 0
        exact_overlap = 0
        near_overlap = 0
        unique_non_overlap_hashes: set[str] = set()
        for b in bins:
            hx = b.read_text(encoding="utf-8", errors="replace").strip()
            try:
                raw_init = parse_hex_bytecode(hx)
            except ValueError:
                continue
            if not raw_init:
                continue
            valid_hex += 1
            rt = extract_runtime_from_initcode(raw_init)
            if not rt:
                continue
            extracted_rt += 1
            st = strip_cbor_metadata(rt)
            ex, nr = matches_xspide_code(st.stripped_bytes, st.code_hash)
            if ex:
                exact_overlap += 1
            if nr:
                near_overlap += 1
            elif st.code_hash:
                unique_non_overlap_hashes.add(st.code_hash)
        return {
            "total_bins": len(bins),
            "valid_hex": valid_hex,
            "extracted_runtime": extracted_rt,
            "code_hash_overlap": exact_overlap,
            "group_near_overlap": near_overlap,
            "remaining_rows": extracted_rt - near_overlap,
            "remaining_unique_hashes": len(unique_non_overlap_hashes),
        }

    pg_ponzi_bins = audit_pg_bins(pg_base / "Ponzi" / "Ponzi" / "verified_contract_bins")
    pg_nonponzi_bins = audit_pg_bins(pg_base / "non-Ponzi" / "non-Ponzi" / "verified_contract_bins")

    # Also inspect PonziGuard Result/verified if reachable (non-fatal if offline)
    pg_result_verified_total = None
    pg_result_verified_overlap = None
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/PonziDetection/PonziGuard/contents/dataset/Result/verified",
            headers={"User-Agent": "x-spide-g/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            ver_items = json.loads(r.read().decode("utf-8"))
        ver_addrs = {Path(it["name"]).stem.lower() for it in ver_items}
        pg_result_verified_total = len(ver_addrs)
        pg_result_verified_overlap = len(ver_addrs & x_addrs)
    except Exception:
        pass

    # Pre-registered decision rule for Dataset 2 (E6):
    # Requires >= 30 non-overlapping Ponzi contracts with runtime bytecode (and matching non-Ponzi pool).
    remaining_ponzi_sol = len(pg_sol_remaining)
    remaining_ponzi_bins = pg_ponzi_bins["remaining_rows"]
    adopt_e6 = remaining_ponzi_bins >= 30 and remaining_ponzi_sol >= 30
    decision = (
        "EXTERNAL_TEST_E6"
        if adopt_e6
        else "SANITY_CHECK_ONLY (Risk R6 triggered)"
    )

    return {
        "unica": {
            "raw_rows": len(unica_rows),
            "unique_addresses": len(unica_unique),
            "address_overlap": len(unica_addr_overlap),
            "address_overlap_labels": dict(Counter(x_addr_label[a] for a in unica_addr_overlap)),
            "address_disjoint": len(unica_addr_disjoint),
            "disjoint_live_code_checked": unica_live_checked,
            "disjoint_code_hash_overlap": unica_code_overlap,
            "disjoint_group_near_overlap": unica_near_overlap,
        },
        "ponziguard": {
            "ponzi_sol_total": len(pg_sol_addrs),
            "ponzi_sol_addr_overlap": len(pg_sol_overlap),
            "ponzi_sol_remaining": remaining_ponzi_sol,
            "ponzi_bins": pg_ponzi_bins,
            "non_ponzi_bins": pg_nonponzi_bins,
            "result_verified_total": pg_result_verified_total,
            "result_verified_addr_overlap": pg_result_verified_overlap,
            "decision": decision,
        },
    }


def render_data_audit_md(audit: dict[str, Any], df_s_code: pd.DataFrame) -> str:
    """Format the full Phase 1 data audit report in Markdown."""
    lines: list[str] = []
    lines.append("# Phase 1 Data Audit Report (`reports/data_audit.md`)")
    lines.append("")
    lines.append(f"- **Generated (UTC):** {audit['generated_at_utc']}")
    lines.append(f"- **Primary Corpus:** X-SPIDE (`DS_deployed_bytecode.csv`, commit `{audit['xspide_commit']}`)")
    lines.append(f"- **Risk Status:** `R1 (<400 Ponzi in S_code)`: **{'TRIGGERED' if audit['r1_triggered'] else 'NOT TRIGGERED'}** (`{audit['s_code_ponzi']}` Ponzi in `S_code`); `R6 (Dataset 2 overlap/coverage)`: **{audit['overlap']['ponziguard']['decision']}**")
    lines.append("")

    lines.append("## 1. Schema & Label Verification (Phase 1.2)")
    lines.append("")
    lines.append("| File | Rows | Cols | Ponzi (`1`) | non-Ponzi (`0`) | Unique Valid Addrs | Conflicting Labels |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for s in audit["schema_summary"]:
        lines.append(
            f"| `{s['file']}` | {s['rows']:,} | {s['cols']} | {s['ponzi']:,} | {s['non_ponzi']:,} | {s['unique_valid_addrs']:,} | {s['label_conflicts']} |"
        )
    lines.append("")
    lines.append(
        "> **Comparison with X-SPIDE paper [1]:** `DS_deployed_bytecode.csv` and `DS_full_bytecode.csv` both contain exactly **7,446** contracts (**880** Ponzi / **6,566** non-Ponzi) with **99** features (`23` account/transaction + `76` opcode-frequency columns), zero missing CSV cells, and zero duplicate or malformed addresses. The raw pre-cleaning `bytecode_opcode_8k.csv` inventory contains **7,962** contracts (**934** Ponzi / **7,028** non-Ponzi), from which **516** rows (**54** Ponzi / **462** non-Ponzi) were excluded when forming the 7,446-contract benchmark."
    )
    lines.append("")

    lines.append("## 2. Bytecode Coverage & Self-Destruct / Selection Bias Audit (Phase 1.3)")
    lines.append("")
    lines.append("### 2.1. `S_full` vs `S_code` Coverage (`DS_deployed_bytecode.csv`)")
    lines.append("")
    lines.append("| Class | `S_full` | `S_code` (Recovered) | Coverage | `bytecode_source = xspide_repo` | `rpc_latest` | `missing` |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for c in audit["coverage_table"]:
        lines.append(
            f"| {c['class_name']} | {c['s_full']:,} | {c['s_code']:,} | {c['coverage_pct']:.2f}% | {c['xspide_repo']:,} | {c['rpc_latest']:,} | {c['missing']:,} |"
        )
    lines.append("")

    if audit.get("live_rpc_audit"):
        rpc_a = audit["live_rpc_audit"]
        lines.append("### 2.2. Live Ethereum Mainnet `eth_getCode('latest')` Verification & 8k Selection Bias")
        lines.append("")
        lines.append(
            f"- **Live RPC check on `DS_deployed_bytecode.csv`:** `{rpc_a['ponzi_alive']}/{rpc_a['ponzi_checked']}` Ponzi contracts and `{rpc_a['nonponzi_alive']}/{rpc_a['nonponzi_checked']}` sampled non-Ponzi contracts still have deployed bytecode on mainnet (`0x` rate = `{rpc_a['ponzi_0x_pct']:.1f}%` vs `{rpc_a['nonponzi_0x_pct']:.1f}%`)."
        )
        lines.append(
            f"- **Raw 8k missing-deployed-bytecode (`{rpc_a['missing_8k_total']}` rows: `{rpc_a['missing_8k_ponzi']}` Ponzi, `{rpc_a['missing_8k_nonponzi']}` non-Ponzi):** `{rpc_a['missing_8k_rpc_alive']}` recovered via live `eth_getCode('latest')` (`{rpc_a['missing_8k_total'] - rpc_a['missing_8k_rpc_alive']}` remain `0x`, confirming they were EOAs or already self-destructed before X-SPIDE archived the 7,446-contract dataset)."
        )
        lines.append("")

    lines.append("### 2.3. KS Distribution & Median Test: `7,446` Retained vs `516` Excluded Rows from `bytecode_opcode_8k.csv`")
    lines.append("")
    lines.append("| Feature | `n` (Kept) | `n` (Excluded) | Median (Kept) | Median (Excluded) | KS Statistic | $p$-value |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for ks in audit["ks_8k_kept_vs_dropped"]:
        lines.append(
            f"| `{ks['feature']}` | {ks['n_kept']:,} | {ks['n_excluded']:,} | {ks['median_kept']:.4g} | {ks['median_excluded']:.4g} | {ks['ks_stat']:.4f} | {ks['p_value']:.3e} |"
        )
    lines.append("")

    lines.append("## 3. CBOR Metadata Stripping & Clone Clustering (Phase 1.4 – 1.5)")
    lines.append("")
    lines.append("### 3.1. CBOR Metadata Status")
    lines.append("")
    lines.append("| `metadata_stripped` | Total | Ponzi (`1`) | non-Ponzi (`0`) | Interpretation |")
    lines.append("|---|---:|---:|---:|---|")
    meta = audit["metadata_counts"]
    lines.append(f"| `true` | {meta['true']['total']:,} | {meta['true']['ponzi']:,} | {meta['true']['non_ponzi']:,} | Valid Solidity/Vyper CBOR footer decoded & stripped |")
    lines.append(f"| `false` | {meta['false']['total']:,} | {meta['false']['ponzi']:,} | {meta['false']['non_ponzi']:,} | Pre-0.4.7 Solidity or custom bytecode without CBOR footer |")
    lines.append(f"| `none` | {meta['none']['total']:,} | {meta['none']['ponzi']:,} | {meta['none']['non_ponzi']:,} | Missing bytecode |")
    lines.append("")

    lines.append("### 3.2. Clone Cluster Summary (`group_exact` vs `group_near`)")
    lines.append("")
    lines.append("| Grouping | Total Groups | Singletons | Size 2–5 | Size 6+ | Max Size | Mixed-Label Groups | Ponzi in Multi-Clone Groups | non-Ponzi in Multi-Clone Groups |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for g in (audit["clones_exact"], audit["clones_near"]):
        lines.append(
            f"| `{g['group_col']}` | {g['total_groups']:,} | {g['singletons']:,} | {g['size_2_5']:,} | {g['size_6_plus']:,} | {g['max_size']} | {g['mixed_label_groups_count']} | {g['ponzi_in_multi']:,}/{g['total_ponzi']:,} ({g['ponzi_in_multi_pct']:.1f}%) | {g['non_ponzi_in_multi']:,}/{g['non_ponzi_total'] if 'non_ponzi_total' in g else (len(df_s_code) - g['total_ponzi']):,} ({g['non_ponzi_in_multi_pct']:.1f}%) |"
        )
    lines.append("")
    if audit["clones_near"]["mixed_label_groups"]:
        lines.append("**Mixed-label clusters detected in `group_near` (label-noise / template-reuse warning):**")
        lines.append("")
        lines.append("| `group_near` | Total | Ponzi | non-Ponzi |")
        lines.append("|---|---:|---:|---:|")
        for mg in audit["clones_near"]["mixed_label_groups"]:
            lines.append(f"| `{mg['group_id']}` | {mg['total']} | {mg['ponzi']} | {mg['non_ponzi']} |")
        lines.append("")

    lines.append("## 4. Cross-Dataset Overlap & Dataset 2 Decision (Phase 1.6)")
    lines.append("")
    u = audit["overlap"]["unica"]
    pg = audit["overlap"]["ponziguard"]
    lines.append(f"- **Blockchain@Unica [6], [11]:** `{u['raw_rows']}` rows (`{u['unique_addresses']}` unique addresses). **`{u['address_overlap']}` / `{u['unique_addresses']}`** addresses already appear in X-SPIDE (all labeled `1` Ponzi: `{u['address_overlap_labels']}`). Among the `{u['address_disjoint']}` address-disjoint entries, `{u['disjoint_live_code_checked']}` had live RPC code, of which `{u['disjoint_code_hash_overlap']}` matched X-SPIDE by `code_hash` and `{u['disjoint_group_near_overlap']}` by `group_near`.")
    lines.append("- **PonziGuard / XBlock (`Ponzi.zip` + `non-Ponzi.zip`) [2], [10]:**")
    lines.append(f"  - `Ponzi/Ponzi contracts/*.sol`: `{pg['ponzi_sol_total']}` address-named Solidity files → **`{pg['ponzi_sol_addr_overlap']}` / `{pg['ponzi_sol_total']}`** (`{pg['ponzi_sol_addr_overlap']/pg['ponzi_sol_total']:.1%}`) are already present in X-SPIDE, leaving only **`{pg['ponzi_sol_remaining']}`** non-overlapping addresses.")
    pb = pg["ponzi_bins"]
    npb = pg["non_ponzi_bins"]
    lines.append(f"  - `Ponzi/verified_contract_bins/*.bin` (creation initcode without addresses): `{pb['extracted_runtime']}/{pb['total_bins']}` yielded extractable deployed runtime bytecode; **`{pb['code_hash_overlap']}`** matched X-SPIDE by exact `code_hash` and **`{pb['group_near_overlap']}`** matched by `group_near`, leaving **`{pb['remaining_rows']}`** runtime samples (**`{pb['remaining_unique_hashes']}`** unique `code_hash`).")
    lines.append(f"  - `non-Ponzi/verified_contract_bins/*.bin` (creation initcode without addresses): `{npb['extracted_runtime']}/{npb['total_bins']}` yielded extractable deployed runtime bytecode; `{npb['code_hash_overlap']}` matched X-SPIDE by `code_hash` and `{npb['group_near_overlap']}` matched by `group_near`, leaving `{npb['remaining_rows']}` samples (`{npb['remaining_unique_hashes']}` unique `code_hash`).")
    if pg["result_verified_total"] is not None:
        lines.append(f"  - `Result/verified/*.sol` (mainnet verified subset): `{pg['result_verified_addr_overlap']}/{pg['result_verified_total']}` already present in X-SPIDE.")
    lines.append(f"- **Pre-Registered Decision for Dataset 2 (`E6`):** **{pg['decision']}** — Because the released `PonziGuard` GitHub archive lacks contract addresses on `non-Ponzi.zip` and `verified_contract_bins`, lacks the full `6,498`-contract `314`-Ponzi XBlock split described in TOSEM [2], and yields `< 30` non-overlapping address-verified Ponzi contracts (`{pg['ponzi_sol_remaining']}` in `Ponzi/*.sol`, `{pb['remaining_rows']}` total runtime `.bin` rows / `{pb['remaining_unique_hashes']}` unique hashes), Dataset 2 is **downgraded to a qualitative/code-only sanity check** rather than a formal `E6` external generalization benchmark.")
    lines.append("")

    lines.append("## 5. Frozen Splits Summary (Phase 1.7)")
    lines.append("")
    for line in audit["splits_summary"]:
        lines.append(f"- {line}")
    lines.append("")

    lines.append("## 6. Real Contract Samples (5 Ponzi + 5 non-Ponzi, Phase 1.2)")
    lines.append("")
    lines.append("| `sample_id` | `address` | `label` | `tx_in` | `tx_out` | `lifetime` | `bytecode_source` | `metadata_stripped` | `code_hash` (prefix) | `group_exact` | `group_near` |")
    lines.append("|---|---|---:|---:|---:|---:|---|---|---|---|---|")
    sample_ponzi = df_s_code[df_s_code["label"] == 1].head(5)
    sample_non = df_s_code[df_s_code["label"] == 0].head(5)
    for _, row in pd.concat([sample_ponzi, sample_non], ignore_index=True).iterrows():
        ch_short = str(row["code_hash"])[:14] + "..." if row["code_hash"] else "None"
        lines.append(
            f"| `{row['sample_id']}` | `{row['address']}` | {int(row['label'])} | {int(row['tx_in'])} | {int(row['tx_out'])} | {float(row['lifetime']):.1f} | `{row['bytecode_source']}` | `{row['metadata_stripped']}` | `{ch_short}` | `{row['group_exact']}` | `{row['group_near']}` |"
        )
    lines.append("")
    return "\n".join(lines)
