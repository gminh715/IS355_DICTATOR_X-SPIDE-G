"""Pure-Python reference state machine for RiskAttestationRegistry (D1/D2)."""

from __future__ import annotations

from dataclasses import dataclass, field

DECISION_UNSET = 0
DECISION_APPROVE = 1
DECISION_REJECT = 2
DECISION_NEEDS_REVIEW = 3

STATUS_OPEN = 0
STATUS_APPROVED = 1
STATUS_REJECTED = 2
STATUS_DISPUTED = 3


def compute_status(approve_count: int, reject_count: int, threshold: int) -> int:
    """Mirror _compute_status from RiskAttestationRegistry.vy."""
    if approve_count >= threshold:
        return STATUS_APPROVED
    if reject_count >= threshold:
        return STATUS_REJECTED
    if approve_count >= 1 and reject_count >= 1:
        return STATUS_DISPUTED
    return STATUS_OPEN


@dataclass
class ReferenceAttestation:
    decision: int = DECISION_UNSET
    revision: int = 0


@dataclass
class ReferenceCase:
    subject: str
    subject_chain_id: int
    evidence_hash: bytes
    model_version_hash: bytes
    registrant: str
    approve_count: int = 0
    reject_count: int = 0
    review_count: int = 0
    status: int = STATUS_OPEN


@dataclass
class ReferenceRegistryState:
    """Exact off-chain mirror of RiskAttestationRegistry state transitions."""

    owner: str
    threshold: int = 2
    auditors: set[str] = field(default_factory=set)
    cases: dict[bytes, ReferenceCase] = field(default_factory=dict)
    attestations: dict[bytes, dict[str, ReferenceAttestation]] = field(default_factory=dict)

    @property
    def auditor_count(self) -> int:
        return len(self.auditors)

    def add_auditor(self, caller: str, auditor: str) -> None:
        if caller != self.owner:
            raise ValueError("Only owner")
        if int(auditor, 16) == 0:
            raise ValueError("Zero address")
        if auditor == self.owner:
            raise ValueError("Owner cannot be auditor")
        if auditor in self.auditors:
            raise ValueError("Already auditor")
        self.auditors.add(auditor)

    def remove_auditor(self, caller: str, auditor: str) -> None:
        if caller != self.owner:
            raise ValueError("Only owner")
        if auditor not in self.auditors:
            raise ValueError("Not an auditor")
        if len(self.auditors) - 1 < self.threshold:
            raise ValueError("Auditor count below threshold")
        self.auditors.remove(auditor)

    def set_threshold(self, caller: str, k: int) -> None:
        if caller != self.owner:
            raise ValueError("Only owner")
        if k < 1 or k > len(self.auditors):
            raise ValueError("Invalid threshold")
        self.threshold = k

    def register_case(
        self,
        caller: str,
        case_id: bytes,
        subject: str,
        subject_chain_id: int,
        evidence_hash: bytes,
        model_version_hash: bytes,
    ) -> None:
        if caller not in self.auditors:
            raise ValueError("Only auditor")
        if case_id == b"\x00" * 32:
            raise ValueError("Zero case_id")
        if int(subject, 16) == 0:
            raise ValueError("Zero subject")
        if evidence_hash == b"\x00" * 32:
            raise ValueError("Zero evidence_hash")
        if model_version_hash == b"\x00" * 32:
            raise ValueError("Zero model_version_hash")
        if case_id in self.cases:
            raise ValueError("Case already exists")

        self.cases[case_id] = ReferenceCase(
            subject=subject,
            subject_chain_id=subject_chain_id,
            evidence_hash=evidence_hash,
            model_version_hash=model_version_hash,
            registrant=caller,
        )
        self.attestations[case_id] = {}

    def attest(self, caller: str, case_id: bytes, decision: int) -> None:
        if caller not in self.auditors:
            raise ValueError("Only auditor")
        if case_id not in self.cases:
            raise ValueError("Case does not exist")
        if decision not in (DECISION_APPROVE, DECISION_REJECT, DECISION_NEEDS_REVIEW):
            raise ValueError("Invalid decision")

        case = self.cases[case_id]
        case_atts = self.attestations[case_id]
        prev = case_atts.get(caller, ReferenceAttestation())
        if prev.decision == decision:
            raise ValueError("Same decision as current")

        if prev.decision == DECISION_APPROVE:
            case.approve_count -= 1
        elif prev.decision == DECISION_REJECT:
            case.reject_count -= 1
        elif prev.decision == DECISION_NEEDS_REVIEW:
            case.review_count -= 1

        if decision == DECISION_APPROVE:
            case.approve_count += 1
        elif decision == DECISION_REJECT:
            case.reject_count += 1
        else:
            case.review_count += 1

        case_atts[caller] = ReferenceAttestation(decision=decision, revision=prev.revision + 1)
        case.status = compute_status(case.approve_count, case.reject_count, self.threshold)

    def assert_invariants(self, case_id: bytes) -> None:
        case = self.cases[case_id]
        non_zero = sum(1 for att in self.attestations[case_id].values() if att.decision != 0)
        assert case.approve_count + case.reject_count + case.review_count == non_zero
        assert case.status == compute_status(case.approve_count, case.reject_count, self.threshold)
