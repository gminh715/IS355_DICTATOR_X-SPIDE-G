"""Web3 client, deployments.json loader, event decoder, and strictly-guarded Anvil test helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from dotenv import load_dotenv
from eth_account import Account
from eth_utils import keccak
from web3 import Web3

from src.evidence.canonical import normalize_address, normalize_bytes32_hex

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENTS_PATH = REPO_ROOT / "deployments.json"
ARTIFACTS_DIR = REPO_ROOT / "contracts" / "artifacts"

DECISION_LABELS: dict[int, str] = {
    0: "Unset",
    1: "Approve",
    2: "Reject",
    3: "NeedsReview",
}

STATUS_LABELS: dict[int, str] = {
    0: "Open",
    1: "Approved",
    2: "Rejected",
    3: "Disputed",
}

NETWORK_CHAIN_IDS: dict[str, int] = {
    "anvil": 31337,
    "sepolia": 11155111,
    "arbitrum-sepolia": 421614,
}

EXPLORER_TX_URLS: dict[str, str] = {
    "sepolia": "https://sepolia.etherscan.io/tx/",
    "arbitrum-sepolia": "https://sepolia.arbiscan.io/tx/",
}


def load_deployments(deployments_path: Path = DEPLOYMENTS_PATH) -> dict[str, Any]:
    """Load deployments.json generated in Phase 5."""
    if not deployments_path.is_file():
        raise FileNotFoundError(f"deployments.json not found at {deployments_path}")
    return json.loads(deployments_path.read_text(encoding="utf-8"))


def load_contract_abi(variant: str = "D1", artifacts_dir: Path = ARTIFACTS_DIR) -> list[dict[str, Any]]:
    """Load compiled Vyper ABI JSON for D1, D2, or D3."""
    name_map = {
        "D1": "RiskAttestationRegistry",
        "RiskAttestationRegistry": "RiskAttestationRegistry",
        "D2": "D2_EventOnly",
        "D2_EventOnly": "D2_EventOnly",
        "D3": "D3_MerkleBatch",
        "D3_MerkleBatch": "D3_MerkleBatch",
    }
    canonical = name_map.get(variant, variant)
    path = artifacts_dir / f"{canonical}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Contract artifact not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))["abi"]


def get_network_rpc_url(network: str) -> str:
    """Resolve RPC URL from .env without ever touching live private keys."""
    load_dotenv(REPO_ROOT / ".env")
    if network == "anvil":
        return os.environ.get("ANVIL_RPC_URL", "http://127.0.0.1:8545").strip()
    if network == "sepolia":
        url = os.environ.get("SEPOLIA_RPC_URL", "").strip()
        if not url:
            raise RuntimeError("SEPOLIA_RPC_URL is not set in environment/.env")
        return url
    if network == "arbitrum-sepolia":
        url = os.environ.get("L2_RPC_URL", "").strip()
        if not url:
            raise RuntimeError("L2_RPC_URL is not set in environment/.env")
        return url
    raise ValueError(f"Unsupported network: {network!r}")


def connect_web3(network: str, *, rpc_url: str | None = None) -> Web3:
    """Connect read-only Web3 provider and verify chain_id matches the selected network."""
    url = rpc_url or get_network_rpc_url(network)
    w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 8}))
    if not w3.is_connected():
        raise ConnectionError(f"Unable to connect to {network} RPC at {url}")
    expected_cid = NETWORK_CHAIN_IDS.get(network)
    if expected_cid is not None and w3.eth.chain_id != expected_cid:
        raise RuntimeError(
            f"Chain ID mismatch for {network}: expected {expected_cid}, got {w3.eth.chain_id}"
        )
    return w3


def get_registry_contract(
    w3: Web3,
    network: str,
    *,
    variant: str = "D1",
    deployments_path: Path = DEPLOYMENTS_PATH,
    contract_address: str | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Return a bound Web3 contract instance and deployment metadata entry."""
    dep = load_deployments(deployments_path)
    net_entry = dep.get("networks", {}).get(network)
    if net_entry is None and contract_address is None:
        raise KeyError(f"Network {network!r} not found in deployments.json")
    info = (net_entry or {}).get("contracts", {}).get(variant, {})
    addr = contract_address or info.get("address")
    if not addr:
        raise KeyError(f"Variant {variant} address not found for network {network!r}")
    abi = load_contract_abi(variant)
    contract = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=abi)
    return contract, info


def _bytes32_arg(val: bytes | str) -> bytes:
    return bytes.fromhex(normalize_bytes32_hex(val)[2:])


