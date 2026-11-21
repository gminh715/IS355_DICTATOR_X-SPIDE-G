"""T12 Merkle batch & inclusion proof tests for D3_MerkleBatch.vy."""

from __future__ import annotations

import pytest
from eth_utils import keccak
from web3.logs import DISCARD

from src.contracts.merkle import MerkleTree, compute_leaf, verify_merkle_proof
from src.contracts.reference import (
    DECISION_APPROVE,
    DECISION_NEEDS_REVIEW,
    DECISION_REJECT,
    STATUS_APPROVED,
    STATUS_DISPUTED,
    STATUS_OPEN,
    STATUS_REJECTED,
)
from tests.contracts.conftest import ZERO_ADDRESS, ZERO_BYTES32, EvmContext, assert_reverts


def _make_batch(n_leaves: int, prefix: str = "b") -> tuple[list[tuple[bytes, bytes, bytes]], list[bytes], MerkleTree]:
    model_hash = keccak(b"baseline_v1")
    triples: list[tuple[bytes, bytes, bytes]] = []
    leaves: list[bytes] = []
    for i in range(n_leaves):
        cid = keccak(f"{prefix}-case-{i}".encode("utf-8"))
        eh = keccak(f"{prefix}-ev-{i}".encode("utf-8"))
        triples.append((cid, eh, model_hash))
        leaves.append(compute_leaf(cid, eh, model_hash))
    return triples, leaves, MerkleTree(leaves)


@pytest.mark.parametrize("n_leaves", [1, 5, 16, 100])
def test_t12_merkle_inclusion_valid_and_invalid_proofs(evm: EvmContext, n_leaves: int) -> None:
    c = evm.deploy_configured("D3", k=2)
    triples, leaves, tree = _make_batch(n_leaves, prefix=f"n{n_leaves}")
    root = tree.root

    # Python leaf construction matches Vyper pure compute_leaf
    cid0, eh0, mh0 = triples[0]
    assert c.functions.compute_leaf(cid0, eh0, mh0).call() == leaves[0]

    # Unregistered root returns False even with a mathematically valid proof
    proof0 = tree.get_proof(0)
    assert verify_merkle_proof(leaves[0], proof0, root) is True
    assert c.functions.verify_inclusion(leaves[0], proof0, root).call() is False

    # Register batch on-chain
    evm.send(c.functions.register_batch(root, n_leaves, f"ipfs://batch/{n_leaves}"), evm.auditors[0])

    # Verify every leaf on-chain for small batches, and boundary + mid indices for N=100
    check_indices = list(range(n_leaves)) if n_leaves <= 16 else [0, 1, 37, 64, 98, 99]
    for idx in check_indices:
        proof = tree.get_proof(idx)
        cid, eh, mh = triples[idx]
        assert c.functions.verify_inclusion(leaves[idx], proof, root).call() is True
        assert c.functions.verify_case_inclusion(cid, eh, mh, proof, root).call() is True

    # Invalid cases must return False
    tampered_leaf = bytes([leaves[0][0] ^ 0x01]) + leaves[0][1:]
    assert c.functions.verify_inclusion(tampered_leaf, proof0, root).call() is False
    assert c.functions.verify_inclusion(ZERO_BYTES32, proof0, root).call() is False

    if n_leaves > 1:
        tampered_proof = [bytes([proof0[0][0] ^ 0x01]) + proof0[0][1:]] + proof0[1:]
        assert c.functions.verify_inclusion(leaves[0], tampered_proof, root).call() is False
        assert c.functions.verify_inclusion(leaves[0], [], root).call() is False
        assert c.functions.verify_inclusion(leaves[1], proof0, root).call() is False
        cid1, eh1, mh1 = triples[1]
        assert c.functions.verify_case_inclusion(cid1, eh1, mh1, proof0, root).call() is False


