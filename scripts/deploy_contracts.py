"""Deploy and configure RiskAttestationRegistry (D1) and E5 variants (D2, D3).

Supports:
  - local-evm: in-process deterministic PyEVMBackend verification
  - anvil: local Anvil/RPC node (strictly checks chainId == 31337 before using Anvil test keys)
  - sepolia: Ethereum Sepolia testnet (requires SEPOLIA_RPC_URL + SEPOLIA_DEPLOYER_PRIVATE_KEY in .env)
  - arbitrum-sepolia / base-sepolia: L2 testnet deployment
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from eth_account import Account
from eth_tester import EthereumTester, PyEVMBackend
from eth_utils import keccak
from web3 import Web3
from web3.providers.eth_tester import EthereumTesterProvider

from src.contracts.compiler import compile_contract

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENTS_PATH = REPO_ROOT / "deployments.json"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

CHAIN_IDS: dict[str, int] = {
    "anvil": 31337,
    "sepolia": 11155111,
    "arbitrum-sepolia": 421614,
    "base-sepolia": 84532,
}


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


def _tx_hash_hex(raw_hash: Any) -> str:
    hex_str = raw_hash.hex() if hasattr(raw_hash, "hex") else str(raw_hash)
    return hex_str if hex_str.startswith("0x") else f"0x{hex_str}"


def _wait_rpc_synced(
    w3: Web3,
    target_block: int,
    *,
    contract_address: str | None = None,
    timeout_s: float = 25.0,
) -> None:
    """Wait until a potentially load-balanced RPC node catches up to target_block."""
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        try:
            head = int(w3.eth.block_number)
            code_ok = True if not contract_address else len(w3.eth.get_code(contract_address)) > 0
            if head >= target_block and code_ok:
                return
        except Exception:
            pass
        time.sleep(0.5)


def _send_tx(
    w3: Web3,
    tx_fn_or_dict: Any,
    *,
    sender_address: str,
    private_key: str | None = None,
    nonce: int | None = None,
    priority_gwei: float | None = None,
) -> Any:
    if private_key is None:
        if hasattr(tx_fn_or_dict, "transact"):
            tx_hash = tx_fn_or_dict.transact({"from": sender_address})
        else:
            tx = dict(tx_fn_or_dict)
            tx["from"] = sender_address
            tx_hash = w3.eth.send_transaction(tx)
        return w3.eth.wait_for_transaction_receipt(tx_hash)

    resolved_nonce = (
        nonce
        if nonce is not None
        else w3.eth.get_transaction_count(sender_address, block_identifier="pending")
    )
    tx_params: dict[str, Any] = {
        "from": sender_address,
        "nonce": resolved_nonce,
        "chainId": w3.eth.chain_id,
    }
    if priority_gwei is not None:
        latest = w3.eth.get_block("latest")
        base_fee = int(latest.get("baseFeePerGas", 0))
        prio_wei = int(w3.to_wei(priority_gwei, "gwei"))
        tx_params["maxPriorityFeePerGas"] = prio_wei
        tx_params["maxFeePerGas"] = max(base_fee * 2 + prio_wei, prio_wei * 2)

    if hasattr(tx_fn_or_dict, "build_transaction"):
        if priority_gwei is not None:
            contract_addr = getattr(tx_fn_or_dict, "address", None)
            est = 0
            last_err: Exception | None = None
            for _ in range(12):
                try:
                    est = int(tx_fn_or_dict.estimate_gas({"from": sender_address}))
                    if contract_addr and est < 22_000:
                        time.sleep(0.75)
                        continue
                    last_err = None
                    break
                except Exception as exc:
                    last_err = exc
                    time.sleep(0.75)
            if last_err is not None or (contract_addr and est < 22_000):
                raise RuntimeError(f"estimate_gas failed after retries (est={est}): {last_err}")
            tx_params["gas"] = max(int(est * 1.15), est + 25_000)
        tx = tx_fn_or_dict.build_transaction(tx_params)
    else:
        tx = dict(tx_fn_or_dict)
        tx.update(tx_params)
        if "gas" not in tx:
            tx["gas"] = w3.eth.estimate_gas(tx)
        if "gasPrice" not in tx and "maxFeePerGas" not in tx:
            tx["gasPrice"] = w3.eth.gas_price

    signed = Account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    rc = w3.eth.wait_for_transaction_receipt(tx_hash)
    if int(rc.status) != 1:
        raise RuntimeError(f"Deployment/setup tx failed (status={rc.status}): {_tx_hash_hex(tx_hash)}")
    return rc


def _read_auditors(*prefixes: str) -> list[str]:
    auditors: list[str] = []
    for idx in (1, 2, 3):
        val = ""
        for prefix in prefixes:
            candidate = os.environ.get(f"{prefix}_AUDITOR{idx}_ADDRESS", "").strip()
            if candidate:
                val = candidate
                break
        if val:
            auditors.append(Web3.to_checksum_address(val))
    return auditors


def _connect_live_network(
    network: str,
    *,
    rpc_var: str,
    pk_var: str,
    owner_var: str,
    owner_type_var: str,
    auditor_prefixes: tuple[str, ...],
) -> tuple[Web3, str, str, str, list[str], str]:
    rpc_url = os.environ.get(rpc_var, "").strip()
    pk = os.environ.get(pk_var, "").strip()
    if not rpc_url or not pk:
        raise RuntimeError(f"Missing {rpc_var} or {pk_var} in environment/.env")
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    expected_cid = CHAIN_IDS[network]
    if not w3.is_connected() or w3.eth.chain_id != expected_cid:
        actual_cid = w3.eth.chain_id if w3.is_connected() else "unreachable"
        raise RuntimeError(f"Expected {network} chainId {expected_cid}, got {actual_cid}")
    deployer = Account.from_key(pk).address
    configured_owner = os.environ.get(owner_var, "").strip()
    owner_addr = Web3.to_checksum_address(configured_owner) if configured_owner else deployer
    owner_type = (
        os.environ.get(owner_type_var, "multisig_or_external")
        if configured_owner and owner_addr.lower() != deployer.lower()
        else "eoa_demo_limit"
    )
    auditors = _read_auditors(*auditor_prefixes)
    return w3, deployer, pk, owner_addr, auditors, owner_type


def _connect(network: str) -> tuple[Web3, str, str | None, str, list[str], str]:
    """Return (w3, deployer_addr, deployer_pk, owner_addr, auditors, owner_type)."""
    load_dotenv(REPO_ROOT / ".env")

    if network == "local-evm":
        w3 = Web3(EthereumTesterProvider(EthereumTester(PyEVMBackend())))
        accts = list(w3.eth.accounts)
        return w3, accts[0], None, accts[0], accts[1:4], "local_ephemeral_eoa"

    if network == "anvil":
        rpc_url = os.environ.get("ANVIL_RPC_URL", "http://127.0.0.1:8545")
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not w3.is_connected():
            raise ConnectionError(f"Cannot connect to Anvil RPC at {rpc_url}")
        if w3.eth.chain_id != 31337:
            raise RuntimeError(
                f"Refusing to use Anvil test keys on non-Anvil chain_id={w3.eth.chain_id}"
            )
        pk_owner = os.environ.get(
            "ANVIL_OWNER_PRIVATE_KEY",
            "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
        )
        aud_pks = [
            os.environ.get(
                "ANVIL_AUDITOR1_PRIVATE_KEY",
                "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
            ),
            os.environ.get(
                "ANVIL_AUDITOR2_PRIVATE_KEY",
                "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",
            ),
            os.environ.get(
                "ANVIL_AUDITOR3_PRIVATE_KEY",
                "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6",
            ),
        ]
        owner_addr = Account.from_key(pk_owner).address
        auditors = [Account.from_key(pk).address for pk in aud_pks]
        return w3, owner_addr, pk_owner, owner_addr, auditors, "anvil_test_eoa"

    live_configs: dict[str, dict[str, Any]] = {
        "sepolia": {
            "rpc_var": "SEPOLIA_RPC_URL",
            "pk_var": "SEPOLIA_DEPLOYER_PRIVATE_KEY",
            "owner_var": "SEPOLIA_OWNER_ADDRESS",
            "owner_type_var": "SEPOLIA_OWNER_TYPE",
            "auditor_prefixes": ("SEPOLIA",),
        },
        "arbitrum-sepolia": {
            "rpc_var": "L2_RPC_URL",
            "pk_var": "L2_DEPLOYER_PRIVATE_KEY",
            "owner_var": "L2_OWNER_ADDRESS",
            "owner_type_var": "L2_OWNER_TYPE",
            "auditor_prefixes": ("L2", "SEPOLIA"),
        },
        "base-sepolia": {
            "rpc_var": "L2_RPC_URL",
            "pk_var": "L2_DEPLOYER_PRIVATE_KEY",
            "owner_var": "L2_OWNER_ADDRESS",
            "owner_type_var": "L2_OWNER_TYPE",
            "auditor_prefixes": ("L2", "SEPOLIA"),
        },
    }
    if network in live_configs:
        return _connect_live_network(network, **live_configs[network])

    raise ValueError(f"Unsupported network: {network}")


def deploy_network(
    network: str,
    variants: list[str],
    threshold: int = 2,
    save: bool = True,
) -> dict[str, Any]:
    """Deploy selected contract variants, configure auditors/threshold, and update deployments.json."""
    w3, deployer, pk, owner_addr, auditors, owner_type = _connect(network)
    commit_hash = _git_commit()
    initial_owner_arg = owner_addr if owner_addr.lower() != deployer.lower() else ZERO_ADDRESS
    next_nonce = (
        w3.eth.get_transaction_count(deployer, block_identifier="pending")
        if pk is not None
        else None
    )

    def _consume_nonce() -> int | None:
        nonlocal next_nonce
        if next_nonce is None:
            return None
        current = next_nonce
        next_nonce += 1
        return current

    prio_gwei = 0.05 if network == "sepolia" else None

    deployed: dict[str, Any] = {}
    for variant in variants:
        compiled = compile_contract(variant, use_cache=True)
        factory = w3.eth.contract(abi=compiled.abi, bytecode=compiled.bytecode)
        deploy_rc = _send_tx(
            w3,
            factory.constructor(initial_owner_arg),
            sender_address=deployer,
            private_key=pk,
            nonce=_consume_nonce(),
            priority_gwei=prio_gwei,
        )
        if pk is not None and network not in ("local-evm", "anvil"):
            _wait_rpc_synced(w3, int(deploy_rc.blockNumber), contract_address=deploy_rc.contractAddress)
        contract = w3.eth.contract(address=deploy_rc.contractAddress, abi=compiled.abi)

        setup_txs: dict[str, Any] = {"add_auditors": [], "set_threshold": None}
        last_block = int(deploy_rc.blockNumber)
        # Only configure roster/threshold if deployer is the owner (otherwise Safe executes via multisig UI)
        if owner_addr.lower() == deployer.lower() and auditors:
            for aud in auditors:
                rc_aud = _send_tx(
                    w3,
                    contract.functions.add_auditor(aud),
                    sender_address=deployer,
                    private_key=pk,
                    nonce=_consume_nonce(),
                    priority_gwei=prio_gwei,
                )
                last_block = max(last_block, int(rc_aud.blockNumber))
                setup_txs["add_auditors"].append(
                    {"auditor": aud, "tx_hash": _tx_hash_hex(rc_aud.transactionHash), "gas_used": int(rc_aud.gasUsed)}
                )
            if len(auditors) >= threshold:
                if pk is not None and network not in ("local-evm", "anvil"):
                    _wait_rpc_synced(w3, last_block, contract_address=deploy_rc.contractAddress)
                rc_k = _send_tx(
                    w3,
                    contract.functions.set_threshold(threshold),
                    sender_address=deployer,
                    private_key=pk,
                    nonce=_consume_nonce(),
                    priority_gwei=prio_gwei,
                )
                last_block = max(last_block, int(rc_k.blockNumber))
                setup_txs["set_threshold"] = {
                    "threshold": threshold,
                    "tx_hash": _tx_hash_hex(rc_k.transactionHash),
                    "gas_used": int(rc_k.gasUsed),
                }
        if pk is not None and network not in ("local-evm", "anvil"):
            _wait_rpc_synced(w3, last_block, contract_address=deploy_rc.contractAddress)

        deployed[variant] = {
            "contract_name": compiled.name,
            "source_path": compiled.source_path,
            "source_sha256": compiled.source_sha256,
            "vyper_version": compiled.vyper_version,
            "address": deploy_rc.contractAddress,
            "deploy_tx_hash": _tx_hash_hex(deploy_rc.transactionHash),
            "deploy_gas_used": int(deploy_rc.gasUsed),
            "block_number": int(deploy_rc.blockNumber),
            "deployer": deployer,
            "owner": contract.functions.owner().call(),
            "owner_type": owner_type,
            "constructor_arg_initial_owner": initial_owner_arg,
            "auditor_count": int(contract.functions.auditor_count().call()),
            "threshold": int(contract.functions.threshold().call()),
            "auditors": auditors if owner_addr.lower() == deployer.lower() else [],
            "pending_owner_setup": owner_addr.lower() != deployer.lower(),
            "intended_auditors": auditors if owner_addr.lower() != deployer.lower() else [],
            "setup_txs": setup_txs,
            "verified_explorer": False,
        }

    # On local-evm, run an immediate end-to-end smoke check on D1 so deployments.json carries verified evidence.
    smoke_evidence: dict[str, Any] | None = None
    if network == "local-evm" and "D1" in deployed and len(auditors) >= 2:
        d1_art = compile_contract("D1", use_cache=True)
        d1 = w3.eth.contract(address=deployed["D1"]["address"], abi=d1_art.abi)
        cid = keccak(b"smoke-case-id")
        eh = keccak(b"smoke-evidence")
        mh = keccak(b"smoke-model")
        subject = w3.eth.accounts[5]
        rc_reg = _send_tx(
            w3,
            d1.functions.register_case(cid, subject, 1, eh, mh, "ipfs://QmSmoke"),
            sender_address=auditors[0],
        )
        rc_a1 = _send_tx(
            w3,
            d1.functions.attest(cid, 1, b"\x00" * 32),
            sender_address=auditors[0],
        )
        rc_a2 = _send_tx(
            w3,
            d1.functions.attest(cid, 1, b"\x00" * 32),
            sender_address=auditors[1],
        )
        case_state = d1.functions.get_case(cid).call()
        smoke_evidence = {
            "case_id": "0x" + cid.hex(),
            "register_gas_used": int(rc_reg.gasUsed),
            "attest1_gas_used": int(rc_a1.gasUsed),
            "attest2_gas_used": int(rc_a2.gasUsed),
            "total_finalization_gas": int(rc_reg.gasUsed + rc_a1.gasUsed + rc_a2.gasUsed),
            "final_status": int(case_state[9]),
            "verify_evidence_exact": bool(d1.functions.verify_evidence(cid, eh).call()),
        }

    network_record: dict[str, Any] = {
        "network": network,
        "chain_id": int(w3.eth.chain_id),
        "updated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": commit_hash,
        "contracts": deployed,
    }
    if smoke_evidence is not None:
        network_record["smoke_check_d1"] = smoke_evidence

    if save:
        existing: dict[str, Any] = {}
        if DEPLOYMENTS_PATH.is_file():
            existing = json.loads(DEPLOYMENTS_PATH.read_text(encoding="utf-8"))
        existing.setdefault("schema_version", "1.0")
        existing.setdefault("networks", {})[network] = network_record
        DEPLOYMENTS_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    return network_record


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy X-SPIDE-G Vyper contracts.")
    parser.add_argument(
        "--network",
        choices=["local-evm", "anvil", "sepolia", "arbitrum-sepolia", "base-sepolia"],
        default="local-evm",
    )
    parser.add_argument(
        "--variants",
        nargs="+",
        choices=["D1", "D2", "D3"],
        default=None,
    )
    parser.add_argument("--threshold", type=int, default=2)
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()

    variants = args.variants
    if variants is None:
        variants = ["D1", "D3"] if args.network in ("arbitrum-sepolia", "base-sepolia") else ["D1", "D2", "D3"]

    record = deploy_network(
        network=args.network,
        variants=variants,
        threshold=args.threshold,
        save=not args.no_save,
    )
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
