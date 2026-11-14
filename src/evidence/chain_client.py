"""On-chain client and persistent local-EVM bridge for RiskAttestationRegistry (Phase 6)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from dotenv import load_dotenv
from eth_account import Account
from eth_tester import EthereumTester, PyEVMBackend
from web3 import Web3
from web3.logs import DISCARD
from web3.providers.eth_tester import EthereumTesterProvider

from src.contracts.compiler import compile_contract
from src.evidence.canonical import normalize_address, normalize_bytes32_hex
from src.evidence.storage import load_and_recompute_evidence

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_LEDGER_PATH = REPO_ROOT / "evidence" / "local_chain_ledger.json"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ZERO_BYTES32 = b"\x00" * 32

STATUS_NAMES = {
    0: "Open",
    1: "Approved",
    2: "Rejected",
    3: "Disputed",
}

DECISION_NAMES = {
    0: "Unset",
    1: "Approve",
    2: "Reject",
    3: "NeedsReview",
}


class RegistryChainSession:
    """Wraps Web3 + RiskAttestationRegistry (D1) for local-evm, Anvil, or Sepolia/L2 RPC."""

    def __init__(self, network: str = "local-evm", *, threshold: int = 2) -> None:
        load_dotenv(REPO_ROOT / ".env")
        self.network = network
        self.compiled = compile_contract("D1", use_cache=True)

        if network == "local-evm":
            self.w3 = Web3(EthereumTesterProvider(EthereumTester(PyEVMBackend())))
            accts = list(self.w3.eth.accounts)
            self.owner = accts[0]
            self.auditors = accts[1:4]
            self.outsider = accts[4]
            self.is_test_key_allowed = True
            self.test_key_banner = "TEST KEY – ANVIL / LOCAL-EVM ONLY"

            factory = self.w3.eth.contract(abi=self.compiled.abi, bytecode=self.compiled.bytecode)
            rc = self.w3.eth.wait_for_transaction_receipt(
                factory.constructor(ZERO_ADDRESS).transact({"from": self.owner})
            )
            self.contract = self.w3.eth.contract(address=rc.contractAddress, abi=self.compiled.abi)
            for aud in self.auditors:
                self.w3.eth.wait_for_transaction_receipt(
                    self.contract.functions.add_auditor(aud).transact({"from": self.owner})
                )
            if threshold != 2:
                self.w3.eth.wait_for_transaction_receipt(
                    self.contract.functions.set_threshold(threshold).transact({"from": self.owner})
                )
        elif network == "anvil":
            rpc_url = os.environ.get("ANVIL_RPC_URL", "http://127.0.0.1:8545")
            self.w3 = Web3(Web3.HTTPProvider(rpc_url))
            if not self.w3.is_connected() or self.w3.eth.chain_id != 31337:
                raise RuntimeError(f"Anvil RPC at {rpc_url} must be connected with chain_id=31337")
            self.is_test_key_allowed = True
            self.test_key_banner = "TEST KEY – ANVIL ONLY"
            self.owner, self.auditors, self.contract = self._load_deployed_contract("anvil")
            self.outsider = ZERO_ADDRESS
        else:
            rpc_var = "SEPOLIA_RPC_URL" if network == "sepolia" else "L2_RPC_URL"
            rpc_url = os.environ.get(rpc_var, "").strip()
            if not rpc_url:
                raise RuntimeError(f"{rpc_var} is not configured in .env")
            self.w3 = Web3(Web3.HTTPProvider(rpc_url))
            self.is_test_key_allowed = False
            self.test_key_banner = "CLIENT-SIDE METAMASK SIGNING ONLY (NO SERVER PRIVATE KEYS)"
            self.owner, self.auditors, self.contract = self._load_deployed_contract(network)
            self.outsider = ZERO_ADDRESS

    def _load_deployed_contract(self, net_key: str) -> tuple[str, list[str], Any]:
        deps = json.loads((REPO_ROOT / "deployments.json").read_text(encoding="utf-8"))
        info = deps["networks"][net_key]["contracts"]["D1"]
        contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(info["address"]),
            abi=self.compiled.abi,
        )
        return info["owner"], list(info.get("auditors", [])), contract

    def register_case(
        self,
        *,
        auditor_index: int = 0,
        case_id_hex: str,
        subject_address: str,
        subject_chain_id: int,
        evidence_hash_hex: str,
        model_version_hash_hex: str,
        evidence_uri: str,
    ) -> dict[str, Any]:
        """Register a case on-chain using an authorized test auditor account (local-evm only)."""
        if not self.is_test_key_allowed:
            raise PermissionError(
                "Server-side signing is disabled on non-local networks. Use signer/index.html with MetaMask."
            )
        sender = self.auditors[auditor_index]
        cid_bytes = bytes.fromhex(normalize_bytes32_hex(case_id_hex, "case_id")[2:])
        eh_bytes = bytes.fromhex(normalize_bytes32_hex(evidence_hash_hex, "evidence_hash")[2:])
        mh_bytes = bytes.fromhex(normalize_bytes32_hex(model_version_hash_hex, "model_version_hash")[2:])
        subj_checksum = Web3.to_checksum_address(normalize_address(subject_address))

        tx_hash = self.contract.functions.register_case(
            cid_bytes,
            subj_checksum,
            int(subject_chain_id),
            eh_bytes,
            mh_bytes,
            str(evidence_uri)[:128],
        ).transact({"from": sender})
        rc = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        return {
            "tx_hash": "0x" + rc.transactionHash.hex().lstrip("0x"),
            "gas_used": int(rc.gasUsed),
            "block_number": int(rc.blockNumber),
            "sender": sender,
        }

    def attest_case(
        self,
        *,
        auditor_index: int,
        case_id_hex: str,
        decision: int,
        reason_hash_hex: str = "0x" + "00" * 32,
    ) -> dict[str, Any]:
        """Submit or replace an attestation using a local test auditor account."""
        if not self.is_test_key_allowed:
            raise PermissionError(
                "Server-side signing is disabled on non-local networks. Use signer/index.html with MetaMask."
            )
        sender = self.auditors[auditor_index]
        cid_bytes = bytes.fromhex(normalize_bytes32_hex(case_id_hex, "case_id")[2:])
        rh_bytes = bytes.fromhex(normalize_bytes32_hex(reason_hash_hex, "reason_hash")[2:])

        tx_hash = self.contract.functions.attest(cid_bytes, int(decision), rh_bytes).transact(
            {"from": sender}
        )
        rc = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        return {
            "tx_hash": "0x" + rc.transactionHash.hex().lstrip("0x"),
            "gas_used": int(rc.gasUsed),
            "block_number": int(rc.blockNumber),
            "sender": sender,
            "decision": int(decision),
            "decision_name": DECISION_NAMES.get(int(decision), "Unknown"),
        }

    def get_case_and_events(self, case_id_hex: str) -> dict[str, Any]:
        """Read on-chain Case struct and decode CaseRegistered, Attested, and StatusChanged events."""
        cid_norm = normalize_bytes32_hex(case_id_hex, "case_id")
        cid_bytes = bytes.fromhex(cid_norm[2:])
        raw = self.contract.functions.get_case(cid_bytes).call()

        case_dict = {
            "case_id": cid_norm,
            "subject": str(raw[0]).lower(),
            "subject_chain_id": int(raw[1]),
            "evidence_hash": "0x" + bytes(raw[2]).hex(),
            "model_version_hash": "0x" + bytes(raw[3]).hex(),
            "registrant": str(raw[4]),
            "created_at": int(raw[5]),
            "approve_count": int(raw[6]),
            "reject_count": int(raw[7]),
            "review_count": int(raw[8]),
            "status": int(raw[9]),
            "status_name": STATUS_NAMES.get(int(raw[9]), "Unknown"),
            "exists": str(raw[4]).lower() != ZERO_ADDRESS,
        }

        reg_logs = self.contract.events.CaseRegistered().get_logs(
            from_block=0, argument_filters={"case_id": cid_bytes}
        )
        att_logs = self.contract.events.Attested().get_logs(
            from_block=0, argument_filters={"case_id": cid_bytes}
        )
        sc_logs = self.contract.events.StatusChanged().get_logs(
            from_block=0, argument_filters={"case_id": cid_bytes}
        )

        evidence_uri = str(reg_logs[0]["args"]["evidence_uri"]) if reg_logs else ""
        attestation_events = [
            {
                "auditor": str(lg["args"]["auditor"]),
                "decision": int(lg["args"]["decision"]),
                "decision_name": DECISION_NAMES.get(int(lg["args"]["decision"]), "Unknown"),
                "revision": int(lg["args"]["revision"]),
                "reason_hash": "0x" + bytes(lg["args"]["reason_hash"]).hex(),
                "block_number": int(lg["blockNumber"]),
                "tx_hash": "0x" + lg["transactionHash"].hex().lstrip("0x"),
            }
            for lg in att_logs
        ]
        status_events = [
            {
                "old_status": int(lg["args"]["old_status"]),
                "old_status_name": STATUS_NAMES.get(int(lg["args"]["old_status"]), "Unknown"),
                "new_status": int(lg["args"]["new_status"]),
                "new_status_name": STATUS_NAMES.get(int(lg["args"]["new_status"]), "Unknown"),
                "block_number": int(lg["blockNumber"]),
                "tx_hash": "0x" + lg["transactionHash"].hex().lstrip("0x"),
            }
            for lg in sc_logs
        ]

        return {
            "case": case_dict,
            "evidence_uri": evidence_uri,
            "attestation_events": attestation_events,
            "status_events": status_events,
        }

    def public_verify_case(
        self,
        case_id_hex: str,
        *,
        evidence_dir: Path | None = None,
    ) -> dict[str, Any]:
        """Third-party verification: fetch on-chain state + events, fetch off-chain JSON, recompute hash."""
        chain_data = self.get_case_and_events(case_id_hex)
        case_info = chain_data["case"]
        if not case_info["exists"]:
            return {
                "verified": False,
                "badge": "❌ UNREGISTERED CASE",
                "reason": "Case does not exist on-chain",
                "onchain": chain_data,
                "offchain": None,
            }

        try:
            offchain = load_and_recompute_evidence(
                case_id_value=case_id_hex,
                evidence_uri=chain_data["evidence_uri"],
                evidence_dir=evidence_dir,
            )
        except Exception as exc:
            return {
                "verified": False,
                "badge": "❌ MISSING OR CORRUPTED OFF-CHAIN JSON",
                "reason": str(exc),
                "onchain": chain_data,
                "offchain": None,
            }

        cid_bytes = bytes.fromhex(normalize_bytes32_hex(case_id_hex, "case_id")[2:])
        raw_hash_bytes = bytes.fromhex(offchain["raw_file_hash"][2:])
        onchain_verify_raw = bool(
            self.contract.functions.verify_evidence(cid_bytes, raw_hash_bytes).call()
        )
        hash_matches = (
            onchain_verify_raw
            and offchain["raw_file_hash"] == case_info["evidence_hash"]
            and offchain["canonical_recomputed_hash"] == case_info["evidence_hash"]
            and offchain["is_canonical_byte_identical"]
        )

        return {
            "verified": hash_matches,
            "badge": "✅ VERIFIED (HASH & SCHEMA MATCH)" if hash_matches else "❌ TAMPERED / HASH MISMATCH",
            "onchain_verify_call": onchain_verify_raw,
            "onchain_evidence_hash": case_info["evidence_hash"],
            "recomputed_raw_hash": offchain["raw_file_hash"],
            "recomputed_canonical_hash": offchain["canonical_recomputed_hash"],
            "is_canonical_byte_identical": offchain["is_canonical_byte_identical"],
            "onchain": chain_data,
            "offchain": offchain,
        }


def build_signer_query_url(
    *,
    base_url: str = "signer/index.html",
    action: str,
    contract_address: str,
    chain_id: int,
    case_id_hex: str,
    subject_address: str = "",
    subject_chain_id: int = 1,
    evidence_hash_hex: str = "",
    model_version_hash_hex: str = "",
    evidence_uri: str = "",
    decision: int = 1,
    reason_hash_hex: str = "0x" + "00" * 32,
) -> str:
    """Build deterministic query-string URL for client-side MetaMask signing in `signer/index.html`."""
    params = {
        "action": action,
        "contract": contract_address,
        "chain_id": str(chain_id),
        "case_id": case_id_hex,
        "subject": subject_address,
        "subject_chain_id": str(subject_chain_id),
        "evidence_hash": evidence_hash_hex,
        "model_version_hash": model_version_hash_hex,
        "evidence_uri": evidence_uri,
        "decision": str(decision),
        "reason_hash": reason_hash_hex,
    }
    return f"{base_url}?{urlencode(params)}"
