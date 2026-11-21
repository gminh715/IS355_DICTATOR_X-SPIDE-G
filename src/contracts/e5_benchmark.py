"""Phase 7 (E5) on-chain gas, cost, and confirmation-latency benchmarking utilities."""

from __future__ import annotations

import math
import os
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from eth_abi import encode
from eth_tester import EthereumTester, PyEVMBackend
from eth_utils import keccak
from web3 import Web3
from web3.providers.eth_tester import EthereumTesterProvider

from src.contracts.compiler import compile_contract
from src.contracts.merkle import MerkleTree, compute_leaf

MAINNET_PUBLIC_RPCS: tuple[str, ...] = (
    "https://ethereum-rpc.publicnode.com",
    "https://eth.llamarpc.com",
    "https://rpc.ankr.com/eth",
)

D3_BATCH_SIZES: tuple[int, ...] = (1, 10, 100, 1000)

PREREG_D1_MAX_GAS = 250_000
PREREG_D3_AMORTIZED_MAX_GAS = 10_000
PREREG_SEPOLIA_MEDIAN_BLOCKS = 2.0


@dataclass(frozen=True)
class PriceAnchor:
    """Fixed-date Ethereum mainnet gas price and ETH/USD reference anchor."""

    fetched_utc: str
    mainnet_block_range: str
    mainnet_median_base_fee_gwei: float
    mainnet_median_priority_fee_gwei: float
    mainnet_median_gas_price_gwei: float
    etherscan_propose_gwei: float | None
    eth_usd: float
    gas_source: str
    eth_price_source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "fetched_utc": self.fetched_utc,
            "mainnet_block_range": self.mainnet_block_range,
            "mainnet_median_base_fee_gwei": round(self.mainnet_median_base_fee_gwei, 6),
            "mainnet_median_priority_fee_gwei": round(self.mainnet_median_priority_fee_gwei, 6),
            "mainnet_median_gas_price_gwei": round(self.mainnet_median_gas_price_gwei, 6),
            "etherscan_propose_gwei": (
                round(self.etherscan_propose_gwei, 6)
                if self.etherscan_propose_gwei is not None
                else None
            ),
            "eth_usd": round(self.eth_usd, 2),
            "gas_source": self.gas_source,
            "eth_price_source": self.eth_price_source,
        }


def compute_mainnet_usd(gas_used: float, gas_price_gwei: float, eth_usd: float) -> float:
    """Compute reference USD cost from gasUsed, gas price (gwei), and ETH/USD."""
    eth_cost = float(gas_used) * float(gas_price_gwei) * 1e-9
    return eth_cost * float(eth_usd)


