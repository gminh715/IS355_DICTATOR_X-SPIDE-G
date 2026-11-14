"""Verification tests for Phase 7 (E5) generated artifacts, schemas, and invariants."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = REPO_ROOT / "results"
FIGURES_DIR = REPO_ROOT / "figures"
REPORTS_DIR = REPO_ROOT / "reports"


def test_e5_gas_csv_contains_all_networks_variants_and_honest_verdicts() -> None:
    gas_path = RESULTS_DIR / "E5_gas.csv"
    assert gas_path.is_file()
    df = pd.read_csv(gas_path)

    required_cols = {
        "network",
        "chain_id",
        "variant",
        "operation",
        "storage_mode",
        "batch_size",
        "gas_used",
        "gas_per_case",
        "prereg_target_gas",
        "meets_target",
        "effective_gas_price_wei",
        "actual_fee_eth",
        "tx_hash",
        "mainnet_ref_gas_price_gwei",
        "mainnet_ref_eth_usd",
        "mainnet_ref_cost_eth",
        "mainnet_ref_cost_usd",
        "mainnet_ref_cost_per_case_usd",
        "actual_fee_usd",
    }
    assert required_cols.issubset(set(df.columns))
    assert set(df["network"].unique()) == {"anvil_pyevm", "sepolia", "arbitrum-sepolia"}
    assert set(df["variant"].unique()) == {"D1", "D2", "D3"}

    anvil_d1 = df[
        (df["network"] == "anvil_pyevm")
        & (df["variant"] == "D1")
        & (df["operation"] == "finalized_case_total")
    ].iloc[0]
    assert float(anvil_d1["gas_per_case"]) > 250_000
    assert bool(anvil_d1["meets_target"]) is False

    anvil_d2 = df[
        (df["network"] == "anvil_pyevm")
        & (df["variant"] == "D2")
        & (df["operation"] == "finalized_case_total")
    ].iloc[0]
    assert float(anvil_d2["gas_per_case"]) < float(anvil_d1["gas_per_case"])

    anvil_d3 = df[
        (df["network"] == "anvil_pyevm")
        & (df["variant"] == "D3")
        & (df["operation"] == "batch_finalized_total")
    ].sort_values("batch_size")
    assert list(anvil_d3["batch_size"].astype(int)) == [1, 10, 100, 1000]
    assert float(anvil_d3[anvil_d3["batch_size"] == 100]["gas_per_case"].iloc[0]) <= 10_000
    assert bool(anvil_d3[anvil_d3["batch_size"] == 100]["meets_target"].iloc[0]) is True
    assert float(anvil_d3[anvil_d3["batch_size"] == 1000]["gas_per_case"].iloc[0]) <= 1_000

    # Arbitrum Sepolia D3 N=100 spot-check also meets <= 10,000 gas/case
    arb_d3 = df[
        (df["network"] == "arbitrum-sepolia")
        & (df["variant"] == "D3")
        & (df["operation"] == "batch_finalized_total")
    ].iloc[0]
    assert float(arb_d3["gas_per_case"]) <= 10_000
    assert bool(arb_d3["meets_target"]) is True
    assert float(arb_d3["actual_fee_usd"]) > 0.0

    # Governance remove_auditor present for D1, D2, D3 on deterministic Anvil suite
    anvil_rem = df[(df["network"] == "anvil_pyevm") & (df["operation"] == "remove_auditor")]
    assert set(anvil_rem["variant"].unique()) == {"D1", "D2", "D3"}

    # Fixed mainnet reference price anchor applied across every row
    assert (df["mainnet_ref_gas_price_gwei"] > 0.0).all()
    assert (df["mainnet_ref_eth_usd"] > 0.0).all()
    assert (df["mainnet_ref_cost_usd"] > 0.0).all()


def test_e5_latency_csv_has_30_txs_per_live_chain_and_meets_sepolia_target() -> None:
    lat_path = RESULTS_DIR / "E5_latency.csv"
    assert lat_path.is_file()
    df = pd.read_csv(lat_path)

    assert len(df) == 60
    assert (df["status"] == 1).all()
    assert (df["latency_seconds"] > 0.0).all()
    assert (df["blocks_to_confirm"] >= 1).all()

    for net in ("sepolia", "arbitrum-sepolia"):
        sub = df[df["network"] == net]
        assert len(sub) == 30
        assert (sub["write_type"] == "cold_first_write").sum() == 15
        assert (sub["write_type"] == "warm_update").sum() == 15
        assert sub["tx_hash"].nunique() == 30

    sep = df[df["network"] == "sepolia"]
    assert float(sep["blocks_to_confirm"].median()) <= 2.0


def test_e5_summary_json_security_evidence_and_outputs() -> None:
    summary_path = RESULTS_DIR / "E5_summary.json"
    assert summary_path.is_file()
    summ = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summ["price_anchor"]["eth_usd"] > 0
    assert summ["price_anchor"]["mainnet_median_gas_price_gwei"] > 0
    assert summ["latency_summary"]["sepolia"]["n_txs"] == 30
    assert summ["latency_summary"]["sepolia"]["meets_target"] is True
    assert summ["latency_summary"]["arbitrum-sepolia"]["n_txs"] == 30

    sep_sec = summ["live_networks"]["sepolia"]["security_on_main_d1"]
    assert sep_sec["state_unchanged_verified"] is True
    assert sep_sec["auditor_count"] == 3
    assert sep_sec["threshold"] == 2
    assert sep_sec["case_registered_count"] == 0

    for key in (
        "T1_non_auditor_register_revert",
        "T1_non_auditor_attest_revert",
        "T6_owner_register_revert",
        "T6_owner_attest_revert",
        "T6_owner_add_self_revert",
    ):
        assert sep_sec[key]["status"] == 0
        assert str(sep_sec[key]["tx_hash"]).startswith("0x")

    t8 = summ["live_networks"]["sepolia"]["T8_sepolia_verify_evidence"]
    assert t8["verify_exact_onchain"] is True
    assert t8["verify_tampered_onchain"] is False
    assert t8["exact_evidence_hash"] != t8["tampered_1byte_hash"]

    plot_path = FIGURES_DIR / "gas_vs_batch.png"
    assert plot_path.is_file()
    assert plot_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert plot_path.stat().st_size > 20_000


def test_rq3_report_and_no_leaked_secrets() -> None:
    report_path = REPORTS_DIR / "rq3_onchain.md"
    assert report_path.is_file()
    text = report_path.read_text(encoding="utf-8")

    for required_phrase in (
        "FAIL",
        "PASS",
        "427,461",
        "3,574.53",
        "EIP-8037",
        "ProvAuditChain",
        "non-head-to-head",
        "reference-only",
        "0x14895F5e1f7F1aC5C58b35dA6d57674Aa5951b77",
        "0x0ff94b4e0f5076059937b331ba6fba7ed8301a034fa78c05d6f32abcb945bb19",
        "0x56764e897eec218d260f2208723495421b1313de1ea858913f8e057c8c3e89bc",
    ):
        assert required_phrase in text

    for artifact_text in (
        text,
        (RESULTS_DIR / "E5_gas.csv").read_text(encoding="utf-8"),
        (RESULTS_DIR / "E5_latency.csv").read_text(encoding="utf-8"),
        (RESULTS_DIR / "E5_summary.json").read_text(encoding="utf-8"),
    ):
        low = artifact_text.lower()
        assert "infura.io/v3/" not in low
        assert "alchemy.com/v2/" not in low
        assert "private_key" not in low