def _hex32(raw: bytes | Any) -> str:
    b = bytes(raw)
    return "0x" + b.hex()


def read_registry_meta(contract: Any, *, known_auditors: list[str] | None = None) -> dict[str, Any]:
    """Read governance metadata (owner, auditor_count, threshold, auditor flags) from chain."""
    owner = contract.functions.owner().call()
    auditor_count = int(contract.functions.auditor_count().call())
    threshold = int(contract.functions.threshold().call())
    auditor_status: dict[str, bool] = {}
    for addr in known_auditors or []:
        cs = Web3.to_checksum_address(addr)
        auditor_status[cs] = bool(contract.functions.is_auditor(cs).call())
    return {
        "address": contract.address,
        "owner": owner,
        "auditor_count": auditor_count,
        "threshold": threshold,
        "auditor_status": auditor_status,
    }


def read_case(contract: Any, case_id_hex: str) -> dict[str, Any]:
    """Read D1 Case struct from chain and return normalized dictionary."""
    cid = _bytes32_arg(case_id_hex)
    raw = contract.functions.get_case(cid).call()
    # D1 Case tuple: (subject, subject_chain_id, evidence_hash, model_version_hash,
    #                 registrant, created_at, approve_count, reject_count, review_count, status)
    if len(raw) == 10:
        registrant = str(raw[4])
        exists = int(registrant, 16) != 0
        status = int(raw[9])
        return {
            "exists": exists,
            "case_id": normalize_bytes32_hex(case_id_hex),
            "subject": str(raw[0]).lower(),
            "subject_chain_id": int(raw[1]),
            "evidence_hash": _hex32(raw[2]),
            "model_version_hash": _hex32(raw[3]),
            "registrant": registrant.lower(),
            "created_at": int(raw[5]),
            "approve_count": int(raw[6]),
            "reject_count": int(raw[7]),
            "review_count": int(raw[8]),
            "status": status,
            "status_label": STATUS_LABELS.get(status, f"Unknown({status})"),
        }
    # D2 CompactCase tuple: (exists, evidence_hash, approve_count, reject_count, review_count, status)
    status = int(raw[5])
    return {
        "exists": bool(raw[0]),
        "case_id": normalize_bytes32_hex(case_id_hex),
        "evidence_hash": _hex32(raw[1]),
        "approve_count": int(raw[2]),
        "reject_count": int(raw[3]),
        "review_count": int(raw[4]),
        "status": status,
        "status_label": STATUS_LABELS.get(status, f"Unknown({status})"),
    }


def verify_evidence_onchain(contract: Any, case_id_hex: str, evidence_hash_hex: str) -> bool:
    """Call on-chain view verify_evidence(case_id, h)."""
    return bool(
        contract.functions.verify_evidence(
            _bytes32_arg(case_id_hex),
            _bytes32_arg(evidence_hash_hex),
        ).call()
    )


def fetch_case_history(
    w3: Web3,
    contract: Any,
    case_id_hex: str,
    *,
    from_block: int = 0,
) -> dict[str, Any]:
    """Fetch and decode CaseRegistered, Attested, and StatusChanged logs for a case_id."""
    cid = _bytes32_arg(case_id_hex)
    latest_block = int(w3.eth.block_number)
    start_block = max(0, int(from_block))

    reg_logs = contract.events.CaseRegistered().get_logs(
        from_block=start_block,
        to_block=latest_block,
        argument_filters={"case_id": cid},
    )
    att_logs = contract.events.Attested().get_logs(
        from_block=start_block,
        to_block=latest_block,
        argument_filters={"case_id": cid},
    )
    status_logs = contract.events.StatusChanged().get_logs(
        from_block=start_block,
        to_block=latest_block,
        argument_filters={"case_id": cid},
    )

    registered = None
    if reg_logs:
        lg = reg_logs[0]
        args = lg["args"]
        registered = {
            "case_id": _hex32(args["case_id"]),
            "subject": str(args["subject"]).lower(),
            "evidence_hash": _hex32(args["evidence_hash"]),
            "model_version_hash": _hex32(args["model_version_hash"]),
            "evidence_uri": str(args["evidence_uri"]),
            "registrant": str(args["registrant"]).lower(),
            "block_number": int(lg["blockNumber"]),
            "tx_hash": "0x" + bytes(lg["transactionHash"]).hex(),
        }

    attestations = []
    for lg in sorted(att_logs, key=lambda x: (int(x["blockNumber"]), int(x["logIndex"]))):
        args = lg["args"]
        dec = int(args["decision"])
        attestations.append(
            {
                "auditor": str(args["auditor"]).lower(),
                "decision": dec,
                "decision_label": DECISION_LABELS.get(dec, f"Unknown({dec})"),
                "revision": int(args["revision"]),
                "reason_hash": _hex32(args["reason_hash"]),
                "block_number": int(lg["blockNumber"]),
                "tx_hash": "0x" + bytes(lg["transactionHash"]).hex(),
            }
        )

    status_changes = []
    for lg in sorted(status_logs, key=lambda x: (int(x["blockNumber"]), int(x["logIndex"]))):
        args = lg["args"]
        old_s = int(args["old_status"])
        new_s = int(args["new_status"])
        status_changes.append(
            {
                "old_status": old_s,
                "old_status_label": STATUS_LABELS.get(old_s, str(old_s)),
                "new_status": new_s,
                "new_status_label": STATUS_LABELS.get(new_s, str(new_s)),
                "block_number": int(lg["blockNumber"]),
                "tx_hash": "0x" + bytes(lg["transactionHash"]).hex(),
            }
        )

    return {
        "registered": registered,
        "attestations": attestations,
        "status_changes": status_changes,
    }