def fetch_mainnet_price_anchor(
    *,
    block_window: int = 100,
    etherscan_api_key: str | None = None,
) -> PriceAnchor:
    """Fetch empirical Ethereum mainnet median gas price and fixed-date ETH/USD quote."""
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    api_key = (etherscan_api_key or os.environ.get("ETHERSCAN_API_KEY", "")).strip()

    block_range = "unavailable"
    med_base = 0.0
    med_prio = 0.0
    med_total = 0.0
    gas_source = ""

    for rpc_url in MAINNET_PUBLIC_RPCS:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
            if not w3.is_connected() or int(w3.eth.chain_id) != 1:
                continue
            fh = w3.eth.fee_history(block_window, "latest", [50])
            bases_gwei = [float(b) / 1e9 for b in fh["baseFeePerGas"][:-1]]
            rewards = fh.get("reward") or []
            prios_gwei = [float(r[0]) / 1e9 for r in rewards if r]
            if not bases_gwei:
                continue
            n_paired = min(len(bases_gwei), len(prios_gwei))
            if n_paired > 0:
                totals = [bases_gwei[i] + prios_gwei[i] for i in range(n_paired)]
                med_base = statistics.median(bases_gwei[:n_paired])
                med_prio = statistics.median(prios_gwei[:n_paired])
                med_total = statistics.median(totals)
            else:
                med_base = statistics.median(bases_gwei)
                med_total = med_base
            oldest = int(fh["oldestBlock"])
            newest = oldest + len(bases_gwei) - 1
            block_range = f"{oldest}..{newest}"
            gas_source = f"{rpc_url} eth_feeHistory({block_window} blocks, p50 priority)"
            break
        except Exception:
            continue

    etherscan_propose: float | None = None
    eth_usd: float | None = None
    eth_price_source = ""

    if api_key:
        try:
            r_gas = requests.get(
                "https://api.etherscan.io/v2/api",
                params={
                    "chainid": 1,
                    "module": "gastracker",
                    "action": "gasoracle",
                    "apikey": api_key,
                },
                timeout=15,
            )
            r_gas.raise_for_status()
            gdata = r_gas.json()
            if str(gdata.get("status")) == "1":
                etherscan_propose = float(gdata["result"]["ProposeGasPrice"])
                if not gas_source:
                    med_total = etherscan_propose
                    med_base = float(gdata["result"].get("suggestBaseFee", etherscan_propose))
                    med_prio = max(0.0, med_total - med_base)
                    block_range = f"block {gdata['result'].get('LastBlock', 'latest')}"
                    gas_source = "Etherscan v2 gastracker.gasoracle ProposeGasPrice"
        except Exception:
            pass

        try:
            r_eth = requests.get(
                "https://api.etherscan.io/v2/api",
                params={
                    "chainid": 1,
                    "module": "stats",
                    "action": "ethprice",
                    "apikey": api_key,
                },
                timeout=15,
            )
            r_eth.raise_for_status()
            pdata = r_eth.json()
            if str(pdata.get("status")) == "1":
                eth_usd = float(pdata["result"]["ethusd"])
                eth_price_source = "Etherscan v2 stats.ethprice"
        except Exception:
            pass

    if eth_usd is None:
        r_cg = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "ethereum", "vs_currencies": "usd"},
            timeout=15,
        )
        r_cg.raise_for_status()
        eth_usd = float(r_cg.json()["ethereum"]["usd"])
        eth_price_source = "CoinGecko /api/v3/simple/price"

    if not gas_source:
        raise RuntimeError("Failed to fetch Ethereum mainnet gas price from RPC and Etherscan.")

    return PriceAnchor(
        fetched_utc=now_utc,
        mainnet_block_range=block_range,
        mainnet_median_base_fee_gwei=med_base,
        mainnet_median_priority_fee_gwei=med_prio,
        mainnet_median_gas_price_gwei=med_total,
        etherscan_propose_gwei=etherscan_propose,
        eth_usd=eth_usd,
        gas_source=gas_source,
        eth_price_source=eth_price_source,
    )


def _tx_hex(raw_hash: Any) -> str:
    h = raw_hash.hex() if hasattr(raw_hash, "hex") else str(raw_hash)
    return h if h.startswith("0x") else f"0x{h}"


def _make_gas_row(
    *,
    network: str,
    chain_id: int,
    variant: str,
    operation: str,
    storage_mode: str,
    batch_size: int,
    gas_used: float,
    gas_per_case: float,
    prereg_target_gas: float | None = None,
    meets_target: bool | None = None,
    effective_gas_price_wei: int | None = None,
    actual_fee_eth: float | None = None,
    tx_hash: str = "",
    notes: str = "",
) -> dict[str, Any]:
    return {
        "network": network,
        "chain_id": int(chain_id),
        "variant": variant,
        "operation": operation,
        "storage_mode": storage_mode,
        "batch_size": int(batch_size),
        "gas_used": round(float(gas_used), 2),
        "gas_per_case": round(float(gas_per_case), 2),
        "prereg_target_gas": prereg_target_gas if prereg_target_gas is not None else "",
        "meets_target": meets_target if meets_target is not None else "",
        "effective_gas_price_wei": effective_gas_price_wei if effective_gas_price_wei is not None else "",
        "actual_fee_eth": f"{actual_fee_eth:.12f}" if actual_fee_eth is not None else "",
        "tx_hash": tx_hash,
        "notes": notes,
    }


