# pragma version ^0.4.0

"""
@title RiskAttestationRegistry (D1 - Full Storage, v1.1)
@notice Multi-auditor k-of-n Ponzi risk attestation registry for X-SPIDE-G.
@dev Enforces role separation (owner != auditor), per-case threshold snapshotting,
     roster-nonce Sybil isolation, tie-safe quorum status evaluation, and
     permissionless revocation of removed auditors' votes on non-finalized cases.
     No function permits editing or deleting registered cases, evidence hashes,
     or finalized verdicts.
"""

DECISION_UNSET: public(constant(uint8)) = 0
DECISION_APPROVE: public(constant(uint8)) = 1
DECISION_REJECT: public(constant(uint8)) = 2
DECISION_NEEDS_REVIEW: public(constant(uint8)) = 3

STATUS_OPEN: public(constant(uint8)) = 0
STATUS_APPROVED: public(constant(uint8)) = 1
STATUS_REJECTED: public(constant(uint8)) = 2
STATUS_DISPUTED: public(constant(uint8)) = 3


struct Case:
    subject: address
    subject_chain_id: uint256
    evidence_hash: bytes32
    model_version_hash: bytes32
    registrant: address
    created_at: uint256
    approve_count: uint256
    reject_count: uint256
    review_count: uint256
    status: uint8
    required_threshold: uint256
    created_roster_nonce: uint256


struct Attestation:
    decision: uint8
    revision: uint256
    timestamp: uint256


event AuditorAdded:
    auditor: indexed(address)


event AuditorRemoved:
    auditor: indexed(address)


event ThresholdChanged:
    old_threshold: uint256
    new_threshold: uint256


event CaseRegistered:
    case_id: indexed(bytes32)
    subject: indexed(address)
    evidence_hash: bytes32
    model_version_hash: bytes32
    evidence_uri: String[128]
    registrant: address


event Attested:
    case_id: indexed(bytes32)
    auditor: indexed(address)
    decision: uint8
    revision: uint256
    reason_hash: bytes32


event StatusChanged:
    case_id: indexed(bytes32)
    old_status: uint8
    new_status: uint8


event RemovedAuditorVoteRevoked:
    case_id: indexed(bytes32)
    auditor: indexed(address)
    previous_decision: uint8
    revision: uint256
    caller: address


owner: public(address)
is_auditor: public(HashMap[address, bool])
auditor_count: public(uint256)
threshold: public(uint256)
roster_nonce: public(uint256)
auditor_added_at: public(HashMap[address, uint256])
cases: public(HashMap[bytes32, Case])
attestations: public(HashMap[bytes32, HashMap[address, Attestation]])


@deploy
def __init__(initial_owner: address):
    if initial_owner == empty(address):
        self.owner = msg.sender
    else:
        self.owner = initial_owner
    self.threshold = 2
    log ThresholdChanged(old_threshold=0, new_threshold=2)


@internal
@view
def _only_owner():
    assert msg.sender == self.owner, "Only owner"


@internal
@view
def _only_auditor():
    assert self.is_auditor[msg.sender], "Only auditor"


@internal
@pure
def _compute_status(approve_count: uint256, reject_count: uint256, req_threshold: uint256) -> uint8:
    if approve_count >= req_threshold and reject_count >= req_threshold:
        return STATUS_DISPUTED
    elif approve_count >= req_threshold:
        return STATUS_APPROVED
    elif reject_count >= req_threshold:
        return STATUS_REJECTED
    elif approve_count >= 1 and reject_count >= 1:
        return STATUS_DISPUTED
    return STATUS_OPEN


@external
def add_auditor(a: address):
    self._only_owner()
    assert a != empty(address), "Zero address"
    assert a != self.owner, "Owner cannot be auditor"
    assert not self.is_auditor[a], "Already auditor"

    self.is_auditor[a] = True
    self.auditor_count += 1
    self.roster_nonce += 1
    self.auditor_added_at[a] = self.roster_nonce
    log AuditorAdded(auditor=a)


@external
def remove_auditor(a: address):
    self._only_owner()
    assert self.is_auditor[a], "Not an auditor"
    assert self.auditor_count - 1 >= self.threshold, "Auditor count below threshold"

    self.is_auditor[a] = False
    self.auditor_count -= 1
    log AuditorRemoved(auditor=a)


@external
def set_threshold(k: uint256):
    self._only_owner()
    assert k >= 1 and k <= self.auditor_count, "Invalid threshold"

    old_k: uint256 = self.threshold
    self.threshold = k
    log ThresholdChanged(old_threshold=old_k, new_threshold=k)


