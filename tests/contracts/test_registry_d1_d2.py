"""Contract tests T1-T10 across RiskAttestationRegistry (D1) and D2_EventOnly (D2)."""

from __future__ import annotations

import itertools
import json

import pytest
from eth_abi import encode
from eth_utils import keccak
from web3.logs import DISCARD

from src.contracts.reference import (
    DECISION_APPROVE,
    DECISION_NEEDS_REVIEW,
    DECISION_REJECT,
    STATUS_APPROVED,
    STATUS_DISPUTED,
    STATUS_OPEN,
    STATUS_REJECTED,
    compute_status,
)
from tests.contracts.conftest import (
    ZERO_ADDRESS,
    ZERO_BYTES32,
    EvmContext,
    assert_reverts,
    unpack_attestation,
    unpack_case,
)


def _sample_ids(tag: str = "case-1") -> tuple[bytes, bytes, bytes]:
    model_hash = keccak(b"baseline_v1_schema")
    evidence_hash = keccak(f"evidence-{tag}".encode("utf-8"))
    run_id = keccak(f"run-{tag}".encode("utf-8"))
    subject = "0x1111111111111111111111111111111111111111"
    case_id = keccak(encode(["uint256", "address", "bytes32", "bytes32"], [1, subject, model_hash, run_id]))
    return case_id, evidence_hash, model_hash


@pytest.mark.parametrize("variant", ["D1", "D2"])
def test_t1_non_auditor_cannot_register_or_attest(evm: EvmContext, variant: str) -> None:
    c = evm.deploy_configured(variant)
    cid, eh, mh = _sample_ids("t1")

    for bad_caller in (evm.outsider, evm.owner):
        assert_reverts(
            lambda bc=bad_caller: evm.send(
                c.functions.register_case(cid, evm.subject, 1, eh, mh, "ipfs://QmT1"), bc
            ),
            "Only auditor",
        )

    evm.send(c.functions.register_case(cid, evm.subject, 1, eh, mh, "ipfs://QmT1"), evm.auditors[0])
    for bad_caller in (evm.outsider, evm.owner):
        assert_reverts(
            lambda bc=bad_caller: evm.send(
                c.functions.attest(cid, DECISION_APPROVE, ZERO_BYTES32), bc
            ),
            "Only auditor",
        )


@pytest.mark.parametrize("variant", ["D1", "D2"])
def test_t2_duplicate_and_zero_case_inputs_revert(evm: EvmContext, variant: str) -> None:
    c = evm.deploy_configured(variant)
    cid, eh, mh = _sample_ids("t2")

    assert_reverts(
        lambda: evm.send(c.functions.register_case(ZERO_BYTES32, evm.subject, 1, eh, mh, "ipfs://z"), evm.auditors[0]),
        "Zero case_id",
    )
    assert_reverts(
        lambda: evm.send(c.functions.register_case(cid, ZERO_ADDRESS, 1, eh, mh, "ipfs://z"), evm.auditors[0]),
        "Zero subject",
    )
    assert_reverts(
        lambda: evm.send(c.functions.register_case(cid, evm.subject, 1, ZERO_BYTES32, mh, "ipfs://z"), evm.auditors[0]),
        "Zero evidence_hash",
    )
    assert_reverts(
        lambda: evm.send(c.functions.register_case(cid, evm.subject, 1, eh, ZERO_BYTES32, "ipfs://z"), evm.auditors[0]),
        "Zero model_version_hash",
    )

    evm.send(c.functions.register_case(cid, evm.subject, 1, eh, mh, "ipfs://QmT2"), evm.auditors[0])
    assert_reverts(
        lambda: evm.send(c.functions.register_case(cid, evm.subject, 1, eh, mh, "ipfs://QmT2-dup"), evm.auditors[1]),
        "Case already exists",
    )