def run_anvil_gas_suite() -> list[dict[str, Any]]:
    """Run deterministic PyEVM/Anvil gas measurements across D1, D2, and D3."""
    w3 = Web3(EthereumTesterProvider(EthereumTester(PyEVMBackend())))
    owner = w3.eth.accounts[0]
    a1, a2, a3 = w3.eth.accounts[1:4]
    subject = w3.eth.accounts[5]
    chain_id = int(w3.eth.chain_id)
    net = "anvil_pyevm"

    rows: list[dict[str, Any]] = []
    sample_uri = "ipfs://bafkreih23hlqee2yymwc7pa3obzpx6lyqpfmvkaphxgswpoy57pdnjhxhu"
    mh = keccak(b"e5-model-version-v1")
    rh = keccak(b"e5-reason-hash")

    contracts: dict[str, Any] = {}
    for variant in ("D1", "D2", "D3"):
        compiled = compile_contract(variant, use_cache=True)
        factory = w3.eth.contract(abi=compiled.abi, bytecode=compiled.bytecode)
        rc_dep = w3.eth.wait_for_transaction_receipt(
            factory.constructor("0x0000000000000000000000000000000000000000").transact({"from": owner})
        )
        inst = w3.eth.contract(address=rc_dep.contractAddress, abi=compiled.abi)
        contracts[variant] = inst
        rows.append(
            _make_gas_row(
                network=net,
                chain_id=chain_id,
                variant=variant,
                operation="deploy",
                storage_mode="deployment",
                batch_size=1,
                gas_used=rc_dep.gasUsed,
                gas_per_case=rc_dep.gasUsed,
                tx_hash=_tx_hex(rc_dep.transactionHash),
                notes="Contract creation + constructor threshold=2",
            )
        )

        for idx, aud in enumerate((a1, a2, a3)):
            rc_add = w3.eth.wait_for_transaction_receipt(
                inst.functions.add_auditor(aud).transact({"from": owner})
            )
            op_name = "add_auditor_cold_first" if idx == 0 else f"add_auditor_{idx + 1}"
            rows.append(
                _make_gas_row(
                    network=net,
                    chain_id=chain_id,
                    variant=variant,
                    operation=op_name,
                    storage_mode="cold_first_write" if idx == 0 else "cold_mapping_warm_count",
                    batch_size=1,
                    gas_used=rc_add.gasUsed,
                    gas_per_case=rc_add.gasUsed,
                    tx_hash=_tx_hex(rc_add.transactionHash),
                )
            )

        rc_k = w3.eth.wait_for_transaction_receipt(
            inst.functions.set_threshold(2).transact({"from": owner})
        )
        rows.append(
            _make_gas_row(
                network=net,
                chain_id=chain_id,
                variant=variant,
                operation="set_threshold",
                storage_mode="warm_update",
                batch_size=1,
                gas_used=rc_k.gasUsed,
                gas_per_case=rc_k.gasUsed,
                tx_hash=_tx_hex(rc_k.transactionHash),
            )
        )

    # Measure D1 and D2 case lifecycle: register -> cold attest 1 -> cold attest 2 (finalize) -> warm replace
    for variant in ("D1", "D2"):
        inst = contracts[variant]
        cid = keccak(encode(["string", "uint256"], [f"e5-{variant}", 1]))
        eh = keccak(encode(["string", "uint256"], [f"evidence-{variant}", 1]))

        rc_reg = w3.eth.wait_for_transaction_receipt(
            inst.functions.register_case(cid, subject, 1, eh, mh, sample_uri).transact({"from": a1})
        )
        rc_att1 = w3.eth.wait_for_transaction_receipt(
            inst.functions.attest(cid, 1, rh).transact({"from": a1})
        )
        rc_att2 = w3.eth.wait_for_transaction_receipt(
            inst.functions.attest(cid, 1, rh).transact({"from": a2})
        )
        rc_att3 = w3.eth.wait_for_transaction_receipt(
            inst.functions.attest(cid, 2, rh).transact({"from": a3})
        )
        rc_rep = w3.eth.wait_for_transaction_receipt(
            inst.functions.attest(cid, 2, rh).transact({"from": a1})
        )

        ve_exact = int(inst.functions.verify_evidence(cid, eh).estimate_gas())
        ve_bad = int(inst.functions.verify_evidence(cid, keccak(b"tampered")).estimate_gas())
        total_finalized = int(rc_reg.gasUsed) + int(rc_att1.gasUsed) + int(rc_att2.gasUsed)

        rows.extend(
            [
                _make_gas_row(
                    network=net,
                    chain_id=chain_id,
                    variant=variant,
                    operation="register_case",
                    storage_mode="cold_first_write",
                    batch_size=1,
                    gas_used=rc_reg.gasUsed,
                    gas_per_case=rc_reg.gasUsed,
                    tx_hash=_tx_hex(rc_reg.transactionHash),
                ),
                _make_gas_row(
                    network=net,
                    chain_id=chain_id,
                    variant=variant,
                    operation="attest_cold_1_open",
                    storage_mode="cold_first_write",
                    batch_size=1,
                    gas_used=rc_att1.gasUsed,
                    gas_per_case=rc_att1.gasUsed,
                    tx_hash=_tx_hex(rc_att1.transactionHash),
                    notes="1st auditor Approve (status stays Open)",
                ),
                _make_gas_row(
                    network=net,
                    chain_id=chain_id,
                    variant=variant,
                    operation="attest_cold_2_finalize",
                    storage_mode="cold_first_write",
                    batch_size=1,
                    gas_used=rc_att2.gasUsed,
                    gas_per_case=rc_att2.gasUsed,
                    tx_hash=_tx_hex(rc_att2.transactionHash),
                    notes="2nd auditor Approve (Open -> Approved + StatusChanged)",
                ),
                _make_gas_row(
                    network=net,
                    chain_id=chain_id,
                    variant=variant,
                    operation="attest_cold_3_additional",
                    storage_mode="cold_first_write",
                    batch_size=1,
                    gas_used=rc_att3.gasUsed,
                    gas_per_case=rc_att3.gasUsed,
                    tx_hash=_tx_hex(rc_att3.transactionHash),
                    notes="3rd auditor Reject while already Approved",
                ),
                _make_gas_row(
                    network=net,
                    chain_id=chain_id,
                    variant=variant,
                    operation="attest_warm_replace",
                    storage_mode="warm_update",
                    batch_size=1,
                    gas_used=rc_rep.gasUsed,
                    gas_per_case=rc_rep.gasUsed,
                    tx_hash=_tx_hex(rc_rep.transactionHash),
                    notes="Auditor 1 changes Approve -> Reject (warm slots, Approved -> Rejected)",
                ),
                _make_gas_row(
                    network=net,
                    chain_id=chain_id,
                    variant=variant,
                    operation="finalized_case_total",
                    storage_mode="aggregate",
                    batch_size=1,
                    gas_used=total_finalized,
                    gas_per_case=total_finalized,
                    prereg_target_gas=PREREG_D1_MAX_GAS if variant == "D1" else None,
                    meets_target=(total_finalized <= PREREG_D1_MAX_GAS) if variant == "D1" else None,
                    notes="register_case + 2 cold attestations (k=2)",
                ),
                _make_gas_row(
                    network=net,
                    chain_id=chain_id,
                    variant=variant,
                    operation="verify_evidence_exact_est",
                    storage_mode="view_estimate",
                    batch_size=1,
                    gas_used=ve_exact,
                    gas_per_case=ve_exact,
                    notes="Off-chain view call estimateGas (0 RPC fee)",
                ),
                _make_gas_row(
                    network=net,
                    chain_id=chain_id,
                    variant=variant,
                    operation="verify_evidence_tampered_est",
                    storage_mode="view_estimate",
                    batch_size=1,
                    gas_used=ve_bad,
                    gas_per_case=ve_bad,
                    notes="Off-chain view call estimateGas on tampered hash (0 RPC fee)",
                ),
            ]
        )

    # Measure D3 Merkle batch across N in {1, 10, 100, 1000}
    d3 = contracts["D3"]
    for n in D3_BATCH_SIZES:
        leaves = [
            compute_leaf(
                keccak(encode(["uint256", "uint256"], [n, idx])),
                keccak(encode(["string", "uint256"], ["ev", idx])),
                mh,
            )
            for idx in range(n)
        ]
        tree = MerkleTree(leaves)
        root = tree.root
        cid0 = keccak(encode(["uint256", "uint256"], [n, 0]))
        eh0 = keccak(encode(["string", "uint256"], ["ev", 0]))
        proof0 = tree.get_proof(0)

        rc_reg_b = w3.eth.wait_for_transaction_receipt(
            d3.functions.register_batch(root, n, f"{sample_uri}").transact({"from": a1})
        )
        rc_att_b1 = w3.eth.wait_for_transaction_receipt(
            d3.functions.attest_batch(root, 1).transact({"from": a1})
        )
        rc_att_b2 = w3.eth.wait_for_transaction_receipt(
            d3.functions.attest_batch(root, 1).transact({"from": a2})
        )
        rc_rep_b = w3.eth.wait_for_transaction_receipt(
            d3.functions.attest_batch(root, 2).transact({"from": a1})
        )

        vi_gas = int(d3.functions.verify_inclusion(leaves[0], proof0, root).estimate_gas())
        vci_gas = int(d3.functions.verify_case_inclusion(cid0, eh0, mh, proof0, root).estimate_gas())
        total_batch = int(rc_reg_b.gasUsed) + int(rc_att_b1.gasUsed) + int(rc_att_b2.gasUsed)
        per_case = total_batch / float(n)
        is_target_n = n >= 100

        rows.extend(
            [
                _make_gas_row(
                    network=net,
                    chain_id=chain_id,
                    variant="D3",
                    operation="register_batch",
                    storage_mode="cold_first_write",
                    batch_size=n,
                    gas_used=rc_reg_b.gasUsed,
                    gas_per_case=rc_reg_b.gasUsed / float(n),
                    tx_hash=_tx_hex(rc_reg_b.transactionHash),
                ),
                _make_gas_row(
                    network=net,
                    chain_id=chain_id,
                    variant="D3",
                    operation="attest_batch_1_open",
                    storage_mode="cold_first_write",
                    batch_size=n,
                    gas_used=rc_att_b1.gasUsed,
                    gas_per_case=rc_att_b1.gasUsed / float(n),
                    tx_hash=_tx_hex(rc_att_b1.transactionHash),
                ),
                _make_gas_row(
                    network=net,
                    chain_id=chain_id,
                    variant="D3",
                    operation="attest_batch_2_finalize",
                    storage_mode="cold_first_write",
                    batch_size=n,
                    gas_used=rc_att_b2.gasUsed,
                    gas_per_case=rc_att_b2.gasUsed / float(n),
                    tx_hash=_tx_hex(rc_att_b2.transactionHash),
                ),
                _make_gas_row(
                    network=net,
                    chain_id=chain_id,
                    variant="D3",
                    operation="attest_batch_warm_replace",
                    storage_mode="warm_update",
                    batch_size=n,
                    gas_used=rc_rep_b.gasUsed,
                    gas_per_case=rc_rep_b.gasUsed / float(n),
                    tx_hash=_tx_hex(rc_rep_b.transactionHash),
                ),
                _make_gas_row(
                    network=net,
                    chain_id=chain_id,
                    variant="D3",
                    operation="batch_finalized_total",
                    storage_mode="aggregate",
                    batch_size=n,
                    gas_used=total_batch,
                    gas_per_case=per_case,
                    prereg_target_gas=PREREG_D3_AMORTIZED_MAX_GAS if is_target_n else None,
                    meets_target=(per_case <= PREREG_D3_AMORTIZED_MAX_GAS) if is_target_n else None,
                    notes=f"Amortized (register_batch + 2 attest_batch) / {n}",
                ),
                _make_gas_row(
                    network=net,
                    chain_id=chain_id,
                    variant="D3",
                    operation="verify_inclusion_est",
                    storage_mode="view_estimate",
                    batch_size=n,
                    gas_used=vi_gas,
                    gas_per_case=vi_gas,
                    notes=f"Merkle proof length={len(proof0)}",
                ),
                _make_gas_row(
                    network=net,
                    chain_id=chain_id,
                    variant="D3",
                    operation="verify_case_inclusion_est",
                    storage_mode="view_estimate",
                    batch_size=n,
                    gas_used=vci_gas,
                    gas_per_case=vci_gas,
                    notes=f"On-chain leaf hash + Merkle proof length={len(proof0)}",
                ),
            ]
        )

    # Prepare one open case (D1/D2) and one open batch (D3) with an Approve vote from a3
    # so we can measure permissionless v1.1 `revoke_removed_auditor_vote` after removing a3.
    revoke_units: dict[str, bytes] = {}
    for variant in ("D1", "D2"):
        inst = contracts[variant]
        cid_rev = keccak(encode(["string", "string"], [f"e5-{variant}", "revoke-open"]))
        eh_rev = keccak(encode(["string", "string"], [f"ev-{variant}", "revoke-open"]))
        w3.eth.wait_for_transaction_receipt(
            inst.functions.register_case(cid_rev, subject, 1, eh_rev, mh, sample_uri).transact({"from": a1})
        )
        w3.eth.wait_for_transaction_receipt(
            inst.functions.attest(cid_rev, 1, rh).transact({"from": a3})
        )
        revoke_units[variant] = cid_rev

    rev_leaf = compute_leaf(
        keccak(b"e5-d3-revoke-case"),
        keccak(b"e5-d3-revoke-ev"),
        mh,
    )
    rev_root = MerkleTree([rev_leaf]).root
    w3.eth.wait_for_transaction_receipt(
        d3.functions.register_batch(rev_root, 1, sample_uri).transact({"from": a1})
    )
    w3.eth.wait_for_transaction_receipt(
        d3.functions.attest_batch(rev_root, 1).transact({"from": a3})
    )
    revoke_units["D3"] = rev_root

    outsider = w3.eth.accounts[4]
    for variant in ("D1", "D2", "D3"):
        rc_rem = w3.eth.wait_for_transaction_receipt(
            contracts[variant].functions.remove_auditor(a3).transact({"from": owner})
        )
        rows.append(
            _make_gas_row(
                network=net,
                chain_id=chain_id,
                variant=variant,
                operation="remove_auditor",
                storage_mode="warm_update",
                batch_size=1,
                gas_used=rc_rem.gasUsed,
                gas_per_case=rc_rem.gasUsed,
                tx_hash=_tx_hex(rc_rem.transactionHash),
                notes="Owner removes auditor a3 (auditor_count 3 -> 2)",
            )
        )
        rc_rev = w3.eth.wait_for_transaction_receipt(
            contracts[variant]
            .functions.revoke_removed_auditor_vote(revoke_units[variant], a3)
            .transact({"from": outsider})
        )
        rows.append(
            _make_gas_row(
                network=net,
                chain_id=chain_id,
                variant=variant,
                operation="revoke_removed_auditor_vote",
                storage_mode="warm_update",
                batch_size=1,
                gas_used=rc_rev.gasUsed,
                gas_per_case=rc_rev.gasUsed,
                tx_hash=_tx_hex(rc_rev.transactionHash),
                notes="Permissionless revocation of removed auditor a3 vote on open unit (v1.1)",
            )
        )

    return rows


