"""Execute Phase 7 (Experiment E5): Anvil/Sepolia/Arbitrum Sepolia gas, cost, latency & security benchmarks."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from eth_abi import encode
from eth_account import Account
from eth_utils import keccak
from web3 import Web3
from web3.exceptions import TransactionNotFound

from src.contracts.compiler import compile_contract
from src.contracts.e5_benchmark import (
    PriceAnchor,
    compute_latency_summary,
    enrich_gas_rows_with_price_anchor,
    fetch_mainnet_price_anchor,
    generate_gas_vs_batch_plot,
    run_anvil_gas_suite,
)
from src.contracts.merkle import MerkleTree, compute_leaf
from src.evidence.canonical import verify_evidence_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENTS_PATH = REPO_ROOT / "deployments.json"
RESULTS_DIR = REPO_ROOT / "results"
FIGURES_DIR = REPO_ROOT / "figures"
EVIDENCE_DIR = REPO_ROOT / "evidence"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

EXPECTED_CHAIN_IDS: dict[str, int] = {
    "sepolia": 11155111,
    "arbitrum-sepolia": 421614,
}
_LAST_MINED_BLOCK: dict[str, int] = {}


@dataclass
class EphemeralWallet:
    """In-memory ephemeral testnet account (never persisted to disk)."""

    label: str
    address: str
    private_key: str
    nonce: int = 0


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:
        return "unknown"


def _tx_hex(raw: Any) -> str:
    h = raw.hex() if hasattr(raw, "hex") else str(raw)
    return h if h.startswith("0x") else f"0x{h}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _connect_live(network: str) -> tuple[Web3, EphemeralWallet]:
    load_dotenv(REPO_ROOT / ".env")
    if network == "sepolia":
        rpc_url = os.environ.get("SEPOLIA_RPC_URL", "").strip()
        pk = os.environ.get("SEPOLIA_DEPLOYER_PRIVATE_KEY", "").strip()
    elif network == "arbitrum-sepolia":
        rpc_url = os.environ.get("L2_RPC_URL", "").strip()
        pk = os.environ.get("L2_DEPLOYER_PRIVATE_KEY", "").strip()
    else:
        raise ValueError(f"Unsupported live network: {network}")

    if not rpc_url or not pk:
        raise RuntimeError(f"Missing RPC URL or deployer private key for {network} in .env")

    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 20}))
    if not w3.is_connected():
        raise ConnectionError(f"Cannot connect to {network} RPC")
    actual_cid = int(w3.eth.chain_id)
    if actual_cid != EXPECTED_CHAIN_IDS[network]:
        raise RuntimeError(f"Expected chain_id {EXPECTED_CHAIN_IDS[network]}, got {actual_cid}")

    addr = Account.from_key(pk).address
    nonce = int(w3.eth.get_transaction_count(addr, block_identifier="pending"))
    return w3, EphemeralWallet(label=f"{network}_deployer", address=addr, private_key=pk, nonce=nonce)


def _compute_eip1559_fees(
    w3: Web3,
    network: str,
    *,
    priority_gwei: float | None = None,
) -> tuple[int, int]:
    latest = w3.eth.get_block("latest")
    base_fee = int(latest.get("baseFeePerGas", w3.eth.gas_price))
    if network == "sepolia":
        prio_wei = w3.to_wei(priority_gwei if priority_gwei is not None else 0.15, "gwei")
        max_fee = max(base_fee * 2 + prio_wei, prio_wei * 2)
        return max_fee, prio_wei
    # Arbitrum Sepolia uses L2 base fee with zero priority fee.
    gas_price = int(w3.eth.gas_price)
    max_fee = int(max(base_fee * 2, gas_price * 1.5, w3.to_wei(0.05, "gwei")))
    return max_fee, 0


def _wait_for_receipt(
    w3: Web3,
    tx_hash: Any,
    *,
    poll_interval: float,
    timeout_s: float = 180.0,
) -> tuple[dict[str, Any], float, str]:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        try:
            rc = w3.eth.get_transaction_receipt(tx_hash)
            if rc is not None:
                return dict(rc), time.perf_counter(), _utc_now()
        except TransactionNotFound:
            pass
        except Exception:
            pass
        time.sleep(poll_interval)
    raise TimeoutError(f"Timed out waiting {timeout_s}s for receipt {_tx_hex(tx_hash)}")


def _ensure_rpc_synced(
    w3: Web3,
    network: str,
    *,
    contract_address: str | None = None,
    timeout_s: float = 20.0,
) -> None:
    """Wait until load-balanced RPC node catches up to last mined block and sees contract code."""
    target_blk = _LAST_MINED_BLOCK.get(network, 0)
    poll_s = 0.5 if network == "sepolia" else 0.25
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        try:
            head = int(w3.eth.block_number)
            code_ok = True if not contract_address else len(w3.eth.get_code(contract_address)) > 0
            if head >= target_blk and code_ok:
                return
        except Exception:
            pass
        time.sleep(poll_s)


def _send_signed_tx(
    w3: Web3,
    network: str,
    wallet: EphemeralWallet,
    fn_or_tx: Any,
    *,
    expect_revert: bool = False,
    explicit_gas: int | None = None,
    priority_gwei: float | None = None,
    gas_multiplier: float = 1.25,
) -> dict[str, Any]:
    """Sign and broadcast an EIP-1559 transaction, measuring confirmation latency."""
    poll_s = 0.5 if network == "sepolia" else 0.2
    contract_addr = getattr(fn_or_tx, "address", None)
    _ensure_rpc_synced(w3, network, contract_address=contract_addr)

    max_fee, max_prio = _compute_eip1559_fees(w3, network, priority_gwei=priority_gwei)
    revert_reason = ""

    if expect_revert and hasattr(fn_or_tx, "call"):
        try:
            fn_or_tx.call({"from": wallet.address})
            raise AssertionError("Expected eth_call revert, but call succeeded")
        except AssertionError:
            raise
        except Exception as exc:
            revert_reason = str(exc)

    tx_params: dict[str, Any] = {
        "from": wallet.address,
        "nonce": wallet.nonce,
        "chainId": EXPECTED_CHAIN_IDS[network],
        "maxFeePerGas": max_fee,
        "maxPriorityFeePerGas": max_prio,
    }
    if explicit_gas is not None:
        tx_params["gas"] = int(explicit_gas)

    if hasattr(fn_or_tx, "build_transaction"):
        if "gas" not in tx_params:
            est = 0
            last_err: Exception | None = None
            for _ in range(10):
                try:
                    est = int(fn_or_tx.estimate_gas({"from": wallet.address}))
                    # Mutating calls to a deployed contract must exceed bare EOA transfer (~21k).
                    if contract_addr and est < 23_000:
                        time.sleep(poll_s)
                        continue
                    last_err = None
                    break
                except Exception as exc:
                    last_err = exc
                    time.sleep(poll_s)
            if last_err is not None or (contract_addr and est < 23_000):
                raise RuntimeError(f"estimate_gas failed after retries (est={est}): {last_err}")
            tx_params["gas"] = max(int(est * gas_multiplier), est + 25_000)
        tx = fn_or_tx.build_transaction(tx_params)
    else:
        tx = dict(fn_or_tx)
        tx.update(tx_params)
        if "gas" not in tx:
            est = int(w3.eth.estimate_gas(tx))
            tx["gas"] = max(int(est * gas_multiplier), est + 10_000)

    signed = Account.sign_transaction(tx, wallet.private_key)
    block_at_submit = int(w3.eth.block_number)
    t_submit = time.perf_counter()
    submit_utc = _utc_now()
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt, t_confirm, confirm_utc = _wait_for_receipt(w3, tx_hash, poll_interval=poll_s)
    wallet.nonce += 1

    status = int(receipt["status"])
    block_mined = int(receipt["blockNumber"])
    _LAST_MINED_BLOCK[network] = max(_LAST_MINED_BLOCK.get(network, 0), block_mined)
    if expect_revert and status != 0:
        raise AssertionError(f"Expected on-chain revert (status=0) for {_tx_hex(tx_hash)}, got status={status}")
    if not expect_revert and status != 1:
        raise RuntimeError(f"Transaction failed on-chain (status={status}): {_tx_hex(tx_hash)}")

    gas_used = int(receipt["gasUsed"])
    eff_price = int(receipt.get("effectiveGasPrice", 0))
    fee_wei = gas_used * eff_price
    raw_l1 = receipt.get("gasUsedForL1", 0)
    l1_gas = int(raw_l1, 16) if isinstance(raw_l1, str) else int(raw_l1 or 0)

    return {
        "tx_hash": _tx_hex(receipt["transactionHash"]),
        "status": status,
        "contract_address": receipt.get("contractAddress"),
        "block_at_submit": block_at_submit,
        "block_mined": block_mined,
        "raw_block_delta": block_mined - block_at_submit,
        "blocks_to_confirm": max(0, block_mined - block_at_submit),
        "submit_utc": submit_utc,
        "confirm_utc": confirm_utc,
        "latency_seconds": round(t_confirm - t_submit, 4),
        "gas_used": gas_used,
        "effective_gas_price_wei": eff_price,
        "gas_used_for_l1": l1_gas,
        "fee_wei": fee_wei,
        "fee_eth": fee_wei / 1e18,
        "revert_reason": revert_reason,
    }


def _create_ephemeral_wallet(label: str) -> EphemeralWallet:
    acct = Account.create()
    return EphemeralWallet(label=label, address=acct.address, private_key=acct.key.hex(), nonce=0)


def _fund_wallet(
    w3: Web3,
    network: str,
    funder: EphemeralWallet,
    target: EphemeralWallet,
    amount_eth: float,
) -> dict[str, Any]:
    val_wei = w3.to_wei(amount_eth, "ether")
    return _send_signed_tx(
        w3,
        network,
        funder,
        {"to": target.address, "value": val_wei},
        priority_gwei=0.1 if network == "sepolia" else None,
    )


def _sweep_wallet(w3: Web3, network: str, src: EphemeralWallet, dst_address: str) -> str | None:
    try:
        bal = int(w3.eth.get_balance(src.address))
        if bal == 0:
            return None
        max_fee, max_prio = _compute_eip1559_fees(w3, network, priority_gwei=0.05 if network == "sepolia" else None)
        est = int(w3.eth.estimate_gas({"from": src.address, "to": dst_address, "value": 1}))
        gas_limit = max(int(est * 1.2), est + 5000)
        reserve = gas_limit * max_fee
        if bal <= reserve:
            return None
        src.nonce = int(w3.eth.get_transaction_count(src.address, block_identifier="pending"))
        tx = {
            "from": src.address,
            "to": dst_address,
            "value": bal - reserve,
            "nonce": src.nonce,
            "chainId": EXPECTED_CHAIN_IDS[network],
            "gas": gas_limit,
            "maxFeePerGas": max_fee,
            "maxPriorityFeePerGas": max_prio,
        }
        signed = Account.sign_transaction(tx, src.private_key)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        _wait_for_receipt(w3, tx_hash, poll_interval=0.5 if network == "sepolia" else 0.2, timeout_s=90.0)
        return _tx_hex(tx_hash)
    except Exception:
        return None


def _deploy_benchmark_suite(
    w3: Web3,
    network: str,
    deployer: EphemeralWallet,
    auditors: list[EphemeralWallet],
    variants: tuple[str, ...],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Deploy dedicated E5 benchmark contracts and configure 3 ephemeral auditors (k=2)."""
    instances: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    gas_rows: list[dict[str, Any]] = []
    chain_id = EXPECTED_CHAIN_IDS[network]
    prio = 0.1 if network == "sepolia" else None

    for variant in variants:
        compiled = compile_contract(variant, use_cache=True)
        factory = w3.eth.contract(abi=compiled.abi, bytecode=compiled.bytecode)
        rc_dep = _send_signed_tx(
            w3,
            network,
            deployer,
            factory.constructor(ZERO_ADDRESS),
            priority_gwei=prio,
        )
        addr = rc_dep["contract_address"]
        inst = w3.eth.contract(address=addr, abi=compiled.abi)
        instances[variant] = inst
        gas_rows.append(
            {
                "network": network,
                "chain_id": chain_id,
                "variant": variant,
                "operation": "deploy",
                "storage_mode": "deployment",
                "batch_size": 1,
                "gas_used": rc_dep["gas_used"],
                "gas_per_case": rc_dep["gas_used"],
                "prereg_target_gas": "",
                "meets_target": "",
                "effective_gas_price_wei": rc_dep["effective_gas_price_wei"],
                "actual_fee_eth": f"{rc_dep['fee_eth']:.12f}",
                "tx_hash": rc_dep["tx_hash"],
                "notes": f"Dedicated E5 benchmark contract ({addr}); L1_gas={rc_dep['gas_used_for_l1']}",
            }
        )

        setup_hashes: list[str] = []
        for idx, aud in enumerate(auditors):
            rc_add = _send_signed_tx(
                w3,
                network,
                deployer,
                inst.functions.add_auditor(aud.address),
                priority_gwei=prio,
            )
            setup_hashes.append(rc_add["tx_hash"])
            gas_rows.append(
                {
                    "network": network,
                    "chain_id": chain_id,
                    "variant": variant,
                    "operation": "add_auditor_cold_first" if idx == 0 else f"add_auditor_{idx + 1}",
                    "storage_mode": "cold_first_write" if idx == 0 else "cold_mapping_warm_count",
                    "batch_size": 1,
                    "gas_used": rc_add["gas_used"],
                    "gas_per_case": rc_add["gas_used"],
                    "prereg_target_gas": "",
                    "meets_target": "",
                    "effective_gas_price_wei": rc_add["effective_gas_price_wei"],
                    "actual_fee_eth": f"{rc_add['fee_eth']:.12f}",
                    "tx_hash": rc_add["tx_hash"],
                    "notes": f"Benchmark auditor {idx + 1}; L1_gas={rc_add['gas_used_for_l1']}",
                }
            )

        rc_k = _send_signed_tx(
            w3,
            network,
            deployer,
            inst.functions.set_threshold(2),
            priority_gwei=prio,
        )
        gas_rows.append(
            {
                "network": network,
                "chain_id": chain_id,
                "variant": variant,
                "operation": "set_threshold",
                "storage_mode": "warm_update",
                "batch_size": 1,
                "gas_used": rc_k["gas_used"],
                "gas_per_case": rc_k["gas_used"],
                "prereg_target_gas": "",
                "meets_target": "",
                "effective_gas_price_wei": rc_k["effective_gas_price_wei"],
                "actual_fee_eth": f"{rc_k['fee_eth']:.12f}",
                "tx_hash": rc_k["tx_hash"],
                "notes": f"threshold=2; L1_gas={rc_k['gas_used_for_l1']}",
            }
        )

        meta[variant] = {
            "address": addr,
            "deploy_tx_hash": rc_dep["tx_hash"],
            "deploy_gas_used": rc_dep["gas_used"],
            "auditors": [a.address for a in auditors],
            "add_auditor_txs": setup_hashes,
            "set_threshold_tx": rc_k["tx_hash"],
        }

    return instances, meta, gas_rows