def test_t12_d3_batch_governance_quorum_and_reverts(evm: EvmContext) -> None:
    c = evm.deploy_configured("D3", k=2)
    _, _, tree = _make_batch(4, prefix="gov")
    root = tree.root

    # Invalid registration inputs and role checks
    assert_reverts(
        lambda: evm.send(c.functions.register_batch(root, 4, "ipfs://b"), evm.outsider),
        "Only auditor",
    )
    assert_reverts(
        lambda: evm.send(c.functions.register_batch(root, 4, "ipfs://b"), evm.owner),
        "Only auditor",
    )
    assert_reverts(
        lambda: evm.send(c.functions.register_batch(ZERO_BYTES32, 4, "ipfs://b"), evm.auditors[0]),
        "Zero root",
    )
    assert_reverts(
        lambda: evm.send(c.functions.register_batch(root, 0, "ipfs://b"), evm.auditors[0]),
        "Empty batch",
    )
    assert_reverts(
        lambda: evm.send(c.functions.attest_batch(root, DECISION_APPROVE), evm.auditors[0]),
        "Batch does not exist",
    )

    rc_reg = evm.send(c.functions.register_batch(root, 4, "ipfs://batch/gov"), evm.auditors[0])
    reg_logs = c.events.BatchRegistered().process_receipt(rc_reg, errors=DISCARD)
    assert reg_logs[0]["args"]["root"] == root
    assert reg_logs[0]["args"]["n_leaves"] == 4

    assert_reverts(
        lambda: evm.send(c.functions.register_batch(root, 4, "ipfs://dup"), evm.auditors[1]),
        "Batch already exists",
    )

    # k=2 of n=3 batch attestation -> Open -> Disputed -> Approved (with replacement)
    evm.send(c.functions.attest_batch(root, DECISION_APPROVE), evm.auditors[0])
    assert c.functions.get_batch(root).call()[6] == STATUS_OPEN

    # Invalid decisions & duplicate same decision revert
    for bad_dec in (0, 4, 255):
        assert_reverts(
            lambda d=bad_dec: evm.send(c.functions.attest_batch(root, d), evm.auditors[1]),
            "Invalid decision",
        )
    assert_reverts(
        lambda: evm.send(c.functions.attest_batch(root, DECISION_APPROVE), evm.auditors[0]),
        "Same decision as current",
    )

    evm.send(c.functions.attest_batch(root, DECISION_REJECT), evm.auditors[1])
    assert c.functions.get_batch(root).call()[6] == STATUS_DISPUTED

    rc_flip = evm.send(c.functions.attest_batch(root, DECISION_APPROVE), evm.auditors[1])
    batch = c.functions.get_batch(root).call()
    att1 = c.functions.get_attestation(root, evm.auditors[1]).call()
    assert batch[3] == 2  # approve_count
    assert batch[4] == 0  # reject_count
    assert batch[6] == STATUS_APPROVED
    assert att1[1] == 2  # revision
    assert len(c.events.BatchStatusChanged().process_receipt(rc_flip, errors=DISCARD)) == 1

    # NeedsReview + Reject replacement -> Rejected
    evm.send(c.functions.attest_batch(root, DECISION_NEEDS_REVIEW), evm.auditors[0])
    evm.send(c.functions.attest_batch(root, DECISION_REJECT), evm.auditors[1])
    evm.send(c.functions.attest_batch(root, DECISION_REJECT), evm.auditors[2])
    assert c.functions.get_batch(root).call()[6] == STATUS_REJECTED
    evm.send(c.functions.attest_batch(root, DECISION_NEEDS_REVIEW), evm.auditors[2])
    assert c.functions.get_batch(root).call()[5] == 2  # review_count

    # Governance & T6 checks on D3 (owner cannot attest_batch, send ETH, or call any unlisted mutating fn)
    assert_reverts(
        lambda: evm.send(c.functions.attest_batch(root, DECISION_APPROVE), evm.owner),
        "Only auditor",
    )
    mutating_fns_d3 = {
        item["name"]
        for item in c.abi
        if item.get("type") == "function" and item.get("stateMutability") not in ("view", "pure")
    }
    assert mutating_fns_d3 == {
        "add_auditor",
        "remove_auditor",
        "set_threshold",
        "register_batch",
        "attest_batch",
        "revoke_removed_auditor_vote",
    }
    assert_reverts(lambda: evm.w3.eth.send_transaction({"from": evm.owner, "to": c.address, "value": 1}))
    assert_reverts(lambda: evm.send(c.functions.add_auditor(evm.owner), evm.owner), "Owner cannot be auditor")
    assert_reverts(lambda: evm.send(c.functions.add_auditor(ZERO_ADDRESS), evm.owner), "Zero address")
    assert_reverts(lambda: evm.send(c.functions.add_auditor(evm.auditors[0]), evm.owner), "Already auditor")
    assert_reverts(lambda: evm.send(c.functions.set_threshold(0), evm.owner), "Invalid threshold")
    assert_reverts(lambda: evm.send(c.functions.remove_auditor(evm.outsider), evm.owner), "Not an auditor")
    evm.send(c.functions.remove_auditor(evm.auditors[2]), evm.owner)
    assert_reverts(
        lambda: evm.send(c.functions.remove_auditor(evm.auditors[1]), evm.owner),
        "Auditor count below threshold",
    )
    assert c.functions.owner().call() != ZERO_ADDRESS