def list_registered_cases(
    w3: Web3,
    contract: Any,
    *,
    from_block: int = 0,
) -> list[dict[str, Any]]:
    """List all CaseRegistered events emitted by the registry contract."""
    latest_block = int(w3.eth.block_number)
    logs = contract.events.CaseRegistered().get_logs(
        from_block=max(0, int(from_block)),
        to_block=latest_block,
    )
    items = []
    for lg in sorted(logs, key=lambda x: (int(x["blockNumber"]), int(x["logIndex"])), reverse=True):
        args = lg["args"]
        items.append(
            {
                "case_id": _hex32(args["case_id"]),
                "subject": str(args["subject"]).lower(),
                "evidence_hash": _hex32(args["evidence_hash"]),
                "evidence_uri": str(args["evidence_uri"]),
                "block_number": int(lg["blockNumber"]),
                "tx_hash": "0x" + bytes(lg["transactionHash"]).hex(),
            }
        )
    return items


def inspect_tx_receipt(w3: Web3, contract: Any, tx_hash: str) -> dict[str, Any]:
    """Fetch transaction receipt and decode registry events without touching private keys."""
    receipt = w3.eth.get_transaction_receipt(tx_hash.strip())
    decoded_events: list[dict[str, Any]] = []
    for event_name in ("CaseRegistered", "Attested", "StatusChanged"):
        try:
            ev_logs = getattr(contract.events, event_name)().process_receipt(receipt)
            for ev in ev_logs:
                args_clean = {
                    k: ("0x" + bytes(v).hex() if isinstance(v, (bytes, bytearray)) else v)
                    for k, v in dict(ev["args"]).items()
                }
                decoded_events.append({"event": event_name, "args": args_clean})
        except Exception:
            continue
    return {
        "tx_hash": tx_hash.strip(),
        "status": int(receipt["status"]),
        "block_number": int(receipt["blockNumber"]),
        "gas_used": int(receipt["gasUsed"]),
        "from": str(receipt["from"]).lower(),
        "to": str(receipt["to"]).lower() if receipt.get("to") else None,
        "events": decoded_events,
    }


def get_anvil_test_accounts(w3: Web3) -> dict[str, dict[str, str]]:
    """Return TEST-ONLY Anvil auditor keys strictly when connected to chain_id == 31337."""
    chain_id = int(w3.eth.chain_id)
    if chain_id != 31337:
        raise RuntimeError(
            f"SECURITY GUARD: Refusing to expose Anvil test keys on chain_id={chain_id} (expected 31337)."
        )
    load_dotenv(REPO_ROOT / ".env")
    defaults = {
        "auditor_1": (
            "ANVIL_AUDITOR1_PRIVATE_KEY",
            "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
        ),
        "auditor_2": (
            "ANVIL_AUDITOR2_PRIVATE_KEY",
            "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",
        ),
        "auditor_3": (
            "ANVIL_AUDITOR3_PRIVATE_KEY",
            "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6",
        ),
    }
    accounts: dict[str, dict[str, str]] = {}
    for label, (env_var, fallback_pk) in defaults.items():
        pk = os.environ.get(env_var, fallback_pk).strip()
        addr = Account.from_key(pk).address
        accounts[label] = {
            "address": addr,
            "private_key": pk,
            "warning": "TEST KEY – ANVIL ONLY",
        }
    return accounts


