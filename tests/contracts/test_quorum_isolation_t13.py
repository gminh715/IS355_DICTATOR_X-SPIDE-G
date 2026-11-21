"""T13 Quorum isolation, Sybil rotation protection, vote revocation, and tie-safety across D1, D2, D3."""

from __future__ import annotations

import pytest
from eth_utils import keccak
from web3.logs import DISCARD

from src.contracts.merkle import MerkleTree, compute_leaf
from src.contracts.reference import (
    DECISION_APPROVE,
    DECISION_NEEDS_REVIEW,
    DECISION_REJECT,
    DECISION_UNSET,
    STATUS_APPROVED,
    STATUS_DISPUTED,
    STATUS_OPEN,
    STATUS_REJECTED,
)
from tests.contracts.conftest import (
    ZERO_BYTES32,
    EvmContext,
    assert_reverts,
    unpack_attestation,
    unpack_batch,
    unpack_case,
)


def _register_unit(evm: EvmContext, c, variant: str, tag: str, registrant: str) -> bytes:
    """Register a case (D1/D2) or Merkle batch (D3) and return its identifier (case_id or root)."""
    cid = keccak(f"t13-case-{variant}-{tag}".encode("utf-8"))
    eh = keccak(f"t13-ev-{variant}-{tag}".encode("utf-8"))
    mh = keccak(b"t13-model-v1")
    if variant in ("D1", "D2"):
        evm.send(c.functions.register_case(cid, evm.subject, 1, eh, mh, f"ipfs://t13/{tag}"), registrant)
        return cid
    leaf = compute_leaf(cid, eh, mh)
    root = MerkleTree([leaf]).root
    evm.send(c.functions.register_batch(root, 1, f"ipfs://t13/batch/{tag}"), registrant)
    return root


def _attest_unit(evm: EvmContext, c, variant: str, unit_id: bytes, decision: int, auditor: str):
    if variant in ("D1", "D2"):
        return evm.send(c.functions.attest(unit_id, decision, ZERO_BYTES32), auditor)
    return evm.send(c.functions.attest_batch(unit_id, decision), auditor)


def _get_unit(c, variant: str, unit_id: bytes) -> dict:
    if variant in ("D1", "D2"):
        return unpack_case(variant, c.functions.get_case(unit_id).call())
    return unpack_batch(c.functions.get_batch(unit_id).call())


def _get_att(c, variant: str, unit_id: bytes, auditor: str) -> dict:
    raw = c.functions.get_attestation(unit_id, auditor).call()
    if variant == "D2":
        return unpack_attestation("D2", raw)
    return unpack_attestation("D1", raw)