@pytest.mark.parametrize("variant", ["D1", "D2"])
def test_t3_invalid_decisions_and_missing_case_revert(evm: EvmContext, variant: str) -> None:
    c = evm.deploy_configured(variant)
    cid, eh, mh = _sample_ids("t3")

    assert_reverts(
        lambda: evm.send(c.functions.attest(cid, DECISION_APPROVE, ZERO_BYTES32), evm.auditors[0]),
        "Case does not exist",
    )

    evm.send(c.functions.register_case(cid, evm.subject, 1, eh, mh, "ipfs://QmT3"), evm.auditors[0])
    for bad_decision in (0, 4, 255):
        assert_reverts(
            lambda d=bad_decision: evm.send(c.functions.attest(cid, d, ZERO_BYTES32), evm.auditors[0]),
            "Invalid decision",
        )


@pytest.mark.parametrize("variant", ["D1", "D2"])
def test_t4_quorum_sequences_k2_of_n3(evm: EvmContext, variant: str) -> None:
    # Exhaustively verify every 3-auditor decision sequence for k=2, n=3.
    decisions = (DECISION_APPROVE, DECISION_REJECT, DECISION_NEEDS_REVIEW)
    observed_statuses: set[int] = set()

    c = evm.deploy_configured(variant, k=2)
    for idx, seq in enumerate(itertools.product(decisions, repeat=3)):
        cid, eh, mh = _sample_ids(f"t4-{idx}")
        evm.send(c.functions.register_case(cid, evm.subject, 1, eh, mh, f"ipfs://QmT4/{idx}"), evm.auditors[0])

        approve_cnt = 0
        reject_cnt = 0
        review_cnt = 0
        for auditor, dec in zip(evm.auditors, seq):
            evm.send(c.functions.attest(cid, dec, ZERO_BYTES32), auditor)
            if dec == DECISION_APPROVE:
                approve_cnt += 1
            elif dec == DECISION_REJECT:
                reject_cnt += 1
            else:
                review_cnt += 1

            expected_status = compute_status(approve_cnt, reject_cnt, threshold=2)
            state = unpack_case(variant, c.functions.get_case(cid).call())
            assert state["approve_count"] == approve_cnt
            assert state["reject_count"] == reject_cnt
            assert state["review_count"] == review_cnt
            assert state["status"] == expected_status
            observed_statuses.add(expected_status)

    assert observed_statuses == {STATUS_OPEN, STATUS_APPROVED, STATUS_REJECTED, STATUS_DISPUTED}


@pytest.mark.parametrize("variant", ["D1", "D2"])
def test_t5_attestation_replacement_updates_revision_counts_and_status(evm: EvmContext, variant: str) -> None:
    c = evm.deploy_configured(variant, k=2)
    cid, eh, mh = _sample_ids("t5")
    evm.send(c.functions.register_case(cid, evm.subject, 1, eh, mh, "ipfs://QmT5"), evm.auditors[0])

    # Auditor 0 & 1 approve -> Approved (1)
    evm.send(c.functions.attest(cid, DECISION_APPROVE, ZERO_BYTES32), evm.auditors[0])
    evm.send(c.functions.attest(cid, DECISION_APPROVE, ZERO_BYTES32), evm.auditors[1])
    assert unpack_case(variant, c.functions.get_case(cid).call())["status"] == STATUS_APPROVED

    # Re-submitting identical decision must revert
    assert_reverts(
        lambda: evm.send(c.functions.attest(cid, DECISION_APPROVE, ZERO_BYTES32), evm.auditors[1]),
        "Same decision as current",
    )

    # Auditor 1 flips Approve -> Reject -> 1 Approve, 1 Reject -> Disputed (3), revision = 2
    evm.send(c.functions.attest(cid, DECISION_REJECT, keccak(b"flip-to-reject")), evm.auditors[1])
    case_mid = unpack_case(variant, c.functions.get_case(cid).call())
    att1 = unpack_attestation(variant, c.functions.get_attestation(cid, evm.auditors[1]).call())
    assert (case_mid["approve_count"], case_mid["reject_count"], case_mid["review_count"]) == (1, 1, 0)
    assert case_mid["status"] == STATUS_DISPUTED
    assert att1["decision"] == DECISION_REJECT
    assert att1["revision"] == 2

    # Auditor 0 flips Approve -> NeedsReview, Auditor 2 rejects -> Rejected (2), Auditor 0 revision = 2
    evm.send(c.functions.attest(cid, DECISION_NEEDS_REVIEW, keccak(b"needs-review")), evm.auditors[0])
    evm.send(c.functions.attest(cid, DECISION_REJECT, ZERO_BYTES32), evm.auditors[2])
    case_end = unpack_case(variant, c.functions.get_case(cid).call())
    att0 = unpack_attestation(variant, c.functions.get_attestation(cid, evm.auditors[0]).call())
    assert (case_end["approve_count"], case_end["reject_count"], case_end["review_count"]) == (0, 2, 1)
    assert case_end["status"] == STATUS_REJECTED
    assert att0["decision"] == DECISION_NEEDS_REVIEW
    assert att0["revision"] == 2