def _run_sepolia_t1_t6_on_main_d1(
    w3: Web3,
    deployer: EphemeralWallet,
    non_auditor: EphemeralWallet,
    main_d1_addr: str,
) -> dict[str, Any]:
    """Execute T1 (non-auditor) and T6 (owner) on-chain revert proofs on main verified Sepolia D1."""
    d1_abi = compile_contract("D1", use_cache=True).abi
    main_d1 = w3.eth.contract(address=main_d1_addr, abi=d1_abi)

    # ABI immutability check: ensure zero admin edit/delete endpoints exist.
    fn_names = sorted(
        item["name"] for item in d1_abi if item.get("type") == "function"
    )
    forbidden = [
        nm
        for nm in fn_names
        if any(tok in nm.lower() for tok in ("edit", "update", "delete", "remove_case", "revoke", "overwrite"))
    ]
    assert not forbidden, f"Unexpected mutable/delete functions in ABI: {forbidden}"

    before_count = int(main_d1.functions.auditor_count().call())
    before_thresh = int(main_d1.functions.threshold().call())
    deploy_block = int(
        json.loads(DEPLOYMENTS_PATH.read_text(encoding="utf-8"))["networks"]["sepolia"]["contracts"]["D1"][
            "block_number"
        ]
    )
    head_safe = max(deploy_block, int(w3.eth.block_number) - 1)
    before_cases = len(
        main_d1.events.CaseRegistered().get_logs(from_block=deploy_block, to_block=head_safe)
    )

    dummy_cid = keccak(b"phase7-sepolia-revert-proof-case")
    dummy_eh = keccak(b"phase7-sepolia-revert-proof-ev")
    dummy_mh = keccak(b"phase7-sepolia-revert-proof-model")
    dummy_rh = keccak(b"phase7-sepolia-revert-proof-reason")
    dummy_subj = Web3.to_checksum_address("0x2c2e3baa2191cf325a28a01ff42340f2ae677572")

    # T6a: Owner attempts register_case (role separation -> revert "Only auditor")
    t6_reg = _send_signed_tx(
        w3,
        "sepolia",
        deployer,
        main_d1.functions.register_case(dummy_cid, dummy_subj, 1, dummy_eh, dummy_mh, "ipfs://t6-owner"),
        expect_revert=True,
        explicit_gas=150_000,
        priority_gwei=0.15,
    )
    # T6b: Owner attempts attest (role separation -> revert "Only auditor")
    t6_att = _send_signed_tx(
        w3,
        "sepolia",
        deployer,
        main_d1.functions.attest(dummy_cid, 1, dummy_rh),
        expect_revert=True,
        explicit_gas=150_000,
        priority_gwei=0.15,
    )
    # T6c: Owner attempts add_auditor(owner) (disjointness -> revert "Owner cannot be auditor")
    t6_add = _send_signed_tx(
        w3,
        "sepolia",
        deployer,
        main_d1.functions.add_auditor(deployer.address),
        expect_revert=True,
        explicit_gas=150_000,
        priority_gwei=0.15,
    )
    # T1a: Non-auditor attempts register_case (-> revert "Only auditor")
    t1_reg = _send_signed_tx(
        w3,
        "sepolia",
        non_auditor,
        main_d1.functions.register_case(dummy_cid, dummy_subj, 1, dummy_eh, dummy_mh, "ipfs://t1-nonaud"),
        expect_revert=True,
        explicit_gas=150_000,
        priority_gwei=0.15,
    )
    # T1b: Non-auditor attempts attest (-> revert "Only auditor")
    t1_att = _send_signed_tx(
        w3,
        "sepolia",
        non_auditor,
        main_d1.functions.attest(dummy_cid, 1, dummy_rh),
        expect_revert=True,
        explicit_gas=150_000,
        priority_gwei=0.15,
    )

    after_count = int(main_d1.functions.auditor_count().call())
    after_thresh = int(main_d1.functions.threshold().call())
    head_after = max(deploy_block, int(w3.eth.block_number) - 1)
    after_cases = len(
        main_d1.events.CaseRegistered().get_logs(from_block=deploy_block, to_block=head_after)
    )
    assert before_count == after_count == 3
    assert before_thresh == after_thresh == 2
    assert before_cases == after_cases

    return {
        "main_d1_address": main_d1_addr,
        "abi_functions": fn_names,
        "state_unchanged_verified": True,
        "auditor_count": after_count,
        "threshold": after_thresh,
        "case_registered_count": after_cases,
        "T1_non_auditor_register_revert": {
            "sender": non_auditor.address,
            "tx_hash": t1_reg["tx_hash"],
            "block_number": t1_reg["block_mined"],
            "status": t1_reg["status"],
            "gas_used": t1_reg["gas_used"],
            "eth_call_revert": t1_reg["revert_reason"],
        },
        "T1_non_auditor_attest_revert": {
            "sender": non_auditor.address,
            "tx_hash": t1_att["tx_hash"],
            "block_number": t1_att["block_mined"],
            "status": t1_att["status"],
            "gas_used": t1_att["gas_used"],
            "eth_call_revert": t1_att["revert_reason"],
        },
        "T6_owner_register_revert": {
            "sender": deployer.address,
            "tx_hash": t6_reg["tx_hash"],
            "block_number": t6_reg["block_mined"],
            "status": t6_reg["status"],
            "gas_used": t6_reg["gas_used"],
            "eth_call_revert": t6_reg["revert_reason"],
        },
        "T6_owner_attest_revert": {
            "sender": deployer.address,
            "tx_hash": t6_att["tx_hash"],
            "block_number": t6_att["block_mined"],
            "status": t6_att["status"],
            "gas_used": t6_att["gas_used"],
            "eth_call_revert": t6_att["revert_reason"],
        },
        "T6_owner_add_self_revert": {
            "sender": deployer.address,
            "tx_hash": t6_add["tx_hash"],
            "block_number": t6_add["block_mined"],
            "status": t6_add["status"],
            "gas_used": t6_add["gas_used"],
            "eth_call_revert": t6_add["revert_reason"],
        },
    }


