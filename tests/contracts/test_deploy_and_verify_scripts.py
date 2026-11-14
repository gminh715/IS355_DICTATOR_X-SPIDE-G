"""Unit tests for deployment and Etherscan v2 verification scripts."""

from __future__ import annotations

import json
from typing import Any

import pytest
from eth_abi import encode
from eth_account import Account
from eth_tester import EthereumTester, PyEVMBackend
from web3 import Web3
from web3.providers.eth_tester import EthereumTesterProvider

from scripts import deploy_contracts, verify_contracts
from src.contracts.compiler import compile_contract


def test_local_evm_deploy_formats_hashes_and_smoke_check() -> None:
    record = deploy_contracts.deploy_network(
        network="local-evm",
        variants=["D1", "D2", "D3"],
        threshold=2,
        save=False,
    )
    assert record["network"] == "local-evm"
    for variant in ("D1", "D2", "D3"):
        info = record["contracts"][variant]
        assert info["deploy_tx_hash"].startswith("0x")
        assert len(info["deploy_tx_hash"]) == 66
        assert info["auditor_count"] == 3
        assert info["threshold"] == 2
        assert info["constructor_arg_initial_owner"] == deploy_contracts.ZERO_ADDRESS
        assert info["pending_owner_setup"] is False
        for entry in info["setup_txs"]["add_auditors"]:
            assert entry["tx_hash"].startswith("0x")
            assert len(entry["tx_hash"]) == 66
        assert info["setup_txs"]["set_threshold"]["tx_hash"].startswith("0x")

    smoke = record["smoke_check_d1"]
    assert smoke["final_status"] == 1
    assert smoke["verify_evidence_exact"] is True


def test_raw_signed_tx_path_with_private_key() -> None:
    w3 = Web3(EthereumTesterProvider(EthereumTester(PyEVMBackend())))
    funder = w3.eth.accounts[0]
    acct = Account.create()
    # Fund the ephemeral EOA so it can deploy and send transactions with explicit raw signing.
    deploy_contracts._send_tx(
        w3,
        {"to": acct.address, "value": w3.to_wei(2, "ether")},
        sender_address=funder,
    )

    compiled = compile_contract("D1", use_cache=True)
    factory = w3.eth.contract(abi=compiled.abi, bytecode=compiled.bytecode)
    safe_owner = w3.eth.accounts[4]
    rc_deploy = deploy_contracts._send_tx(
        w3,
        factory.constructor(safe_owner),
        sender_address=acct.address,
        private_key=acct.key.hex(),
        nonce=0,
    )
    contract = w3.eth.contract(address=rc_deploy.contractAddress, abi=compiled.abi)
    assert contract.functions.owner().call() == safe_owner
    assert contract.functions.threshold().call() == 2


def test_verify_on_etherscan_v2_payload_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_posts: list[dict[str, Any]] = []

    class FakeResp:
        def __init__(self, body: dict[str, Any]) -> None:
            self._body = body

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self._body

    def fake_post(url: str, *, params: dict[str, Any], data: dict[str, Any], timeout: int) -> FakeResp:
        captured_posts.append({"url": url, "params": params, "data": data, "timeout": timeout})
        return FakeResp({"status": "1", "result": "test-guid-123"})

    def fake_get(url: str, *, params: dict[str, Any], timeout: int) -> FakeResp:
        return FakeResp({"status": "1", "result": "Pass - Verified"})

    monkeypatch.setattr(verify_contracts.requests, "post", fake_post)
    monkeypatch.setattr(verify_contracts.requests, "get", fake_get)
    monkeypatch.setattr(verify_contracts.time, "sleep", lambda _: None)

    safe_owner = "0x1111111111111111111111111111111111111111"
    deployer = "0x2222222222222222222222222222222222222222"
    contract_info = {
        "contract_name": "RiskAttestationRegistry",
        "vyper_version": "0.4.3",
        "address": "0x3333333333333333333333333333333333333333",
        "owner": safe_owner,
        "deployer": deployer,
    }

    res = verify_contracts.verify_on_etherscan_v2(
        network="sepolia",
        variant="D1",
        contract_info=contract_info,
        api_key="dummy-key",
    )
    assert res["guid"] == "test-guid-123"
    assert res["status_response"]["status"] == "1"

    req = captured_posts[0]
    assert req["params"] == {
        "chainid": 11155111,
        "module": "contract",
        "action": "verifysourcecode",
        "apikey": "dummy-key",
    }
    assert req["data"]["codeformat"] == "vyper-json"
    assert req["data"]["compilerversion"] == "vyper:0.4.3"
    assert req["data"]["contractname"] == "contracts/RiskAttestationRegistry.vy:RiskAttestationRegistry"
    assert req["data"]["constructorArguments"] == encode(["address"], [safe_owner]).hex()
    assert "constructorArguements" not in req["data"]
    parsed_solc_json = json.loads(req["data"]["sourceCode"])
    assert parsed_solc_json["language"] == "Vyper"
    assert "contracts/RiskAttestationRegistry.vy" in parsed_solc_json["sources"]

    # Also ensure timeout string response does not crash downstream dict checks.
    monkeypatch.setattr(
        verify_contracts.requests,
        "get",
        lambda url, *, params, timeout: FakeResp({"status": "0", "result": "Pending in queue"}),
    )
    timeout_res = verify_contracts.verify_on_etherscan_v2(
        network="sepolia",
        variant="D1",
        contract_info=contract_info,
        api_key="dummy-key",
    )
    assert timeout_res["status_response"] == "pending_timeout"
