"""Canonical JSON serialization, validation, and cryptographic hashing for Phase 6 evidence."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any

from eth_abi import encode
from eth_utils import keccak

SCHEMA_VERSION = "1.0"

ADDRESS_RE = re.compile(r"^0x[0-9a-f]{40}$")
BYTES32_RE = re.compile(r"^0x[0-9a-f]{64}$")
DECIMAL6_RE = re.compile(r"^-?\d+\.\d{6}$")
ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

REQUIRED_EVIDENCE_KEYS = frozenset(
    {
        "schema_version",
        "source_chain_id",
        "subject_address",
        "code_hash",
        "dataset_id",
        "sample_id",
        "feature_schema_hash",
        "model_version_hash",
        "score",
        "threshold",
        "predicted_label",
        "shap_top_k",
        "shap_digest",
        "run_id",
        "created_at_utc",
    }
)

REQUIRED_SHAP_ITEM_KEYS = frozenset({"feature", "feature_value", "rank", "shap_value"})


def format_decimal6(value: float | int | str) -> str:
    """Format a finite numeric value as a fixed 6-decimal string, normalizing -0.000000 to 0.000000."""
    if isinstance(value, bool):
        raise ValueError("Boolean is not a valid numeric value for format_decimal6")
    num = float(value)
    if not math.isfinite(num):
        raise ValueError(f"Non-finite number not allowed in canonical evidence: {value!r}")
    if abs(num) < 5e-7:
        num = 0.0
    return f"{num:.6f}"


def normalize_address(address: str) -> str:
    """Return a validated lowercase 0x-prefixed 20-byte Ethereum address."""
    s = str(address).strip().lower()
    if not ADDRESS_RE.match(s):
        raise ValueError(f"Invalid Ethereum address (expected lowercase 0x + 40 hex chars): {address!r}")
    return s


def normalize_bytes32_hex(value: bytes | str, field_name: str = "hash") -> str:
    """Return a validated lowercase 0x-prefixed 32-byte hex string."""
    if isinstance(value, (bytes, bytearray)):
        if len(value) != 32:
            raise ValueError(f"{field_name} must be 32 bytes, got {len(value)}")
        return "0x" + bytes(value).hex()
    s = str(value).strip().lower()
    if not s.startswith("0x"):
        s = "0x" + s
    if not BYTES32_RE.match(s):
        raise ValueError(f"Invalid {field_name} (expected 0x + 64 hex chars): {value!r}")
    return s


def _to_bytes32(value: bytes | str, field_name: str = "hash") -> bytes:
    hex_str = normalize_bytes32_hex(value, field_name=field_name)
    return bytes.fromhex(hex_str[2:])


def _assert_no_raw_floats(obj: Any, path: str = "root") -> None:
    """Ensure no raw Python float or non-finite numbers appear anywhere in the canonical dict."""
    if isinstance(obj, float):
        raise ValueError(
            f"Raw float {obj!r} at {path} is forbidden; format as a 6-decimal string first."
        )
    if isinstance(obj, dict):
        for k, v in obj.items():
            _assert_no_raw_floats(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            _assert_no_raw_floats(item, f"{path}[{idx}]")


def canonical_bytes(evidence: dict[str, Any]) -> bytes:
    """Serialize a dictionary into canonical UTF-8 JSON bytes (sorted keys, compact separators)."""
    _assert_no_raw_floats(evidence)
    return json.dumps(
        evidence,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def evidence_hash(evidence: dict[str, Any]) -> bytes:
    """Compute 32-byte keccak256 digest of canonical_bytes(evidence)."""
    return bytes(keccak(canonical_bytes(evidence)))


def evidence_hash_hex(evidence: dict[str, Any]) -> str:
    """Return 0x-prefixed lowercase hex string of evidence_hash(evidence)."""
    return "0x" + evidence_hash(evidence).hex()


def case_id(
    chain_id: int,
    subject: str,
    model_version_hash: bytes | str,
    run_id: bytes | str,
) -> bytes:
    """Compute keccak256(abi.encode(uint256, address, bytes32, bytes32))."""
    if isinstance(chain_id, bool) or int(chain_id) <= 0:
        raise ValueError(f"chain_id must be a positive integer, got {chain_id!r}")
    norm_subject = normalize_address(subject)
    mvh_bytes = _to_bytes32(model_version_hash, "model_version_hash")
    run_bytes = _to_bytes32(run_id, "run_id")
    encoded = encode(
        ["uint256", "address", "bytes32", "bytes32"],
        [int(chain_id), norm_subject, mvh_bytes, run_bytes],
    )
    return bytes(keccak(encoded))


def case_id_hex(
    chain_id: int,
    subject: str,
    model_version_hash: bytes | str,
    run_id: bytes | str,
) -> str:
    """Return 0x-prefixed lowercase hex string of case_id(...)."""
    return "0x" + case_id(chain_id, subject, model_version_hash, run_id).hex()


def compute_shap_digest_hex(shap_top_k: list[dict[str, Any]]) -> str:
    """Compute 0x-prefixed keccak256 digest over canonical JSON of shap_top_k list."""
    _assert_no_raw_floats(shap_top_k, path="shap_top_k")
    raw = json.dumps(
        shap_top_k,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "0x" + bytes(keccak(raw)).hex()


def compute_ipfs_cidv1_raw(payload: bytes) -> str:
    """Compute deterministic IPFS CIDv1 (raw codec 0x55, sha2-256 multihash, base32lower 'b...')."""
    sha256_digest = hashlib.sha256(payload).digest()
    # CIDv1 = version(0x01) || codec_raw(0x55) || multihash_sha256(0x12) || len(0x20) || digest(32B)
    cid_bytes = b"\x01\x55\x12\x20" + sha256_digest
    b32 = base64.b32encode(cid_bytes).decode("ascii").lower().rstrip("=")
    return "b" + b32


def validate_evidence_dict(evidence: dict[str, Any]) -> None:
    """Strictly validate an evidence dictionary against schema_version 1.0 rules."""
    if not isinstance(evidence, dict):
        raise ValueError("Evidence payload must be a dict")
    _assert_no_raw_floats(evidence)

    keys = set(evidence.keys())
    if keys != REQUIRED_EVIDENCE_KEYS:
        missing = sorted(REQUIRED_EVIDENCE_KEYS - keys)
        extra = sorted(keys - REQUIRED_EVIDENCE_KEYS)
        raise ValueError(f"Evidence schema key mismatch: missing={missing}, extra={extra}")

    if evidence["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"Unsupported schema_version: {evidence['schema_version']!r}")

    if isinstance(evidence["source_chain_id"], bool) or not isinstance(evidence["source_chain_id"], int) or evidence["source_chain_id"] < 1:
        raise ValueError(f"Invalid source_chain_id: {evidence['source_chain_id']!r}")

    if not ADDRESS_RE.match(str(evidence["subject_address"])):
        raise ValueError(f"Invalid subject_address: {evidence['subject_address']!r}")

    for hash_key in ("code_hash", "feature_schema_hash", "model_version_hash", "shap_digest", "run_id"):
        if not BYTES32_RE.match(str(evidence[hash_key])):
            raise ValueError(f"Invalid {hash_key}: {evidence[hash_key]!r}")

    for str_key in ("dataset_id", "sample_id"):
        if not isinstance(evidence[str_key], str) or not evidence[str_key].strip():
            raise ValueError(f"{str_key} must be a non-empty string")

    for dec_key in ("score", "threshold"):
        val_str = str(evidence[dec_key])
        if not isinstance(evidence[dec_key], str) or not DECIMAL6_RE.match(val_str):
            raise ValueError(f"{dec_key} must be a 6-decimal string, got {evidence[dec_key]!r}")

    if isinstance(evidence["predicted_label"], bool) or evidence["predicted_label"] not in (0, 1):
        raise ValueError(f"predicted_label must be 0 or 1, got {evidence['predicted_label']!r}")

    if not isinstance(evidence["created_at_utc"], str) or not ISO_UTC_RE.match(evidence["created_at_utc"]):
        raise ValueError(f"created_at_utc must match YYYY-MM-DDTHH:MM:SSZ, got {evidence['created_at_utc']!r}")

    shap_list = evidence["shap_top_k"]
    if not isinstance(shap_list, list) or not (1 <= len(shap_list) <= 10):
        raise ValueError("shap_top_k must be a list of 1..10 items")

    for idx, item in enumerate(shap_list, start=1):
        if not isinstance(item, dict) or set(item.keys()) != REQUIRED_SHAP_ITEM_KEYS:
            raise ValueError(f"Invalid shap_top_k[{idx - 1}] keys: {item!r}")
        if not isinstance(item["feature"], str) or not item["feature"]:
            raise ValueError(f"Empty feature name in shap_top_k[{idx - 1}]")
        if item["rank"] != idx:
            raise ValueError(f"Expected rank={idx} in shap_top_k[{idx - 1}], got {item['rank']!r}")
        for num_field in ("feature_value", "shap_value"):
            if not isinstance(item[num_field], str) or not DECIMAL6_RE.match(item[num_field]):
                raise ValueError(
                    f"shap_top_k[{idx - 1}].{num_field} must be a 6-decimal string, got {item[num_field]!r}"
                )

    expected_shap_digest = compute_shap_digest_hex(shap_list)
    if evidence["shap_digest"] != expected_shap_digest:
        raise ValueError(
            f"shap_digest mismatch: expected {expected_shap_digest}, got {evidence['shap_digest']}"
        )


def build_evidence_bundle(
    *,
    subject_address: str,
    code_hash: str,
    sample_id: str,
    feature_schema_hash: str,
    model_version_hash: str,
    score: float | str,
    threshold: float | str,
    shap_items: list[dict[str, Any]],
    run_id: bytes | str,
    source_chain_id: int = 1,
    dataset_id: str = "xspide_s_code",
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    """Construct and validate a canonical v1.0 evidence dictionary."""
    score_str = format_decimal6(score)
    threshold_str = format_decimal6(threshold)
    pred_label = 1 if float(score_str) >= float(threshold_str) else 0

    normalized_shap: list[dict[str, Any]] = []
    # Sort by descending absolute SHAP value, tie-breaking by feature name ascending
    sorted_items = sorted(
        shap_items,
        key=lambda item: (-abs(float(item["shap_value"])), str(item["feature"])),
    )[:10]
    for rank_idx, item in enumerate(sorted_items, start=1):
        normalized_shap.append(
            {
                "feature": str(item["feature"]),
                "feature_value": format_decimal6(item["feature_value"]),
                "rank": rank_idx,
                "shap_value": format_decimal6(item["shap_value"]),
            }
        )

    shap_digest_hex = compute_shap_digest_hex(normalized_shap)
    ts = created_at_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    bundle: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source_chain_id": int(source_chain_id),
        "subject_address": normalize_address(subject_address),
        "code_hash": normalize_bytes32_hex(code_hash, "code_hash"),
        "dataset_id": str(dataset_id),
        "sample_id": str(sample_id),
        "feature_schema_hash": normalize_bytes32_hex(feature_schema_hash, "feature_schema_hash"),
        "model_version_hash": normalize_bytes32_hex(model_version_hash, "model_version_hash"),
        "score": score_str,
        "threshold": threshold_str,
        "predicted_label": pred_label,
        "shap_top_k": normalized_shap,
        "shap_digest": shap_digest_hex,
        "run_id": normalize_bytes32_hex(run_id, "run_id"),
        "created_at_utc": ts,
    }
    validate_evidence_dict(bundle)
    return bundle
