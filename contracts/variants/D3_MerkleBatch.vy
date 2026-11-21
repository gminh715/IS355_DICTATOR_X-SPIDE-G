# pragma version ^0.4.0

"""
@title RiskAttestationRegistry D3 (Merkle Batch Variant, v1.1)
@notice Amortized Merkle-root batch registration and k-of-n batch attestation
        for E5 cost comparison. Enforces per-batch threshold snapshotting,
        roster-nonce Sybil isolation, tie-safe quorum status evaluation, and
        permissionless revocation of removed auditors' votes on non-finalized
        batches. Each leaf is:
        keccak256(abi_encode(case_id, evidence_hash, model_version_hash)).
        Inclusion proofs use sorted-pair keccak256 hashing.
"""

DECISION_UNSET: public(constant(uint8)) = 0
DECISION_APPROVE: public(constant(uint8)) = 1
DECISION_REJECT: public(constant(uint8)) = 2
DECISION_NEEDS_REVIEW: public(constant(uint8)) = 3

STATUS_OPEN: public(constant(uint8)) = 0
STATUS_APPROVED: public(constant(uint8)) = 1
STATUS_REJECTED: public(constant(uint8)) = 2
STATUS_DISPUTED: public(constant(uint8)) = 3


struct Batch:
    n_leaves: uint256
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


event BatchRegistered:
    root: indexed(bytes32)
    n_leaves: uint256
    batch_uri: String[128]
    registrant: address


event BatchAttested:
    root: indexed(bytes32)
    auditor: indexed(address)
    decision: uint8
    revision: uint256


event BatchStatusChanged:
    root: indexed(bytes32)
    old_status: uint8
    new_status: uint8


event RemovedAuditorBatchVoteRevoked:
    root: indexed(bytes32)
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
batches: public(HashMap[bytes32, Batch])
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
def register_batch(root: bytes32, n_leaves: uint256, batch_uri: String[128]):
    self._only_auditor()
    assert root != empty(bytes32), "Zero root"
    assert n_leaves > 0, "Empty batch"
    assert self.batches[root].registrant == empty(address), "Batch already exists"

    self.batches[root] = Batch(
        n_leaves=n_leaves,
        registrant=msg.sender,
        created_at=block.timestamp,
        approve_count=0,
        reject_count=0,
        review_count=0,
        status=STATUS_OPEN,
        required_threshold=self.threshold,
        created_roster_nonce=self.roster_nonce,
    )

    log BatchRegistered(
        root=root,
        n_leaves=n_leaves,
        batch_uri=batch_uri,
        registrant=msg.sender,
    )


@external
def attest_batch(root: bytes32, decision: uint8):
    self._only_auditor()
    assert self.batches[root].registrant != empty(address), "Batch does not exist"
    assert (
        self.auditor_added_at[msg.sender] <= self.batches[root].created_roster_nonce
    ), "Auditor added after batch creation"
    assert (
        decision == DECISION_APPROVE
        or decision == DECISION_REJECT
        or decision == DECISION_NEEDS_REVIEW
    ), "Invalid decision"

    prev: Attestation = self.attestations[root][msg.sender]
    assert prev.decision != decision, "Same decision as current"

    if prev.decision == DECISION_APPROVE:
        self.batches[root].approve_count -= 1
    elif prev.decision == DECISION_REJECT:
        self.batches[root].reject_count -= 1
    elif prev.decision == DECISION_NEEDS_REVIEW:
        self.batches[root].review_count -= 1

    if decision == DECISION_APPROVE:
        self.batches[root].approve_count += 1
    elif decision == DECISION_REJECT:
        self.batches[root].reject_count += 1
    else:
        self.batches[root].review_count += 1

    new_revision: uint256 = prev.revision + 1
    self.attestations[root][msg.sender] = Attestation(
        decision=decision,
        revision=new_revision,
        timestamp=block.timestamp,
    )

    log BatchAttested(
        root=root,
        auditor=msg.sender,
        decision=decision,
        revision=new_revision,
    )

    old_status: uint8 = self.batches[root].status
    new_status: uint8 = self._compute_status(
        self.batches[root].approve_count,
        self.batches[root].reject_count,
        self.batches[root].required_threshold,
    )
    if new_status != old_status:
        self.batches[root].status = new_status
        log BatchStatusChanged(root=root, old_status=old_status, new_status=new_status)


@external
def revoke_removed_auditor_vote(root: bytes32, removed_auditor: address):
    assert self.batches[root].registrant != empty(address), "Batch does not exist"
    old_status: uint8 = self.batches[root].status
    assert (
        old_status == STATUS_OPEN or old_status == STATUS_DISPUTED
    ), "Batch already finalized"
    assert not self.is_auditor[removed_auditor], "Auditor is still active"

    prev: Attestation = self.attestations[root][removed_auditor]
    assert prev.decision != DECISION_UNSET, "No vote to revoke"

    if prev.decision == DECISION_APPROVE:
        self.batches[root].approve_count -= 1
    elif prev.decision == DECISION_REJECT:
        self.batches[root].reject_count -= 1
    elif prev.decision == DECISION_NEEDS_REVIEW:
        self.batches[root].review_count -= 1

    new_revision: uint256 = prev.revision + 1
    self.attestations[root][removed_auditor] = Attestation(
        decision=DECISION_UNSET,
        revision=new_revision,
        timestamp=block.timestamp,
    )

    log RemovedAuditorBatchVoteRevoked(
        root=root,
        auditor=removed_auditor,
        previous_decision=prev.decision,
        revision=new_revision,
        caller=msg.sender,
    )

    new_status: uint8 = self._compute_status(
        self.batches[root].approve_count,
        self.batches[root].reject_count,
        self.batches[root].required_threshold,
    )
    if new_status != old_status:
        self.batches[root].status = new_status
        log BatchStatusChanged(root=root, old_status=old_status, new_status=new_status)


@pure
@external
def compute_leaf(
    case_id: bytes32,
    evidence_hash: bytes32,
    model_version_hash: bytes32,
) -> bytes32:
    return keccak256(abi_encode(case_id, evidence_hash, model_version_hash))


@view
@external
def verify_inclusion(
    leaf: bytes32,
    proof: DynArray[bytes32, 32],
    root: bytes32,
) -> bool:
    if leaf == empty(bytes32) or self.batches[root].registrant == empty(address):
        return False

    computed: bytes32 = leaf
    for sibling: bytes32 in proof:
        if convert(computed, uint256) <= convert(sibling, uint256):
            computed = keccak256(concat(computed, sibling))
        else:
            computed = keccak256(concat(sibling, computed))
    return computed == root


@view
@external
def verify_case_inclusion(
    case_id: bytes32,
    evidence_hash: bytes32,
    model_version_hash: bytes32,
    proof: DynArray[bytes32, 32],
    root: bytes32,
) -> bool:
    if self.batches[root].registrant == empty(address):
        return False

    computed: bytes32 = keccak256(abi_encode(case_id, evidence_hash, model_version_hash))
    for sibling: bytes32 in proof:
        if convert(computed, uint256) <= convert(sibling, uint256):
            computed = keccak256(concat(computed, sibling))
        else:
            computed = keccak256(concat(sibling, computed))
    return computed == root


@view
@external
def get_batch(root: bytes32) -> Batch:
    return self.batches[root]


@view
@external
def get_attestation(root: bytes32, auditor: address) -> Attestation:
    return self.attestations[root][auditor]