def _send_anvil_tx(w3: Web3, fn_call: Any, private_key: str) -> dict[str, Any]:
    if int(w3.eth.chain_id) != 31337:
        raise RuntimeError(
            f"SECURITY GUARD: Anvil-only server signing refused on chain_id={w3.eth.chain_id}"
        )
    acct = Account.from_key(private_key)
    tx = fn_call.build_transaction(
        {
            "from": acct.address,
            "nonce": w3.eth.get_transaction_count(acct.address, block_identifier="pending"),
            "chainId": 31337,
        }
    )
    signed = Account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    if int(receipt["status"]) != 1:
        raise RuntimeError(f"Transaction reverted: tx_hash=0x{tx_hash.hex()}")
    return {
        "tx_hash": "0x" + bytes(receipt["transactionHash"]).hex(),
        "gas_used": int(receipt["gasUsed"]),
        "block_number": int(receipt["blockNumber"]),
        "sender": acct.address,
    }


def send_anvil_register_case(
    w3: Web3,
    contract: Any,
    private_key: str,
    *,
    case_id_hex: str,
    subject: str,
    subject_chain_id: int,
    evidence_hash_hex: str,
    model_version_hash_hex: str,
    evidence_uri: str,
) -> dict[str, Any]:
    """Execute register_case using an Anvil-only test auditor key."""
    if len(evidence_uri) > 128:
        raise ValueError("evidence_uri exceeds String[128]")
    fn = contract.functions.register_case(
        _bytes32_arg(case_id_hex),
        Web3.to_checksum_address(normalize_address(subject)),
        int(subject_chain_id),
        _bytes32_arg(evidence_hash_hex),
        _bytes32_arg(model_version_hash_hex),
        evidence_uri,
    )
    return _send_anvil_tx(w3, fn, private_key)


def send_anvil_attest(
    w3: Web3,
    contract: Any,
    private_key: str,
    *,
    case_id_hex: str,
    decision: int,
    reason_text_or_hash: str = "",
) -> dict[str, Any]:
    """Execute attest(case_id, decision, reason_hash) using an Anvil-only test auditor key."""
    if int(decision) not in (1, 2, 3):
        raise ValueError(f"decision must be 1, 2, or 3, got {decision!r}")
    raw_reason = reason_text_or_hash.strip()
    if not raw_reason:
        reason_bytes = b"\x00" * 32
    elif raw_reason.startswith("0x") and len(raw_reason) == 66:
        reason_bytes = _bytes32_arg(raw_reason)
    else:
        reason_bytes = keccak(raw_reason.encode("utf-8"))

    fn = contract.functions.attest(
        _bytes32_arg(case_id_hex),
        int(decision),
        reason_bytes,
    )
    return _send_anvil_tx(w3, fn, private_key)


def compute_reason_hash(reason_text: str) -> str:
    """Compute bytes32 reason_hash from optional auditor note (or zero bytes32 if empty)."""
    clean = reason_text.strip()
    if not clean:
        return "0x" + ("00" * 32)
    if clean.startswith("0x") and len(clean) == 66:
        return normalize_bytes32_hex(clean)
    return "0x" + keccak(clean.encode("utf-8")).hex()


def build_signer_url(
    base_url: str,
    *,
    action: str,
    chain_id: int,
    contract_address: str,
    case_id_hex: str,
    subject: str,
    subject_chain_id: int,
    evidence_hash_hex: str,
    model_version_hash_hex: str,
    evidence_uri: str,
    decision: int = 1,
    reason_hash: str = "0x" + ("00" * 32),
) -> str:
    """Construct the query-string URL for static signer/index.html."""
    params = {
        "action": action,
        "chain_id": str(int(chain_id)),
        "contract_address": Web3.to_checksum_address(contract_address),
        "case_id": normalize_bytes32_hex(case_id_hex),
        "subject": Web3.to_checksum_address(normalize_address(subject)),
        "subject_chain_id": str(int(subject_chain_id)),
        "evidence_hash": normalize_bytes32_hex(evidence_hash_hex),
        "model_version_hash": normalize_bytes32_hex(model_version_hash_hex),
        "evidence_uri": evidence_uri,
        "decision": str(int(decision)),
        "reason_hash": normalize_bytes32_hex(reason_hash),
    }
    sep = "&" if "?" in base_url else "?"
    return f"{base_url.rstrip('/')}{sep}{urlencode(params)}"