def enrich_gas_rows_with_price_anchor(
    rows: list[dict[str, Any]],
    anchor: PriceAnchor,
) -> list[dict[str, Any]]:
    """Attach fixed-date mainnet reference cost (ETH and USD) and L2 actual USD cost."""
    enriched: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        gas_used = float(item["gas_used"])
        gas_per_case = float(item["gas_per_case"])
        ref_eth = gas_used * anchor.mainnet_median_gas_price_gwei * 1e-9
        ref_usd = compute_mainnet_usd(gas_used, anchor.mainnet_median_gas_price_gwei, anchor.eth_usd)
        ref_case_usd = compute_mainnet_usd(
            gas_per_case, anchor.mainnet_median_gas_price_gwei, anchor.eth_usd
        )
        item["mainnet_ref_gas_price_gwei"] = round(anchor.mainnet_median_gas_price_gwei, 6)
        item["mainnet_ref_eth_usd"] = round(anchor.eth_usd, 2)
        item["mainnet_ref_cost_eth"] = f"{ref_eth:.12f}"
        item["mainnet_ref_cost_usd"] = round(ref_usd, 8)
        item["mainnet_ref_cost_per_case_usd"] = round(ref_case_usd, 8)

        actual_eth_str = str(item.get("actual_fee_eth", "")).strip()
        if actual_eth_str:
            item["actual_fee_usd"] = round(float(actual_eth_str) * anchor.eth_usd, 8)
        else:
            item["actual_fee_usd"] = ""
        enriched.append(item)
    return enriched


