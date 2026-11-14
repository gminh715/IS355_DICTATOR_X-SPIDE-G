"""Phase 6 canonical evidence packaging, IPFS/Git storage, and on-chain verification helpers."""

from src.evidence.canonical import (
    SCHEMA_VERSION,
    build_evidence_bundle,
    canonical_bytes,
    case_id,
    case_id_hex,
    compute_ipfs_cidv1_raw,
    compute_shap_digest_hex,
    evidence_hash,
    evidence_hash_hex,
    format_decimal6,
    normalize_address,
    normalize_bytes32_hex,
    validate_evidence_dict,
)
from src.evidence.chain_client import (
    DECISION_NAMES,
    STATUS_NAMES,
    RegistryChainSession,
    build_signer_query_url,
)
from src.evidence.inference import evaluate_contract_sample, load_frozen_model_and_data
from src.evidence.storage import (
    StoredEvidence,
    load_and_recompute_evidence,
    save_evidence_bundle,
)

__all__ = [
    "DECISION_NAMES",
    "SCHEMA_VERSION",
    "STATUS_NAMES",
    "RegistryChainSession",
    "StoredEvidence",
    "build_evidence_bundle",
    "build_signer_query_url",
    "canonical_bytes",
    "case_id",
    "case_id_hex",
    "compute_ipfs_cidv1_raw",
    "compute_shap_digest_hex",
    "evaluate_contract_sample",
    "evidence_hash",
    "evidence_hash_hex",
    "format_decimal6",
    "load_and_recompute_evidence",
    "load_frozen_model_and_data",
    "normalize_address",
    "normalize_bytes32_hex",
    "save_evidence_bundle",
    "validate_evidence_dict",
]