@pytest.mark.parametrize("variant", ["D1", "D2", "D3"])
def test_t13_quorum_rotation_sybil_and_tie_safety(evm: EvmContext, variant: str) -> None:
    """T13: Verify threshold snapshot, Sybil roster isolation, removed-auditor revocation, and tie safety."""
    c = evm.deploy_configured(variant, k=2)
    aud0, aud1, aud2 = evm.auditors
    aud3 = evm.extra_auditor

    # 1. Register case/batch at k=2, n=3 -> snapshots required_threshold=2 and created_roster_nonce=3
    assert c.functions.roster_nonce().call() == 3
    for idx, aud in enumerate(evm.auditors, start=1):
        assert c.functions.auditor_added_at(aud).call() == idx

    uid_old = _register_unit(evm, c, variant, "old", aud0)
    state_old = _get_unit(c, variant, uid_old)
    assert state_old["required_threshold"] == 2
    assert state_old["created_roster_nonce"] == 3
    assert state_old["status"] == STATUS_OPEN

    # 2. Owner lowers threshold to 1 and adds aud3 (Sybil attempt on pre-existing case)
    evm.send(c.functions.set_threshold(1), evm.owner)
    evm.send(c.functions.add_auditor(aud3), evm.owner)
    assert c.functions.threshold().call() == 1
    assert c.functions.roster_nonce().call() == 4
    assert c.functions.auditor_added_at(aud3).call() == 4

    # Pre-existing case retains required_threshold=2 and blocks newly added aud3
    assert _get_unit(c, variant, uid_old)["required_threshold"] == 2
    expected_sybil_msg = (
        "Auditor added after case creation" if variant in ("D1", "D2") else "Auditor added after batch creation"
    )
    assert_reverts(
        lambda: _attest_unit(evm, c, variant, uid_old, DECISION_APPROVE, aud3),
        expected_sybil_msg,
    )

    # 3. aud0 votes Approve & aud1 votes Reject on uid_old -> Disputed (1 vs 1 under k=2, NOT finalized)
    _attest_unit(evm, c, variant, uid_old, DECISION_APPROVE, aud0)
    assert _get_unit(c, variant, uid_old)["status"] == STATUS_OPEN  # 1 Approve < required_threshold=2
    _attest_unit(evm, c, variant, uid_old, DECISION_REJECT, aud1)
    assert _get_unit(c, variant, uid_old)["status"] == STATUS_DISPUTED

    # Remove aud0 -> revoking aud0's vote decrements approve_count to 0, resets decision, transitions Disputed -> Open
    evm.send(c.functions.remove_auditor(aud0), evm.owner)
    rc_rev = evm.send(c.functions.revoke_removed_auditor_vote(uid_old, aud0), evm.outsider)

    state_after_rev = _get_unit(c, variant, uid_old)
    att0_after_rev = _get_att(c, variant, uid_old, aud0)
    assert (state_after_rev["approve_count"], state_after_rev["reject_count"], state_after_rev["review_count"]) == (0, 1, 0)
    assert state_after_rev["status"] == STATUS_OPEN
    assert att0_after_rev["decision"] == DECISION_UNSET
    assert att0_after_rev["revision"] == 2

    if variant in ("D1", "D2"):
        rev_logs = c.events.RemovedAuditorVoteRevoked().process_receipt(rc_rev, errors=DISCARD)
        sc_logs = c.events.StatusChanged().process_receipt(rc_rev, errors=DISCARD)
        assert len(rev_logs) == 1
        assert rev_logs[0]["args"]["case_id"] == uid_old
        assert rev_logs[0]["args"]["auditor"] == aud0
        assert rev_logs[0]["args"]["previous_decision"] == DECISION_APPROVE
        assert rev_logs[0]["args"]["revision"] == 2
        assert rev_logs[0]["args"]["caller"] == evm.outsider
    else:
        rev_logs = c.events.RemovedAuditorBatchVoteRevoked().process_receipt(rc_rev, errors=DISCARD)
        sc_logs = c.events.BatchStatusChanged().process_receipt(rc_rev, errors=DISCARD)
        assert len(rev_logs) == 1
        assert rev_logs[0]["args"]["root"] == uid_old
        assert rev_logs[0]["args"]["auditor"] == aud0
        assert rev_logs[0]["args"]["previous_decision"] == DECISION_APPROVE
        assert rev_logs[0]["args"]["revision"] == 2
        assert rev_logs[0]["args"]["caller"] == evm.outsider

    assert len(sc_logs) == 1
    assert sc_logs[0]["args"]["old_status"] == STATUS_DISPUTED
    assert sc_logs[0]["args"]["new_status"] == STATUS_OPEN

    # Calling revoke a second time must revert
    assert_reverts(
        lambda: evm.send(c.functions.revoke_removed_auditor_vote(uid_old, aud0), evm.outsider),
        "No vote to revoke",
    )

    # Re-adding aud0 gives a higher roster_nonce (5 > 3), so aud0 STILL cannot vote on uid_old
    evm.send(c.functions.add_auditor(aud0), evm.owner)
    assert c.functions.auditor_added_at(aud0).call() == 5
    assert_reverts(
        lambda: _attest_unit(evm, c, variant, uid_old, DECISION_APPROVE, aud0),
        expected_sybil_msg,
    )

    # 4. Tie-safety at k=1: new case registered at threshold=1 allows aud3 (added at nonce 4 <= 5)
    uid_tie = _register_unit(evm, c, variant, "tie-k1", aud1)
    assert _get_unit(c, variant, uid_tie)["required_threshold"] == 1

    # Approve first -> Approved (1 >= 1), then Reject -> BOTH >= 1 -> MUST become Disputed (NOT Approved!)
    _attest_unit(evm, c, variant, uid_tie, DECISION_APPROVE, aud1)
    assert _get_unit(c, variant, uid_tie)["status"] == STATUS_APPROVED
    _attest_unit(evm, c, variant, uid_tie, DECISION_REJECT, aud3)
    tie_state = _get_unit(c, variant, uid_tie)
    assert (tie_state["approve_count"], tie_state["reject_count"]) == (1, 1)
    assert tie_state["status"] == STATUS_DISPUTED

    # Reverse order (Reject first, then Approve) must also resolve symmetrically to Disputed
    uid_tie_rev = _register_unit(evm, c, variant, "tie-k1-rev", aud2)
    _attest_unit(evm, c, variant, uid_tie_rev, DECISION_REJECT, aud2)
    assert _get_unit(c, variant, uid_tie_rev)["status"] == STATUS_REJECTED
    _attest_unit(evm, c, variant, uid_tie_rev, DECISION_APPROVE, aud3)
    assert _get_unit(c, variant, uid_tie_rev)["status"] == STATUS_DISPUTED