def compute_latency_summary(rows: list[dict[str, Any]] | pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Summarize confirmation latency (seconds & blocks) and fees per network."""
    df = pd.DataFrame(rows) if not isinstance(rows, pd.DataFrame) else rows.copy()
    if df.empty:
        return {}

    summaries: dict[str, dict[str, Any]] = {}
    for net, grp in df.groupby("network", sort=False):
        secs = grp["latency_seconds"].astype(float).to_numpy()
        blocks = grp["blocks_to_confirm"].astype(float).to_numpy()
        gas_vals = grp["gas_used"].astype(float).to_numpy()
        fee_eth = grp["fee_eth"].astype(float).to_numpy()
        fee_usd = grp["fee_usd"].astype(float).to_numpy()

        med_blocks = float(np.median(blocks))
        p95_blocks = float(np.percentile(blocks, 95))
        summary: dict[str, Any] = {
            "network": str(net),
            "n_txs": int(len(grp)),
            "median_seconds": round(float(np.median(secs)), 3),
            "p95_seconds": round(float(np.percentile(secs, 95)), 3),
            "mean_seconds": round(float(np.mean(secs)), 3),
            "min_seconds": round(float(np.min(secs)), 3),
            "max_seconds": round(float(np.max(secs)), 3),
            "median_blocks": round(med_blocks, 2),
            "p95_blocks": round(p95_blocks, 2),
            "min_blocks": int(np.min(blocks)),
            "max_blocks": int(np.max(blocks)),
            "median_gas_used": round(float(np.median(gas_vals)), 1),
            "p95_gas_used": round(float(np.percentile(gas_vals, 95)), 1),
            "median_fee_eth": f"{float(np.median(fee_eth)):.12f}",
            "total_fee_eth": f"{float(np.sum(fee_eth)):.12f}",
            "median_fee_usd": round(float(np.median(fee_usd)), 8),
            "total_fee_usd": round(float(np.sum(fee_usd)), 8),
        }
        if str(net) == "sepolia":
            summary["prereg_max_median_blocks"] = PREREG_SEPOLIA_MEDIAN_BLOCKS
            summary["meets_target"] = bool(med_blocks <= PREREG_SEPOLIA_MEDIAN_BLOCKS)
        summaries[str(net)] = summary
    return summaries


def generate_gas_vs_batch_plot(
    gas_df: pd.DataFrame,
    output_path: Path,
) -> Path:
    """Plot amortized gas per case vs Merkle batch size N against D1, D2, and targets."""
    anvil = gas_df[gas_df["network"] == "anvil_pyevm"]
    d1_total = float(
        anvil[(anvil["variant"] == "D1") & (anvil["operation"] == "finalized_case_total")][
            "gas_per_case"
        ].iloc[0]
    )
    d2_total = float(
        anvil[(anvil["variant"] == "D2") & (anvil["operation"] == "finalized_case_total")][
            "gas_per_case"
        ].iloc[0]
    )
    d3_curve = anvil[
        (anvil["variant"] == "D3") & (anvil["operation"] == "batch_finalized_total")
    ].sort_values("batch_size")

    ns = d3_curve["batch_size"].astype(int).to_numpy()
    per_case = d3_curve["gas_per_case"].astype(float).to_numpy()

    fig, ax = plt.subplots(figsize=(8.2, 5.2), dpi=220)
    ax.plot(
        ns,
        per_case,
        marker="o",
        linewidth=2.4,
        markersize=8,
        color="#1f77b4",
        label="D3 (Merkle Batch): amortized gas / case",
        zorder=4,
    )

    for x_val, y_val in zip(ns, per_case):
        offset_y = 1.28 if x_val in (1, 100) else 1.22
        ax.annotate(
            f"{y_val:,.0f}" if y_val >= 1000 else f"{y_val:,.1f}",
            xy=(x_val, y_val),
            xytext=(x_val, y_val * offset_y),
            ha="center",
            va="bottom",
            fontsize=9,
            fontweight="bold",
            color="#104e8b",
        )

    ax.axhline(
        d1_total,
        color="#d62728",
        linestyle="-",
        linewidth=1.8,
        label=f"D1 (Full Storage) finalized case = {d1_total:,.0f} gas",
    )
    ax.axhline(
        d2_total,
        color="#ff7f0e",
        linestyle="-.",
        linewidth=1.8,
        label=f"D2 (Event-Only) finalized case = {d2_total:,.0f} gas",
    )
    ax.axhline(
        PREREG_D1_MAX_GAS,
        color="#8c564b",
        linestyle="--",
        linewidth=1.4,
        label=f"Pre-reg D1 ceiling = {PREREG_D1_MAX_GAS:,} gas",
    )
    ax.axhline(
        PREREG_D3_AMORTIZED_MAX_GAS,
        color="#2ca02c",
        linestyle=":",
        linewidth=2.0,
        label=f"Pre-reg D3 target (N >= 100) = {PREREG_D3_AMORTIZED_MAX_GAS:,} gas/case",
    )

    ax.axvspan(100, 1400, color="#2ca02c", alpha=0.07)
    ax.text(
        320,
        PREREG_D3_AMORTIZED_MAX_GAS * 0.62,
        "Target Zone (N >= 100)",
        fontsize=8.5,
        color="#1e7b1e",
        ha="center",
    )

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xticks(ns)
    ax.set_xticklabels([str(x) for x in ns])
    ax.set_xlim(0.7, 1500)
    ax.set_ylim(180, max(d1_total * 2.2, 900_000))
    ax.grid(True, which="both", linestyle="--", alpha=0.35)
    ax.set_xlabel("Merkle Batch Size N (cases per root)", fontsize=10.5)
    ax.set_ylabel("Amortized Gas per Finalized Case (log scale)", fontsize=10.5)
    ax.set_title(
        "E5 Gas Scaling: D3 Merkle Batch vs D1 Full Storage & D2 Event-Only (k = 2)",
        fontsize=11.5,
        fontweight="bold",
        pad=10,
    )
    ax.legend(loc="lower left", fontsize=8.3, framealpha=0.94)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    if output_path.suffix.lower() == ".pdf":
        with plt.rc_context({"pdf.fonttype": 42, "ps.fonttype": 42}):
            fig.savefig(output_path, bbox_inches="tight")
    else:
        fig.savefig(output_path, dpi=220)
    plt.close(fig)
    return output_path