def _spot_check_and_latency_network(
    w3: Web3,
    network: str,
    instances: dict[str, Any],
    auditors: list[EphemeralWallet],
    *,
    eth_usd: float,
    latency_txs: int = 30,
    run_t8: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Run D1/D2/D3 gas spot-checks, optional T8 check, and 30 sequential attest latency txs."""
    chain_id = EXPECTED_CHAIN_IDS[network]
    gas_rows: list[dict[str, Any]] = []
    latency_rows: list[dict[str, Any]] = []
    extra_evidence: dict[str, Any] = {}

    sample_uri = "ipfs://bafkreiemixow7szs3zagtzfbx5vyp4l3yb2xd7zfckxwfko46i3hwu64hy"
    mh = keccak(b"e5-live-model-v1")
    rh = keccak(b"e5-live-reason")
    subj = Web3.to_checksum_address("0x2c2e3baa2191cf325a28a01ff42340f2ae677572")
    spot_prio = 0.2 if network == "sepolia" else None

    # Load real Phase 6 canonical JSON evidence for T8 if available
    ev_files = sorted(p for p in EVIDENCE_DIR.glob("0x*.json"))
    if run_t8 and ev_files:
        ev_raw = ev_files[0].read_bytes()
        ev_obj = json.loads(ev_raw.decode("utf-8"))
        cid_t8 = bytes.fromhex(ev_files[0].stem[2:])
        eh_t8 = keccak(ev_raw)
        mh_t8 = bytes.fromhex(ev_obj["model_version_hash"][2:])
        subj_t8 = Web3.to_checksum_address(ev_obj["subject_address"])
        uri_t8 = sample_uri
    else:
        cid_t8 = keccak(encode(["string", "string"], [network, "spot-d1"]))
        eh_t8 = keccak(b"spot-evidence-d1")
        mh_t8 = mh
        subj_t8 = subj
        uri_t8 = sample_uri
        ev_raw = b'{"sample":"fallback"}'

    # Spot-check D1 (+ D2 on Sepolia)
    for variant in [v for v in ("D1", "D2") if v in instances]:
        inst = instances[variant]
        cid = cid_t8 if variant == "D1" else keccak(encode(["string", "string"], [network, f"spot-{variant}"]))
        eh = eh_t8 if variant == "D1" else keccak(b"spot-evidence-d2")
        m_hash = mh_t8 if variant == "D1" else mh
        sub_addr = subj_t8 if variant == "D1" else subj

        rc_reg = _send_signed_tx(
            w3,
            network,
            auditors[0],
            inst.functions.register_case(cid, sub_addr, 1, eh, m_hash, uri_t8),
            priority_gwei=spot_prio,
        )
        rc_a1 = _send_signed_tx(
            w3,
            network,
            auditors[0],
            inst.functions.attest(cid, 1, rh),
            priority_gwei=spot_prio,
        )
        rc_a2 = _send_signed_tx(
            w3,
            network,
            auditors[1],
            inst.functions.attest(cid, 1, rh),
            priority_gwei=spot_prio,
        )
        rc_rep = _send_signed_tx(
            w3,
            network,
            auditors[0],
            inst.functions.attest(cid, 2, rh),
            priority_gwei=spot_prio,
        )

        tot_gas = rc_reg["gas_used"] + rc_a1["gas_used"] + rc_a2["gas_used"]
        tot_eth = rc_reg["fee_eth"] + rc_a1["fee_eth"] + rc_a2["fee_eth"]
        for op_nm, mode, rc_item in (
            ("register_case", "cold_first_write", rc_reg),
            ("attest_cold_1_open", "cold_first_write", rc_a1),
            ("attest_cold_2_finalize", "cold_first_write", rc_a2),
            ("attest_warm_replace", "warm_update", rc_rep),
        ):
            gas_rows.append(
                {
                    "network": network,
                    "chain_id": chain_id,
                    "variant": variant,
                    "operation": op_nm,
                    "storage_mode": mode,
                    "batch_size": 1,
                    "gas_used": rc_item["gas_used"],
                    "gas_per_case": rc_item["gas_used"],
                    "prereg_target_gas": "",
                    "meets_target": "",
                    "effective_gas_price_wei": rc_item["effective_gas_price_wei"],
                    "actual_fee_eth": f"{rc_item['fee_eth']:.12f}",
                    "tx_hash": rc_item["tx_hash"],
                    "notes": f"Live spot-check; L1_gas={rc_item['gas_used_for_l1']}",
                }
            )
        gas_rows.append(
            {
                "network": network,
                "chain_id": chain_id,
                "variant": variant,
                "operation": "finalized_case_total",
                "storage_mode": "aggregate",
                "batch_size": 1,
                "gas_used": tot_gas,
                "gas_per_case": tot_gas,
                "prereg_target_gas": 250_000 if variant == "D1" else "",
                "meets_target": (tot_gas <= 250_000) if variant == "D1" else "",
                "effective_gas_price_wei": rc_a2["effective_gas_price_wei"],
                "actual_fee_eth": f"{tot_eth:.12f}",
                "tx_hash": rc_a2["tx_hash"],
                "notes": f"Live sum (reg+att1+att2); reg_tx={rc_reg['tx_hash']}",
            }
        )

        if run_t8 and variant == "D1":
            tampered_obj = dict(json.loads(ev_raw.decode("utf-8")))
            old_score = str(tampered_obj["score"])
            new_last = "2" if old_score[-1] != "2" else "3"
            tampered_obj["score"] = old_score[:-1] + new_last
            from src.evidence.canonical import canonical_bytes

            tampered_bytes = canonical_bytes(tampered_obj)
            assert len(tampered_bytes) == len(ev_raw)
            assert sum(a != b for a, b in zip(ev_raw, tampered_bytes)) == 1
            tampered_hash = keccak(tampered_bytes)
            ok_local, _ = verify_evidence_payload(
                ev_raw,
                "0x" + eh.hex(),
                expected_case_id_hex="0x" + cid.hex(),
                expected_subject=sub_addr,
                expected_subject_chain_id=1,
                expected_model_version_hash_hex="0x" + m_hash.hex(),
            )
            bad_local, _ = verify_evidence_payload(
                tampered_bytes,
                "0x" + eh.hex(),
                expected_case_id_hex="0x" + cid.hex(),
                expected_subject=sub_addr,
                expected_subject_chain_id=1,
                expected_model_version_hash_hex="0x" + m_hash.hex(),
            )
            _ensure_rpc_synced(w3, network, contract_address=inst.address)
            ok_chain = False
            for _ in range(5):
                ok_chain = bool(inst.functions.verify_evidence(cid, eh).call())
                if ok_chain:
                    break
                time.sleep(0.5)
            bad_chain = bool(inst.functions.verify_evidence(cid, tampered_hash).call())
            assert ok_local and ok_chain and (not bad_local) and (not bad_chain)
            extra_evidence["T8_sepolia_verify_evidence"] = {
                "contract_address": inst.address,
                "case_id": "0x" + cid.hex(),
                "register_tx_hash": rc_reg["tx_hash"],
                "exact_evidence_hash": "0x" + eh.hex(),
                "tampered_1byte_hash": "0x" + tampered_hash.hex(),
                "verify_exact_onchain": ok_chain,
                "verify_tampered_onchain": bad_chain,
            }

    # Spot-check D3 (N = 100)
    if "D3" in instances:
        d3 = instances["D3"]
        n_batch = 100
        leaves = [
            compute_leaf(
                keccak(encode(["string", "uint256"], [f"{network}-d3", i])),
                keccak(encode(["string", "uint256"], ["ev", i])),
                mh,
            )
            for i in range(n_batch)
        ]
        tree = MerkleTree(leaves)
        rc_rb = _send_signed_tx(
            w3,
            network,
            auditors[0],
            d3.functions.register_batch(tree.root, n_batch, sample_uri),
            priority_gwei=spot_prio,
        )
        rc_ab1 = _send_signed_tx(
            w3,
            network,
            auditors[0],
            d3.functions.attest_batch(tree.root, 1),
            priority_gwei=spot_prio,
        )
        rc_ab2 = _send_signed_tx(
            w3,
            network,
            auditors[1],
            d3.functions.attest_batch(tree.root, 1),
            priority_gwei=spot_prio,
        )
        proof0 = tree.get_proof(0)
        _ensure_rpc_synced(w3, network, contract_address=d3.address)
        incl_ok = False
        for _ in range(5):
            incl_ok = bool(d3.functions.verify_inclusion(leaves[0], proof0, tree.root).call())
            if incl_ok:
                break
            time.sleep(0.5)
        assert incl_ok
        tot_b = rc_rb["gas_used"] + rc_ab1["gas_used"] + rc_ab2["gas_used"]
        tot_b_eth = rc_rb["fee_eth"] + rc_ab1["fee_eth"] + rc_ab2["fee_eth"]
        for op_nm, rc_item in (
            ("register_batch", rc_rb),
            ("attest_batch_1_open", rc_ab1),
            ("attest_batch_2_finalize", rc_ab2),
        ):
            gas_rows.append(
                {
                    "network": network,
                    "chain_id": chain_id,
                    "variant": "D3",
                    "operation": op_nm,
                    "storage_mode": "cold_first_write",
                    "batch_size": n_batch,
                    "gas_used": rc_item["gas_used"],
                    "gas_per_case": rc_item["gas_used"] / float(n_batch),
                    "prereg_target_gas": "",
                    "meets_target": "",
                    "effective_gas_price_wei": rc_item["effective_gas_price_wei"],
                    "actual_fee_eth": f"{rc_item['fee_eth']:.12f}",
                    "tx_hash": rc_item["tx_hash"],
                    "notes": f"Live N={n_batch} spot-check; L1_gas={rc_item['gas_used_for_l1']}",
                }
            )
        gas_rows.append(
            {
                "network": network,
                "chain_id": chain_id,
                "variant": "D3",
                "operation": "batch_finalized_total",
                "storage_mode": "aggregate",
                "batch_size": n_batch,
                "gas_used": tot_b,
                "gas_per_case": tot_b / float(n_batch),
                "prereg_target_gas": 10_000,
                "meets_target": (tot_b / float(n_batch)) <= 10_000,
                "effective_gas_price_wei": rc_ab2["effective_gas_price_wei"],
                "actual_fee_eth": f"{tot_b_eth:.12f}",
                "tx_hash": rc_ab2["tx_hash"],
                "notes": f"Live amortized N={n_batch}; reg_tx={rc_rb['tx_hash']}",
            }
        )

    # Latency benchmark: 30 sequential `attest` transactions on D1 (15 cold + 15 warm across 5 cases x 3 auditors)
    d1 = instances["D1"]
    n_cases = 5
    case_ids = [
        keccak(encode(["string", "string", "uint256"], [network, "latency-case", idx]))
        for idx in range(n_cases)
    ]
    for idx, cid in enumerate(case_ids):
        _send_signed_tx(
            w3,
            network,
            auditors[0],
            d1.functions.register_case(cid, subj, 1, keccak(f"lat-ev-{idx}".encode()), mh, sample_uri),
            priority_gwei=spot_prio,
        )

    lat_prio = 0.5 if network == "sepolia" else None
    schedule: list[tuple[int, str, bytes, EphemeralWallet]] = []
    # Round 1 (15 cold attestations): 5 cases x 3 auditors
    # Round 2 (15 warm replacement attestations): 5 cases x 3 auditors
    for decision_val, mode_label in ((1, "cold_first_write"), (3, "warm_update")):
        for cid in case_ids:
            for aud in auditors:
                schedule.append((decision_val, mode_label, cid, aud))

    for tx_counter, (decision_val, mode_label, cid, aud) in enumerate(schedule[:latency_txs], start=1):
        rc_lat = _send_signed_tx(
            w3,
            network,
            aud,
            d1.functions.attest(cid, decision_val, rh),
            priority_gwei=lat_prio,
        )
        latency_rows.append(
            {
                "network": network,
                "chain_id": chain_id,
                "tx_index": tx_counter,
                "variant": "D1",
                "contract_address": d1.address,
                "case_id": "0x" + cid.hex(),
                "auditor": aud.address,
                "decision": decision_val,
                "write_type": mode_label,
                "tx_hash": rc_lat["tx_hash"],
                "submit_utc": rc_lat["submit_utc"],
                "confirm_utc": rc_lat["confirm_utc"],
                "block_at_submit": rc_lat["block_at_submit"],
                "block_mined": rc_lat["block_mined"],
                "raw_block_delta": rc_lat["raw_block_delta"],
                "blocks_to_confirm": rc_lat["blocks_to_confirm"],
                "latency_seconds": rc_lat["latency_seconds"],
                "gas_used": rc_lat["gas_used"],
                "effective_gas_price_wei": rc_lat["effective_gas_price_wei"],
                "gas_used_for_l1": rc_lat["gas_used_for_l1"],
                "fee_eth": f"{rc_lat['fee_eth']:.12f}",
                "fee_usd": round(rc_lat["fee_eth"] * eth_usd, 8),
                "status": rc_lat["status"],
            }
        )
        print(
            f"[{network}] attest {tx_counter}/{min(latency_txs, len(schedule))} "
            f"({mode_label}) blocks={rc_lat['blocks_to_confirm']} "
            f"time={rc_lat['latency_seconds']:.2f}s gas={rc_lat['gas_used']}",
            flush=True,
        )

    return gas_rows, latency_rows, extra_evidence


def run_phase7(
    *,
    skip_live: bool = False,
    latency_txs: int = 30,
) -> dict[str, Any]:
    """Run full Phase 7 E5 benchmark suite and save CSVs, plot, and JSON summary."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    print("1/4 Running deterministic Anvil (PyEVM) gas suite...", flush=True)
    all_gas_rows = run_anvil_gas_suite()

    print("2/4 Fetching Ethereum mainnet median gas price & ETH/USD anchor...", flush=True)
    load_dotenv(REPO_ROOT / ".env")
    anchor = fetch_mainnet_price_anchor()
    print(
        f"    Anchor: {anchor.mainnet_median_gas_price_gwei:.6f} gwei ({anchor.mainnet_block_range}), "
        f"ETH=${anchor.eth_usd:.2f}",
        flush=True,
    )

    all_latency_rows: list[dict[str, Any]] = []
    live_meta: dict[str, Any] = {}

    if not skip_live:
        deployments = json.loads(DEPLOYMENTS_PATH.read_text(encoding="utf-8"))
        main_sep_d1 = deployments["networks"]["sepolia"]["contracts"]["D1"]["address"]

        # --- Sepolia ---
        print("3/4 Running Sepolia T1/T6 on main D1 + benchmark suite + 30 attest txs...", flush=True)
        w3_sep, sep_deployer = _connect_live("sepolia")
        sep_non_aud = _create_ephemeral_wallet("sep_non_auditor")
        sep_auds = [_create_ephemeral_wallet(f"sep_bench_aud_{i}") for i in (1, 2, 3)]
        try:
            _fund_wallet(w3_sep, "sepolia", sep_deployer, sep_non_aud, 0.0005)
            t1_t6_evidence = _run_sepolia_t1_t6_on_main_d1(
                w3_sep, sep_deployer, sep_non_aud, main_sep_d1
            )
            sep_insts, sep_bench_meta, sep_setup_rows = _deploy_benchmark_suite(
                w3_sep, "sepolia", sep_deployer, sep_auds, ("D1", "D2", "D3")
            )
            _fund_wallet(w3_sep, "sepolia", sep_deployer, sep_auds[0], 0.008)
            _fund_wallet(w3_sep, "sepolia", sep_deployer, sep_auds[1], 0.004)
            _fund_wallet(w3_sep, "sepolia", sep_deployer, sep_auds[2], 0.004)
            sep_gas_rows, sep_lat_rows, sep_extra = _spot_check_and_latency_network(
                w3_sep,
                "sepolia",
                sep_insts,
                sep_auds,
                eth_usd=anchor.eth_usd,
                latency_txs=latency_txs,
                run_t8=True,
            )
            all_gas_rows.extend(sep_setup_rows)
            all_gas_rows.extend(sep_gas_rows)
            all_latency_rows.extend(sep_lat_rows)
            live_meta["sepolia"] = {
                "security_on_main_d1": t1_t6_evidence,
                "benchmark_contracts": sep_bench_meta,
                **sep_extra,
            }
        finally:
            for w in [sep_non_aud, *sep_auds]:
                _sweep_wallet(w3_sep, "sepolia", w, sep_deployer.address)

        # --- Arbitrum Sepolia ---
        print("4/4 Running Arbitrum Sepolia benchmark suite + 30 attest txs...", flush=True)
        w3_l2, l2_deployer = _connect_live("arbitrum-sepolia")
        l2_auds = [_create_ephemeral_wallet(f"l2_bench_aud_{i}") for i in (1, 2, 3)]
        try:
            l2_insts, l2_bench_meta, l2_setup_rows = _deploy_benchmark_suite(
                w3_l2, "arbitrum-sepolia", l2_deployer, l2_auds, ("D1", "D3")
            )
            _fund_wallet(w3_l2, "arbitrum-sepolia", l2_deployer, l2_auds[0], 0.003)
            _fund_wallet(w3_l2, "arbitrum-sepolia", l2_deployer, l2_auds[1], 0.002)
            _fund_wallet(w3_l2, "arbitrum-sepolia", l2_deployer, l2_auds[2], 0.002)
            l2_gas_rows, l2_lat_rows, _ = _spot_check_and_latency_network(
                w3_l2,
                "arbitrum-sepolia",
                l2_insts,
                l2_auds,
                eth_usd=anchor.eth_usd,
                latency_txs=latency_txs,
                run_t8=False,
            )
            all_gas_rows.extend(l2_setup_rows)
            all_gas_rows.extend(l2_gas_rows)
            all_latency_rows.extend(l2_lat_rows)
            live_meta["arbitrum-sepolia"] = {
                "benchmark_contracts": l2_bench_meta,
            }
        finally:
            for w in l2_auds:
                _sweep_wallet(w3_l2, "arbitrum-sepolia", w, l2_deployer.address)

    enriched_gas = enrich_gas_rows_with_price_anchor(all_gas_rows, anchor)
    gas_df = pd.DataFrame(enriched_gas)
    gas_csv_path = RESULTS_DIR / "E5_gas.csv"
    gas_df.to_csv(gas_csv_path, index=False)

    lat_df = pd.DataFrame(all_latency_rows)
    lat_csv_path = RESULTS_DIR / "E5_latency.csv"
    lat_df.to_csv(lat_csv_path, index=False)

    plot_path = generate_gas_vs_batch_plot(gas_df, FIGURES_DIR / "gas_vs_batch.png")
    lat_summary = compute_latency_summary(lat_df)

    summary = {
        "schema_version": "1.0",
        "generated_utc": _utc_now(),
        "git_commit": _git_commit(),
        "price_anchor": anchor.to_dict(),
        "latency_summary": lat_summary,
        "live_networks": live_meta,
        "outputs": {
            "E5_gas_csv": str(gas_csv_path.relative_to(REPO_ROOT).as_posix()),
            "E5_latency_csv": str(lat_csv_path.relative_to(REPO_ROOT).as_posix()),
            "gas_vs_batch_png": str(plot_path.relative_to(REPO_ROOT).as_posix()),
        },
    }
    summary_path = RESULTS_DIR / "E5_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Done! Saved {gas_csv_path}, {lat_csv_path}, {plot_path}, {summary_path}", flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Phase 7 Experiment E5 on-chain benchmarks.")
    parser.add_argument("--skip-live", action="store_true", help="Run only offline Anvil suite + price anchor.")
    parser.add_argument("--latency-txs", type=int, default=30, help="Number of attest txs per live network.")
    args = parser.parse_args()
    run_phase7(skip_live=args.skip_live, latency_txs=args.latency_txs)


if __name__ == "__main__":
    main()