@pytest.mark.parametrize("variant", ["D1", "D2", "D3"])
def test_t13_revoke_reject_review_and_finalized_immutability(evm: EvmContext, variant: str) -> None:
    """Verify revocation across Reject/NeedsReview/tie-disputed states and immutability of finalized verdicts."""
    c = evm.deploy_configured(variant, k=2)
    aud0, aud1, aud2 = evm.auditors
    aud3 = evm.extra_auditor
    evm.send(c.functions.add_auditor(aud3), evm.owner)  # n=4, k=2

    # Case A: 2-vs-2 quorum tie (k=2, n=4) -> STATUS_DISPUTED; removing aud0 & revoking resolves to STATUS_REJECTED
    uid_a = _register_unit(evm, c, variant, "tie-k2-n4", aud0)
    _attest_unit(evm, c, variant, uid_a, DECISION_APPROVE, aud0)
    _attest_unit(evm, c, variant, uid_a, DECISION_APPROVE, aud1)
    assert _get_unit(c, variant, uid_a)["status"] == STATUS_APPROVED
    _attest_unit(evm, c, variant, uid_a, DECISION_REJECT, aud2)
    assert _get_unit(c, variant, uid_a)["status"] == STATUS_APPROVED  # 2 Approve >= 2, 1 Reject < 2
    _attest_unit(evm, c, variant, uid_a, DECISION_REJECT, aud3)
    assert _get_unit(c, variant, uid_a)["status"] == STATUS_DISPUTED  # 2 Approve >= 2 AND 2 Reject >= 2

    # Case B: NeedsReview and Reject votes on an Open case to cover all counter-decrement branches
    uid_b = _register_unit(evm, c, variant, "open-rev-branches", aud0)
    _attest_unit(evm, c, variant, uid_b, DECISION_NEEDS_REVIEW, aud0)
    _attest_unit(evm, c, variant, uid_b, DECISION_REJECT, aud1)
    assert _get_unit(c, variant, uid_b)["status"] == STATUS_OPEN

    # Case C: Finalized Approved case must reject vote revocation even after removing an auditor
    uid_c = _register_unit(evm, c, variant, "finalized-locked", aud0)
    _attest_unit(evm, c, variant, uid_c, DECISION_APPROVE, aud0)
    _attest_unit(evm, c, variant, uid_c, DECISION_APPROVE, aud1)
    assert _get_unit(c, variant, uid_c)["status"] == STATUS_APPROVED

    # Remove aud0 and aud1 (4 -> 3 -> 2 >= k=2)
    evm.send(c.functions.remove_auditor(aud0), evm.owner)
    evm.send(c.functions.remove_auditor(aud1), evm.owner)

    # On Case A (Disputed 2 vs 2): revoking aud0 (Approve) drops Approve to 1 -> Rejected (2 >= 2)
    evm.send(c.functions.revoke_removed_auditor_vote(uid_a, aud0), evm.outsider)
    st_a = _get_unit(c, variant, uid_a)
    assert (st_a["approve_count"], st_a["reject_count"], st_a["status"]) == (1, 2, STATUS_REJECTED)
    # Once Case A becomes Rejected (finalized), revoking aud1 must now revert
    finalized_msg = "Case already finalized" if variant in ("D1", "D2") else "Batch already finalized"
    assert_reverts(
        lambda: evm.send(c.functions.revoke_removed_auditor_vote(uid_a, aud1), evm.outsider),
        finalized_msg,
    )

    # On Case B (Open): revoking aud0 (NeedsReview) and aud1 (Reject) zeroes both counters cleanly
    evm.send(c.functions.revoke_removed_auditor_vote(uid_b, aud0), evm.outsider)
    evm.send(c.functions.revoke_removed_auditor_vote(uid_b, aud1), evm.outsider)
    st_b = _get_unit(c, variant, uid_b)
    assert (st_b["approve_count"], st_b["reject_count"], st_b["review_count"], st_b["status"]) == (
        0,
        0,
        0,
        STATUS_OPEN,
    )

    # On Case C (Finalized Approved): owner cannot revoke aud0's historical vote
    assert_reverts(
        lambda: evm.send(c.functions.revoke_removed_auditor_vote(uid_c, aud0), evm.owner),
        finalized_msg,
    )
    st_c = _get_unit(c, variant, uid_c)
    assert (st_c["approve_count"], st_c["status"]) == (2, STATUS_APPROVED)
