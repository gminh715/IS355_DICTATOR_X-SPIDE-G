"""Verify 100% revert-branch coverage across D1, D2, and D3 Vyper contracts."""

from __future__ import annotations

import re
from pathlib import Path

from eth_utils import keccak

from src.contracts.compiler import CONTRACT_PATHS
from src.contracts.merkle import MerkleTree, compute_leaf
from src.contracts.reference import DECISION_APPROVE
from tests.contracts.conftest import ZERO_ADDRESS, ZERO_BYTES32, EvmContext, assert_reverts

ASSERT_MSG_RE = re.compile(r'assert\s+.+?,\s*"([^"]+)"', re.DOTALL)


def _extract_revert_reasons(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return set(ASSERT_MSG_RE.findall(text))


def test_every_revert_reason_triggered_across_d1_d2_d3(evm: EvmContext) -> None:
    """Exercise and record every single assert revert branch in D1, D2, and D3."""
    for variant in ("D1", "D2"):
        expected_reasons = _extract_revert_reasons(CONTRACT_PATHS[variant])
        observed: set[str] = set()

        def check(fn, reason: str) -> None:
            assert_reverts(fn, reason)
            observed.add(reason)

        c = evm.deploy_configured(variant, k=2)
        cid = keccak(f"cov-{variant}".encode())
        eh = keccak(b"cov-ev")
        mh = keccak(b"cov-mh")

        check(lambda: evm.send(c.functions.add_auditor(evm.extra_auditor), evm.outsider), "Only owner")
        check(lambda: evm.send(c.functions.add_auditor(ZERO_ADDRESS), evm.owner), "Zero address")
        check(lambda: evm.send(c.functions.add_auditor(evm.owner), evm.owner), "Owner cannot be auditor")
        check(lambda: evm.send(c.functions.add_auditor(evm.auditors[0]), evm.owner), "Already auditor")
        check(lambda: evm.send(c.functions.remove_auditor(evm.outsider), evm.owner), "Not an auditor")
        check(lambda: evm.send(c.functions.set_threshold(0), evm.owner), "Invalid threshold")

        evm.send(c.functions.remove_auditor(evm.auditors[2]), evm.owner)
        check(lambda: evm.send(c.functions.remove_auditor(evm.auditors[1]), evm.owner), "Auditor count below threshold")

        check(lambda: evm.send(c.functions.register_case(cid, evm.subject, 1, eh, mh, "ipfs://c"), evm.outsider), "Only auditor")
        check(lambda: evm.send(c.functions.register_case(ZERO_BYTES32, evm.subject, 1, eh, mh, "ipfs://c"), evm.auditors[0]), "Zero case_id")
        check(lambda: evm.send(c.functions.register_case(cid, ZERO_ADDRESS, 1, eh, mh, "ipfs://c"), evm.auditors[0]), "Zero subject")
        check(lambda: evm.send(c.functions.register_case(cid, evm.subject, 1, ZERO_BYTES32, mh, "ipfs://c"), evm.auditors[0]), "Zero evidence_hash")
        check(lambda: evm.send(c.functions.register_case(cid, evm.subject, 1, eh, ZERO_BYTES32, "ipfs://c"), evm.auditors[0]), "Zero model_version_hash")
        check(lambda: evm.send(c.functions.attest(cid, DECISION_APPROVE, ZERO_BYTES32), evm.auditors[0]), "Case does not exist")

        evm.send(c.functions.register_case(cid, evm.subject, 1, eh, mh, "ipfs://c"), evm.auditors[0])
        check(lambda: evm.send(c.functions.register_case(cid, evm.subject, 1, eh, mh, "ipfs://c"), evm.auditors[0]), "Case already exists")
        check(lambda: evm.send(c.functions.attest(cid, 0, ZERO_BYTES32), evm.auditors[0]), "Invalid decision")

        evm.send(c.functions.attest(cid, DECISION_APPROVE, ZERO_BYTES32), evm.auditors[0])
        check(lambda: evm.send(c.functions.attest(cid, DECISION_APPROVE, ZERO_BYTES32), evm.auditors[0]), "Same decision as current")

        assert observed == expected_reasons

    # D3 branch coverage
    expected_d3 = _extract_revert_reasons(CONTRACT_PATHS["D3"])
    observed_d3: set[str] = set()

    def check_d3(fn, reason: str) -> None:
        assert_reverts(fn, reason)
        observed_d3.add(reason)

    d3 = evm.deploy_configured("D3", k=2)
    leaf = compute_leaf(keccak(b"c"), keccak(b"e"), keccak(b"m"))
    root = MerkleTree([leaf]).root

    check_d3(lambda: evm.send(d3.functions.add_auditor(evm.extra_auditor), evm.outsider), "Only owner")
    check_d3(lambda: evm.send(d3.functions.add_auditor(ZERO_ADDRESS), evm.owner), "Zero address")
    check_d3(lambda: evm.send(d3.functions.add_auditor(evm.owner), evm.owner), "Owner cannot be auditor")
    check_d3(lambda: evm.send(d3.functions.add_auditor(evm.auditors[0]), evm.owner), "Already auditor")
    check_d3(lambda: evm.send(d3.functions.remove_auditor(evm.outsider), evm.owner), "Not an auditor")
    check_d3(lambda: evm.send(d3.functions.set_threshold(0), evm.owner), "Invalid threshold")

    evm.send(d3.functions.remove_auditor(evm.auditors[2]), evm.owner)
    check_d3(lambda: evm.send(d3.functions.remove_auditor(evm.auditors[1]), evm.owner), "Auditor count below threshold")

    check_d3(lambda: evm.send(d3.functions.register_batch(root, 1, "ipfs://b"), evm.outsider), "Only auditor")
    check_d3(lambda: evm.send(d3.functions.register_batch(ZERO_BYTES32, 1, "ipfs://b"), evm.auditors[0]), "Zero root")
    check_d3(lambda: evm.send(d3.functions.register_batch(root, 0, "ipfs://b"), evm.auditors[0]), "Empty batch")
    check_d3(lambda: evm.send(d3.functions.attest_batch(root, DECISION_APPROVE), evm.auditors[0]), "Batch does not exist")

    evm.send(d3.functions.register_batch(root, 1, "ipfs://b"), evm.auditors[0])
    check_d3(lambda: evm.send(d3.functions.register_batch(root, 1, "ipfs://b"), evm.auditors[0]), "Batch already exists")
    check_d3(lambda: evm.send(d3.functions.attest_batch(root, 99), evm.auditors[0]), "Invalid decision")
    evm.send(d3.functions.attest_batch(root, DECISION_APPROVE), evm.auditors[0])
    check_d3(lambda: evm.send(d3.functions.attest_batch(root, DECISION_APPROVE), evm.auditors[0]), "Same decision as current")

    # Rejects direct ETH transfers
    assert_reverts(lambda: evm.w3.eth.send_transaction({"from": evm.owner, "to": d3.address, "value": 1}))

    assert observed_d3 == expected_d3
