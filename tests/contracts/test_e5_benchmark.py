"""Unit tests for Phase 7 (E5) benchmark suite, cost calculations, and plotting."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.contracts.e5_benchmark import (
    PriceAnchor,
    compute_latency_summary,
    compute_mainnet_usd,
    enrich_gas_rows_with_price_anchor,
    generate_gas_vs_batch_plot,
    run_anvil_gas_suite,
)


def test_anvil_gas_suite_covers_variants_cold_warm_and_batches(tmp_path: Path) -> None:
    rows = run_anvil_gas_suite()
    assert len(rows) > 30
    df = pd.DataFrame(rows)

    assert set(df["variant"].unique()) == {"D1", "D2", "D3"}
    assert set(df["network"].unique()) == {"anvil_pyevm"}

    d1_tot = df[(df["variant"] == "D1") & (df["operation"] == "finalized_case_total")].iloc[0]
    d2_tot = df[(df["variant"] == "D2") & (df["operation"] == "finalized_case_total")].iloc[0]
    assert float(d1_tot["gas_used"]) > 250_000
    assert bool(d1_tot["meets_target"]) is False
    assert float(d2_tot["gas_used"]) < float(d1_tot["gas_used"])

    # Warm replacement attestation should be noticeably cheaper than cold first write.
    d1_cold = float(df[(df["variant"] == "D1") & (df["operation"] == "attest_cold_1_open")]["gas_used"].iloc[0])
    d1_warm = float(df[(df["variant"] == "D1") & (df["operation"] == "attest_warm_replace")]["gas_used"].iloc[0])
    assert d1_warm < d1_cold

    # Governance remove_auditor measured across all three variants.
    rem_rows = df[(df["operation"] == "remove_auditor") & (df["storage_mode"] == "warm_update")]
    assert set(rem_rows["variant"].unique()) == {"D1", "D2", "D3"}
    assert (rem_rows["gas_used"] > 21_000).all()

    # D3 amortized cost across N in {1, 10, 100, 1000}
    d3_tot = df[(df["variant"] == "D3") & (df["operation"] == "batch_finalized_total")].sort_values("batch_size")
    assert list(d3_tot["batch_size"].astype(int)) == [1, 10, 100, 1000]
    per_100 = float(d3_tot[d3_tot["batch_size"] == 100]["gas_per_case"].iloc[0])
    per_1000 = float(d3_tot[d3_tot["batch_size"] == 1000]["gas_per_case"].iloc[0])
    assert per_100 <= 10_000
    assert per_1000 <= 1_000
    assert bool(d3_tot[d3_tot["batch_size"] == 100]["meets_target"].iloc[0]) is True

    anchor = PriceAnchor(
        fetched_utc="2026-11-14T00:00:00Z",
        mainnet_block_range="100..200",
        mainnet_median_base_fee_gwei=1.0,
        mainnet_median_priority_fee_gwei=0.5,
        mainnet_median_gas_price_gwei=1.5,
        etherscan_propose_gwei=1.5,
        eth_usd=2000.0,
        gas_source="unit-test",
        eth_price_source="unit-test",
    )
    enriched = enrich_gas_rows_with_price_anchor(rows, anchor)
    edf = pd.DataFrame(enriched)
    assert "mainnet_ref_cost_usd" in edf.columns
    expected_d1_usd = compute_mainnet_usd(float(d1_tot["gas_used"]), 1.5, 2000.0)
    actual_d1_usd = float(
        edf[(edf["variant"] == "D1") & (edf["operation"] == "finalized_case_total")][
            "mainnet_ref_cost_usd"
        ].iloc[0]
    )
    assert abs(expected_d1_usd - actual_d1_usd) < 1e-6

    plot_out = generate_gas_vs_batch_plot(edf, tmp_path / "gas_vs_batch.png")
    assert plot_out.is_file()
    assert plot_out.stat().st_size > 10_000


def test_latency_summary_computes_median_p95_and_target() -> None:
    rows = [
        {
            "network": "sepolia",
            "latency_seconds": float(i + 1),
            "blocks_to_confirm": 1 if i < 18 else 2,
            "gas_used": 100_000 + i * 100,
            "fee_eth": 0.0001,
            "fee_usd": 0.2,
        }
        for i in range(20)
    ]
    rows.append(
        {
            "network": "arbitrum-sepolia",
            "latency_seconds": 0.6,
            "blocks_to_confirm": 1,
            "gas_used": 120_000,
            "fee_eth": 0.000002,
            "fee_usd": 0.004,
        }
    )
    summary = compute_latency_summary(rows)
    assert summary["sepolia"]["n_txs"] == 20
    assert summary["sepolia"]["median_blocks"] == 1.0
    assert summary["sepolia"]["p95_blocks"] == 2.0
    assert summary["sepolia"]["meets_target"] is True
    assert summary["arbitrum-sepolia"]["n_txs"] == 1
    assert summary["arbitrum-sepolia"]["median_seconds"] == 0.6