@pytest.mark.parametrize("variant", ["D1", "D2"])
def test_t6_owner_cannot_modify_cases_attestations_or_become_auditor(evm: EvmContext, variant: str) -> None:
    c = evm.deploy_configured(variant, k=2)
    cid, eh, mh = _sample_ids("t6")
    evm.send(c.functions.register_case(cid, evm.subject, 1, eh, mh, "ipfs://QmT6"), evm.auditors[0])
    evm.send(c.functions.attest(cid, DECISION_APPROVE, ZERO_BYTES32), evm.auditors[0])

    # Owner cannot enroll self as auditor
    assert_reverts(
        lambda: evm.send(c.functions.add_auditor(evm.owner), evm.owner),
        "Owner cannot be auditor",
    )

    # Owner cannot register cases or submit attestations
    assert_reverts(
        lambda: evm.send(c.functions.register_case(cid, evm.subject, 1, eh, mh, "ipfs://forged"), evm.owner),
        "Only auditor",
    )
    assert_reverts(
        lambda: evm.send(c.functions.attest(cid, DECISION_REJECT, ZERO_BYTES32), evm.owner),
        "Only auditor",
    )

    # Check ABI: no non-view mutating functions exist beyond governance + register_case + attest + revoke_removed_auditor_vote
    mutating_fns = {
        item["name"]
        for item in c.abi
        if item.get("type") == "function" and item.get("stateMutability") not in ("view", "pure")
    }
    assert mutating_fns == {
        "add_auditor",
        "remove_auditor",
        "set_threshold",
        "register_case",
        "attest",
        "revoke_removed_auditor_vote",
    }

    # Owner cannot revoke an active auditor's vote
    assert_reverts(
        lambda: evm.send(c.functions.revoke_removed_auditor_vote(cid, evm.auditors[0]), evm.owner),
        "Auditor is still active",
    )

    # Contract rejects direct ETH transfers (non-payable)
    assert_reverts(lambda: evm.w3.eth.send_transaction({"from": evm.owner, "to": c.address, "value": 1}))

    # Original case and attestation remain untouched
    assert c.functions.verify_evidence(cid, eh).call() is True
    assert unpack_attestation(variant, c.functions.get_attestation(cid, evm.auditors[0]).call())["decision"] == DECISION_APPROVE

    # Once finalized (Approved), even removing an auditor does not allow owner to revoke that historical vote
    evm.send(c.functions.attest(cid, DECISION_APPROVE, ZERO_BYTES32), evm.auditors[1])
    assert unpack_case(variant, c.functions.get_case(cid).call())["status"] == STATUS_APPROVED
    evm.send(c.functions.remove_auditor(evm.auditors[0]), evm.owner)
    assert_reverts(
        lambda: evm.send(c.functions.revoke_removed_auditor_vote(cid, evm.auditors[0]), evm.owner),
        "Case already finalized",
    )


