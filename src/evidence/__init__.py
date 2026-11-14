"""Canonical evidence packaging, IPFS/Git storage, ML inference, and Web3 verification."""

from src.evidence.canonical import (
    REQUIRED_EVIDENCE_FIELDS,
    SCHEMA_VERSION,
    build_evidence_bundle,
    canonical_bytes,
    case_id,
    case_id_hex,
    compute_shap_digest,
    evidence_hash,
    evidence_hash_hex,
    format_decimal6,
    normalize_address,
    normalize_bytes32_hex,
    normalize_utc_timestamp,
    validate_evidence_bundle,
    verify_evidence_payload,
)

__all__ = [
    "REQUIRED_EVIDENCE_FIELDS",
    "SCHEMA_VERSION",
    "build_evidence_bundle",
    "canonical_bytes",
    "case_id",
    "case_id_hex",
    "compute_shap_digest",
    "evidence_hash",
    "evidence_hash_hex",
    "format_decimal6",
    "normalize_address",
    "normalize_bytes32_hex",
    "normalize_utc_timestamp",
    "validate_evidence_bundle",
    "verify_evidence_payload",
]
