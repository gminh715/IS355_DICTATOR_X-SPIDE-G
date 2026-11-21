"""Shared EVM fixtures and revert/event helpers for contract tests."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

import pytest
from eth_tester import EthereumTester, PyEVMBackend
from eth_tester.exceptions import TransactionFailed
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import ContractLogicError
from web3.providers.eth_tester import EthereumTesterProvider

from src.contracts.compiler import CompiledContract, compile_contract

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ZERO_BYTES32 = b"\x00" * 32


@dataclass
class EvmContext:
    """EVM test harness wrapping Web3, pre-funded accounts, and compiled artifacts."""

    w3: Web3
    owner: str
    auditors: tuple[str, str, str]
    extra_auditor: str
    outsider: str
    subject: str

    def deploy(self, variant: str, *, initial_owner: str = ZERO_ADDRESS, sender: str | None = None) -> tuple[Contract, Any]:
        compiled: CompiledContract = compile_contract(variant, use_cache=True)
        factory = self.w3.eth.contract(abi=compiled.abi, bytecode=compiled.bytecode)
        tx_hash = factory.constructor(initial_owner).transact({"from": sender or self.owner})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        contract = self.w3.eth.contract(address=receipt.contractAddress, abi=compiled.abi)
        return contract, receipt

    def deploy_configured(self, variant: str, *, k: int = 2) -> Contract:
        contract, _ = self.deploy(variant)
        for aud in self.auditors:
            self.send(contract.functions.add_auditor(aud), self.owner)
        if k != 2:
            self.send(contract.functions.set_threshold(k), self.owner)
        return contract

    def send(self, fn_call: Any, sender: str) -> Any:
        tx_hash = fn_call.transact({"from": sender})
        return self.w3.eth.wait_for_transaction_receipt(tx_hash)


def assert_reverts(action: Callable[[], Any], expected_substring: str | None = None) -> None:
    """Assert that a contract call/transaction reverts, optionally checking revert reason."""
    with pytest.raises((ContractLogicError, TransactionFailed, ValueError)) as exc_info:
        action()
    if expected_substring is not None:
        assert expected_substring in str(exc_info.value), (
            f"Expected {expected_substring!r} in revert message, got: {exc_info.value!r}"
        )


def unpack_case(variant: str, raw: tuple[Any, ...]) -> dict[str, Any]:
    """Normalize D1 Case and D2 CompactCase tuples into a common dict."""
    if variant == "D1":
        return {
            "subject": raw[0],
            "subject_chain_id": raw[1],
            "evidence_hash": raw[2],
            "model_version_hash": raw[3],
            "registrant": raw[4],
            "created_at": raw[5],
            "approve_count": raw[6],
            "reject_count": raw[7],
            "review_count": raw[8],
            "status": raw[9],
            "required_threshold": raw[10],
            "created_roster_nonce": raw[11],
        }
    return {
        "exists": raw[0],
        "evidence_hash": raw[1],
        "approve_count": raw[2],
        "reject_count": raw[3],
        "review_count": raw[4],
        "status": raw[5],
        "required_threshold": raw[6],
        "created_roster_nonce": raw[7],
    }


def unpack_batch(raw: tuple[Any, ...]) -> dict[str, Any]:
    """Normalize D3 Batch tuple into a dict."""
    return {
        "n_leaves": raw[0],
        "registrant": raw[1],
        "created_at": raw[2],
        "approve_count": raw[3],
        "reject_count": raw[4],
        "review_count": raw[5],
        "status": raw[6],
        "required_threshold": raw[7],
        "created_roster_nonce": raw[8],
    }


def unpack_attestation(variant: str, raw: tuple[Any, ...]) -> dict[str, Any]:
    """Normalize D1 Attestation and D2 CompactAttestation tuples into a common dict."""
    if variant == "D1":
        return {"decision": raw[0], "revision": raw[1], "timestamp": raw[2]}
    return {"decision": raw[0], "revision": raw[1]}


@pytest.fixture
def evm() -> EvmContext:
    """Fresh deterministic EVM state per test."""
    rpc_url = os.environ.get("XSPIDE_TEST_RPC_URL", "").strip()
    if rpc_url:
        w3 = Web3(Web3.HTTPProvider(rpc_url))
    else:
        w3 = Web3(EthereumTesterProvider(EthereumTester(PyEVMBackend())))

    accounts = w3.eth.accounts
    assert len(accounts) >= 7
    return EvmContext(
        w3=w3,
        owner=accounts[0],
        auditors=(accounts[1], accounts[2], accounts[3]),
        extra_auditor=accounts[4],
        outsider=accounts[5],
        subject=accounts[6],
    )