@pytest.mark.parametrize("variant", ["D1", "D2"])
def test_t7_removed_auditor_blocked_but_prior_attestation_retained(evm: EvmContext, variant: str) -> None:
    c = evm.deploy_configured(variant, k=2)
    cid, eh, mh = _sample_ids("t7")
    evm.send(c.functions.register_case(cid, evm.subject, 1, eh, mh, "ipfs://QmT7"), evm.auditors[0])
    evm.send(c.functions.attest(cid, DECISION_APPROVE, ZERO_BYTES32), evm.auditors[0])

    # Remove auditor[0] (auditor_count 3 -> 2 >= k=2)
    evm.send(c.functions.remove_auditor(evm.auditors[0]), evm.owner)
    assert c.functions.is_auditor(evm.auditors[0]).call() is False
    assert c.functions.auditor_count().call() == 2

    # Removed auditor cannot register or attest anymore
    cid2, eh2, mh2 = _sample_ids("t7-2")
    assert_reverts(
        lambda: evm.send(c.functions.register_case(cid2, evm.subject, 1, eh2, mh2, "ipfs://x"), evm.auditors[0]),
        "Only auditor",
    )
    assert_reverts(
        lambda: evm.send(c.functions.attest(cid, DECISION_REJECT, ZERO_BYTES32), evm.auditors[0]),
        "Only auditor",
    )

    # Prior attestation and tally remain intact
    att0 = unpack_attestation(variant, c.functions.get_attestation(cid, evm.auditors[0]).call())
    case_state = unpack_case(variant, c.functions.get_case(cid).call())
    assert att0["decision"] == DECISION_APPROVE
    assert att0["revision"] == 1
    assert case_state["approve_count"] == 1