@external
def register_case(
    case_id: bytes32,
    subject: address,
    subject_chain_id: uint256,
    evidence_hash: bytes32,
    model_version_hash: bytes32,
    evidence_uri: String[128],
):
    self._only_auditor()
    assert case_id != empty(bytes32), "Zero case_id"
    assert subject != empty(address), "Zero subject"
    assert evidence_hash != empty(bytes32), "Zero evidence_hash"
    assert model_version_hash != empty(bytes32), "Zero model_version_hash"
    assert self.cases[case_id].registrant == empty(address), "Case already exists"

    self.cases[case_id] = Case(
        subject=subject,
        subject_chain_id=subject_chain_id,
        evidence_hash=evidence_hash,
        model_version_hash=model_version_hash,
        registrant=msg.sender,
        created_at=block.timestamp,
        approve_count=0,
        reject_count=0,
        review_count=0,
        status=STATUS_OPEN,
        required_threshold=self.threshold,
        created_roster_nonce=self.roster_nonce,
    )

    log CaseRegistered(
        case_id=case_id,
        subject=subject,
        evidence_hash=evidence_hash,
        model_version_hash=model_version_hash,
        evidence_uri=evidence_uri,
        registrant=msg.sender,
    )


@external
def attest(case_id: bytes32, decision: uint8, reason_hash: bytes32):
    self._only_auditor()
    assert self.cases[case_id].registrant != empty(address), "Case does not exist"
    assert (
        self.auditor_added_at[msg.sender] <= self.cases[case_id].created_roster_nonce
    ), "Auditor added after case creation"
    assert (
        decision == DECISION_APPROVE
        or decision == DECISION_REJECT
        or decision == DECISION_NEEDS_REVIEW
    ), "Invalid decision"

    prev: Attestation = self.attestations[case_id][msg.sender]
    assert prev.decision != decision, "Same decision as current"

    if prev.decision == DECISION_APPROVE:
        self.cases[case_id].approve_count -= 1
    elif prev.decision == DECISION_REJECT:
        self.cases[case_id].reject_count -= 1
    elif prev.decision == DECISION_NEEDS_REVIEW:
        self.cases[case_id].review_count -= 1

    if decision == DECISION_APPROVE:
        self.cases[case_id].approve_count += 1
    elif decision == DECISION_REJECT:
        self.cases[case_id].reject_count += 1
    else:
        self.cases[case_id].review_count += 1

    new_revision: uint256 = prev.revision + 1
    self.attestations[case_id][msg.sender] = Attestation(
        decision=decision,
        revision=new_revision,
        timestamp=block.timestamp,
    )

    log Attested(
        case_id=case_id,
        auditor=msg.sender,
        decision=decision,
        revision=new_revision,
        reason_hash=reason_hash,
    )

    old_status: uint8 = self.cases[case_id].status
    new_status: uint8 = self._compute_status(
        self.cases[case_id].approve_count,
        self.cases[case_id].reject_count,
        self.cases[case_id].required_threshold,
    )
    if new_status != old_status:
        self.cases[case_id].status = new_status
        log StatusChanged(case_id=case_id, old_status=old_status, new_status=new_status)


@external
def revoke_removed_auditor_vote(case_id: bytes32, removed_auditor: address):
    assert self.cases[case_id].registrant != empty(address), "Case does not exist"
    old_status: uint8 = self.cases[case_id].status
    assert (
        old_status == STATUS_OPEN or old_status == STATUS_DISPUTED
    ), "Case already finalized"
    assert not self.is_auditor[removed_auditor], "Auditor is still active"

    prev: Attestation = self.attestations[case_id][removed_auditor]
    assert prev.decision != DECISION_UNSET, "No vote to revoke"

    if prev.decision == DECISION_APPROVE:
        self.cases[case_id].approve_count -= 1
    elif prev.decision == DECISION_REJECT:
        self.cases[case_id].reject_count -= 1
    elif prev.decision == DECISION_NEEDS_REVIEW:
        self.cases[case_id].review_count -= 1

    new_revision: uint256 = prev.revision + 1
    self.attestations[case_id][removed_auditor] = Attestation(
        decision=DECISION_UNSET,
        revision=new_revision,
        timestamp=block.timestamp,
    )

    log RemovedAuditorVoteRevoked(
        case_id=case_id,
        auditor=removed_auditor,
        previous_decision=prev.decision,
        revision=new_revision,
        caller=msg.sender,
    )

    new_status: uint8 = self._compute_status(
        self.cases[case_id].approve_count,
        self.cases[case_id].reject_count,
        self.cases[case_id].required_threshold,
    )
    if new_status != old_status:
        self.cases[case_id].status = new_status
        log StatusChanged(case_id=case_id, old_status=old_status, new_status=new_status)


@view
@external
def verify_evidence(case_id: bytes32, h: bytes32) -> bool:
    return (
        self.cases[case_id].registrant != empty(address)
        and self.cases[case_id].evidence_hash == h
    )


@view
@external
def get_case(case_id: bytes32) -> Case:
    return self.cases[case_id]


@view
@external
def get_attestation(case_id: bytes32, auditor: address) -> Attestation:
    return self.attestations[case_id][auditor]