@pytest.mark.parametrize("variant", ["D1", "D2"])
def test_t8_verify_evidence_exact_vs_one_byte_tampered(evm: EvmContext, variant: str) -> None:
    c = evm.deploy_configured(variant, k=2)
    payload_ok = {"score": "0.873421", "subject": evm.subject.lower()}
    payload_tampered = {"score": "0.873422", "subject": evm.subject.lower()}

    bytes_ok = json.dumps(payload_ok, sort_keys=True, separators=(",", ":")).encode("utf-8")
    bytes_tampered = json.dumps(payload_tampered, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert sum(a != b for a, b in zip(bytes_ok, bytes_tampered)) == 1

    eh_ok = keccak(bytes_ok)
    eh_tampered = keccak(bytes_tampered)
    cid, _, mh = _sample_ids("t8")

    # Unregistered case must return False even for zero hash
    assert c.functions.verify_evidence(cid, ZERO_BYTES32).call() is False

    evm.send(c.functions.register_case(cid, evm.subject, 1, eh_ok, mh, "ipfs://QmT8"), evm.auditors[0])
    assert c.functions.verify_evidence(cid, eh_ok).call() is True
    assert c.functions.verify_evidence(cid, eh_tampered).call() is False
    assert c.functions.verify_evidence(cid, ZERO_BYTES32).call() is False


@pytest.mark.parametrize("variant", ["D1", "D2"])
def test_t9_events_emitted_with_exact_parameters(evm: EvmContext, variant: str) -> None:
    c, deploy_rc = evm.deploy(variant, initial_owner=evm.owner)
    init_logs = c.events.ThresholdChanged().process_receipt(deploy_rc, errors=DISCARD)
    assert len(init_logs) == 1
    assert init_logs[0]["args"]["old_threshold"] == 0
    assert init_logs[0]["args"]["new_threshold"] == 2

    rc_add = evm.send(c.functions.add_auditor(evm.auditors[0]), evm.owner)
    add_logs = c.events.AuditorAdded().process_receipt(rc_add, errors=DISCARD)
    assert len(add_logs) == 1 and add_logs[0]["args"]["auditor"] == evm.auditors[0]

    evm.send(c.functions.add_auditor(evm.auditors[1]), evm.owner)
    evm.send(c.functions.add_auditor(evm.auditors[2]), evm.owner)

    rc_thresh = evm.send(c.functions.set_threshold(3), evm.owner)
    thresh_logs = c.events.ThresholdChanged().process_receipt(rc_thresh, errors=DISCARD)
    assert thresh_logs[0]["args"]["old_threshold"] == 2
    assert thresh_logs[0]["args"]["new_threshold"] == 3

    rc_rem = evm.send(c.functions.set_threshold(2), evm.owner)
    assert c.events.ThresholdChanged().process_receipt(rc_rem, errors=DISCARD)[0]["args"]["new_threshold"] == 2

    cid, eh, mh = _sample_ids("t9")
    rc_reg = evm.send(c.functions.register_case(cid, evm.subject, 11155111, eh, mh, "ipfs://QmT9"), evm.auditors[0])
    reg_logs = c.events.CaseRegistered().process_receipt(rc_reg, errors=DISCARD)
    assert len(reg_logs) == 1
    reg_args = reg_logs[0]["args"]
    assert reg_args["case_id"] == cid
    assert reg_args["subject"] == evm.subject
    assert reg_args["evidence_hash"] == eh
    assert reg_args["model_version_hash"] == mh
    assert reg_args["evidence_uri"] == "ipfs://QmT9"
    assert reg_args["registrant"] == evm.auditors[0]

    reason_h = keccak(b"confirmed-ponzi-loop")
    rc_a1 = evm.send(c.functions.attest(cid, DECISION_APPROVE, reason_h), evm.auditors[0])
    att_logs = c.events.Attested().process_receipt(rc_a1, errors=DISCARD)
    assert len(att_logs) == 1
    assert att_logs[0]["args"]["case_id"] == cid
    assert att_logs[0]["args"]["auditor"] == evm.auditors[0]
    assert att_logs[0]["args"]["decision"] == DECISION_APPROVE
    assert att_logs[0]["args"]["revision"] == 1
    assert att_logs[0]["args"]["reason_hash"] == reason_h
    assert len(c.events.StatusChanged().process_receipt(rc_a1, errors=DISCARD)) == 0

    rc_a2 = evm.send(c.functions.attest(cid, DECISION_APPROVE, ZERO_BYTES32), evm.auditors[1])
    sc_logs = c.events.StatusChanged().process_receipt(rc_a2, errors=DISCARD)
    assert len(sc_logs) == 1
    assert sc_logs[0]["args"]["case_id"] == cid
    assert sc_logs[0]["args"]["old_status"] == STATUS_OPEN
    assert sc_logs[0]["args"]["new_status"] == STATUS_APPROVED

    rc_rm = evm.send(c.functions.remove_auditor(evm.auditors[2]), evm.owner)
    rm_logs = c.events.AuditorRemoved().process_receipt(rc_rm, errors=DISCARD)
    assert len(rm_logs) == 1 and rm_logs[0]["args"]["auditor"] == evm.auditors[2]


@pytest.mark.parametrize("variant", ["D1", "D2"])
def test_t10_admin_validation_and_threshold_bounds_revert(evm: EvmContext, variant: str) -> None:
    c = evm.deploy_configured(variant, k=2)

    # Non-owner admin calls revert
    assert_reverts(lambda: evm.send(c.functions.add_auditor(evm.extra_auditor), evm.outsider), "Only owner")
    assert_reverts(lambda: evm.send(c.functions.remove_auditor(evm.auditors[0]), evm.outsider), "Only owner")
    assert_reverts(lambda: evm.send(c.functions.set_threshold(1), evm.outsider), "Only owner")

    # Invalid add_auditor inputs
    assert_reverts(lambda: evm.send(c.functions.add_auditor(ZERO_ADDRESS), evm.owner), "Zero address")
    assert_reverts(lambda: evm.send(c.functions.add_auditor(evm.auditors[0]), evm.owner), "Already auditor")

    # Invalid threshold bounds (0 or > auditor_count=3)
    assert_reverts(lambda: evm.send(c.functions.set_threshold(0), evm.owner), "Invalid threshold")
    assert_reverts(lambda: evm.send(c.functions.set_threshold(4), evm.owner), "Invalid threshold")

    # Remove non-auditor reverts
    assert_reverts(lambda: evm.send(c.functions.remove_auditor(evm.outsider), evm.owner), "Not an auditor")

    # Removing down to k=2 works; removing below k=2 must revert
    evm.send(c.functions.remove_auditor(evm.auditors[2]), evm.owner)
    assert_reverts(
        lambda: evm.send(c.functions.remove_auditor(evm.auditors[1]), evm.owner),
        "Auditor count below threshold",
    )
