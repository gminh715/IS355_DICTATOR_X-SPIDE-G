"""Canonical JSON evidence schema, keccak256 hashing, and ABI-encoded case_id derivation."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any

from eth_abi import encode
from eth_utils import keccak

SCHEMA_VERSION = "1.0"

REQUIRED_EVIDENCE_FIELDS: tuple[str, ...] = (
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
)

_ADDRESS_RE = re.compile(r"^0x[0-9a-f]{40}$")
_BYTES32_RE = re.compile(r"^0x[0-9a-f]{64}$")
_DECIMAL6_RE = re.compile(r"^-?\d+\.\d{6}$")
_UTC_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def format_decimal6(value: float | int | str) -> str:
    """Format a finite numeric value as a fixed 6-decimal string (normalizing -0.000000)."""
    if isinstance(value, bool):
        raise ValueError("Boolean value cannot be formatted as decimal6")
    num = float(value)
    if not math.isfinite(num):
        raise ValueError(f"Non-finite numeric value is not allowed: {value!r}")
    formatted = f"{num:.6f}"
    return "0.000000" if formatted == "-0.000000" else formatted


def normalize_address(addr: str) -> str:
    """Normalize an EVM address to lowercase 0x-prefixed 40-hex-character form."""
    if not isinstance(addr, str):
        raise ValueError(f"Expected address string, got {type(addr).__name__}")
    norm = addr.strip().lower()
    if not _ADDRESS_RE.match(norm):
        raise ValueError(f"Invalid EVM address: {addr!r}")
    return norm


def normalize_bytes32_hex(val: bytes | str) -> str:
    """Normalize a 32-byte value or 0x-hex string to lowercase 0x + 64 hex chars."""
    if isinstance(val, (bytes, bytearray)):
        if len(val) != 32:
            raise ValueError(f"Expected 32 bytes, got {len(val)}")
        return "0x" + bytes(val).hex()
    if isinstance(val, str):
        s = val.strip().lower()
        if not s.startswith("0x"):
            s = "0x" + s
        if not _BYTES32_RE.match(s):
            raise ValueError(f"Invalid bytes32 hex string: {val!r}")
        return s
    raise ValueError(f"Expected bytes or hex string, got {type(val).__name__}")


def _to_bytes32(val: bytes | str) -> bytes:
    return bytes.fromhex(normalize_bytes32_hex(val)[2:])


def normalize_utc_timestamp(ts: datetime | str | None = None) -> str:
    """Normalize a datetime or ISO-8601 string to UTC YYYY-MM-DDTHH:MM:SSZ."""
    if ts is None:
        dt = datetime.now(timezone.utc)
    elif isinstance(ts, datetime):
        dt = ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    elif isinstance(ts, str):
        raw = ts.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        dt = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    else:
        raise ValueError(f"Unsupported timestamp type: {type(ts).__name__}")
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _assert_no_raw_floats(obj: Any, path: str = "$") -> None:
    """Reject raw Python floats (including NaN/Inf) to enforce string-encoded decimals."""
    if isinstance(obj, float):
        raise ValueError(
            f"Raw float at {path} ({obj!r}) is forbidden; encode real numbers as 6-decimal strings"
        )
    if isinstance(obj, dict):
        for k, v in obj.items():
            _assert_no_raw_floats(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            _assert_no_raw_floats(item, f"{path}[{idx}]")


def canonical_bytes(evidence: Any) -> bytes:
    """Serialize a canonical JSON object/array with strict deterministic formatting."""
    _assert_no_raw_floats(evidence)
    return json.dumps(
        evidence,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def compute_shap_digest(shap_top_k: list[dict[str, str]]) -> str:
    """Compute keccak256 digest over canonical JSON serialization of shap_top_k."""
    return "0x" + keccak(canonical_bytes(shap_top_k)).hex()


def evidence_hash(evidence: dict[str, Any]) -> bytes:
    """Compute keccak256(canonical_bytes(evidence)) as 32 raw bytes."""
    return keccak(canonical_bytes(evidence))


def evidence_hash_hex(evidence: dict[str, Any]) -> str:
    """Compute lowercase 0x-prefixed evidence_hash hex digest."""
    return "0x" + evidence_hash(evidence).hex()


def case_id(
    chain_id: int,
    subject: str,
    model_version_hash: bytes | str,
    run_id: bytes | str,
) -> bytes:
    """Derive deterministic bytes32 case_id via strict abi.encode (never encode_packed)."""
    if isinstance(chain_id, bool) or not isinstance(chain_id, int) or chain_id <= 0:
        raise ValueError(f"chain_id must be a positive integer, got {chain_id!r}")
    subj_norm = normalize_address(subject)
    mvh_bytes = _to_bytes32(model_version_hash)
    run_bytes = _to_bytes32(run_id)
    return keccak(
        encode(
            ["uint256", "address", "bytes32", "bytes32"],
            [chain_id, subj_norm, mvh_bytes, run_bytes],
        )
    )


def case_id_hex(
    chain_id: int,
    subject: str,
    model_version_hash: bytes | str,
    run_id: bytes | str,
) -> str:
    """Derive lowercase 0x-prefixed case_id hex string."""
    return "0x" + case_id(chain_id, subject, model_version_hash, run_id).hex()


def normalize_shap_top_k(
    entries: list[dict[str, Any]],
    *,
    max_items: int = 10,
) -> list[dict[str, str]]:
    """Normalize and deterministically sort top-k SHAP entries by |shap_value| desc."""
    if not entries:
        raise ValueError("shap_top_k must contain at least 1 entry")
    parsed: list[tuple[float, str, str, str]] = []
    for item in entries:
        feat = str(item["feature"]).strip()
        if not feat:
            raise ValueError("SHAP entry has empty feature name")
        val_str = format_decimal6(item["value"])
        sv_num = float(item["shap_value"])
        sv_str = format_decimal6(sv_num)
        parsed.append((abs(sv_num), feat, val_str, sv_str))

    parsed.sort(key=lambda tup: (-tup[0], tup[1]))
    return [
        {"feature": feat, "value": val_str, "shap_value": sv_str}
        for _, feat, val_str, sv_str in parsed[:max_items]
    ]


def build_evidence_bundle(
    *,
    source_chain_id: int,
    subject_address: str,
    code_hash: bytes | str,
    dataset_id: str,
    sample_id: str,
    feature_schema_hash: bytes | str,
    model_version_hash: bytes | str,
    score: float | str,
    threshold: float | str,
    predicted_label: int,
    shap_top_k: list[dict[str, Any]],
    run_id: bytes | str,
    created_at_utc: datetime | str | None = None,
    schema_version: str = SCHEMA_VERSION,
) -> dict[str, Any]:
    """Build and validate a schema-compliant canonical evidence dictionary."""
    if schema_version != SCHEMA_VERSION:
        raise ValueError(f"Unsupported schema_version: {schema_version!r}")
    if isinstance(source_chain_id, bool) or int(source_chain_id) <= 0:
        raise ValueError(f"source_chain_id must be positive, got {source_chain_id!r}")
    if isinstance(predicted_label, bool) or int(predicted_label) not in (0, 1):
        raise ValueError(f"predicted_label must be 0 or 1, got {predicted_label!r}")
    if not str(dataset_id).strip():
        raise ValueError("dataset_id must be non-empty")
    if not str(sample_id).strip():
        raise ValueError("sample_id must be non-empty")

    norm_shap = normalize_shap_top_k(shap_top_k, max_items=10)
    bundle: dict[str, Any] = {
        "schema_version": schema_version,
        "source_chain_id": int(source_chain_id),
        "subject_address": normalize_address(subject_address),
        "code_hash": normalize_bytes32_hex(code_hash),
        "dataset_id": str(dataset_id).strip(),
        "sample_id": str(sample_id).strip(),
        "feature_schema_hash": normalize_bytes32_hex(feature_schema_hash),
        "model_version_hash": normalize_bytes32_hex(model_version_hash),
        "score": format_decimal6(score),
        "threshold": format_decimal6(threshold),
        "predicted_label": int(predicted_label),
        "shap_top_k": norm_shap,
        "shap_digest": compute_shap_digest(norm_shap),
        "run_id": normalize_bytes32_hex(run_id),
        "created_at_utc": normalize_utc_timestamp(created_at_utc),
    }

    errors = validate_evidence_bundle(bundle)
    if errors:
        raise ValueError("Invalid evidence bundle: " + "; ".join(errors))
    return bundle


def validate_evidence_bundle(evidence: dict[str, Any]) -> list[str]:
    """Validate structure, formatting rules, and internal shap_digest consistency."""
    errors: list[str] = []
    if not isinstance(evidence, dict):
        return ["Evidence payload must be a JSON object"]

    missing = [f for f in REQUIRED_EVIDENCE_FIELDS if f not in evidence]
    if missing:
        errors.append(f"Missing required fields: {missing}")

    extra = sorted(set(evidence.keys()) - set(REQUIRED_EVIDENCE_FIELDS))
    if extra:
        errors.append(f"Unexpected extra fields: {extra}")

    try:
        _assert_no_raw_floats(evidence)
    except ValueError as exc:
        errors.append(str(exc))

    if evidence.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}")

    scid = evidence.get("source_chain_id")
    if isinstance(scid, bool) or not isinstance(scid, int) or scid <= 0:
        errors.append("source_chain_id must be a positive integer")

    subj = evidence.get("subject_address")
    if not isinstance(subj, str) or not _ADDRESS_RE.match(subj):
        errors.append("subject_address must be lowercase 0x + 40 hex chars")

    for hex_field in ("code_hash", "feature_schema_hash", "model_version_hash", "shap_digest", "run_id"):
        val = evidence.get(hex_field)
        if not isinstance(val, str) or not _BYTES32_RE.match(val):
            errors.append(f"{hex_field} must be lowercase 0x + 64 hex chars")

    for str_field in ("dataset_id", "sample_id"):
        val = evidence.get(str_field)
        if not isinstance(val, str) or not val.strip():
            errors.append(f"{str_field} must be a non-empty string")

    for dec_field in ("score", "threshold"):
        val = evidence.get(dec_field)
        if not isinstance(val, str) or not _DECIMAL6_RE.match(val):
            errors.append(f"{dec_field} must be a 6-decimal formatted string")

    lbl = evidence.get("predicted_label")
    if isinstance(lbl, bool) or lbl not in (0, 1):
        errors.append("predicted_label must be integer 0 or 1")

    ts = evidence.get("created_at_utc")
    if not isinstance(ts, str) or not _UTC_ISO_RE.match(ts):
        errors.append("created_at_utc must match YYYY-MM-DDTHH:MM:SSZ")

    shap_items = evidence.get("shap_top_k")
    if not isinstance(shap_items, list) or not (1 <= len(shap_items) <= 10):
        errors.append("shap_top_k must be a list of 1..10 items")
    else:
        for idx, item in enumerate(shap_items):
            if not isinstance(item, dict) or set(item.keys()) != {"feature", "value", "shap_value"}:
                errors.append(f"shap_top_k[{idx}] must have keys {{feature, value, shap_value}}")
                continue
            if not isinstance(item["feature"], str) or not item["feature"].strip():
                errors.append(f"shap_top_k[{idx}].feature must be non-empty string")
            for k in ("value", "shap_value"):
                if not isinstance(item[k], str) or not _DECIMAL6_RE.match(item[k]):
                    errors.append(f"shap_top_k[{idx}].{k} must be 6-decimal string")
        if not errors:
            expected_digest = compute_shap_digest(shap_items)
            if evidence.get("shap_digest") != expected_digest:
                errors.append(
                    f"shap_digest mismatch: got {evidence.get('shap_digest')}, expected {expected_digest}"
                )

    return errors


def verify_evidence_payload(
    raw_bytes: bytes,
    expected_hash_hex: str,
    *,
    expected_case_id_hex: str | None = None,
    expected_subject: str | None = None,
    expected_subject_chain_id: int | None = None,
    expected_model_version_hash_hex: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Verify raw JSON bytes against an on-chain evidence_hash, schema invariants, and optional case metadata."""
    expected_norm = normalize_bytes32_hex(expected_hash_hex)
    actual_hash = "0x" + keccak(raw_bytes).hex()
    raw_hash_matches = actual_hash == expected_norm

    diag: dict[str, Any] = {
        "expected_hash": expected_norm,
        "recomputed_hash": actual_hash,
        "raw_hash_matches": raw_hash_matches,
        "canonical_match": False,
        "identity_match": True,
        "derived_case_id": None,
        "schema_errors": [],
        "identity_errors": [],
        "evidence": None,
    }

    try:
        parsed = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        diag["schema_errors"] = [f"JSON/UTF-8 parse error: {exc}"]
        return False, diag

    diag["evidence"] = parsed
    schema_errors = validate_evidence_bundle(parsed)
    diag["schema_errors"] = schema_errors
    if not schema_errors:
        re_canon = canonical_bytes(parsed)
        diag["canonical_match"] = re_canon == raw_bytes
        diag["canonical_hash"] = "0x" + keccak(re_canon).hex()
        derived_cid = case_id_hex(
            int(parsed["source_chain_id"]),
            str(parsed["subject_address"]),
            str(parsed["model_version_hash"]),
            str(parsed["run_id"]),
        )
        diag["derived_case_id"] = derived_cid

        identity_errors: list[str] = []
        if expected_case_id_hex is not None:
            exp_cid = normalize_bytes32_hex(expected_case_id_hex)
            if derived_cid != exp_cid:
                identity_errors.append(
                    f"case_id mismatch: derived {derived_cid}, expected on-chain {exp_cid}"
                )
        if expected_subject is not None:
            exp_subj = normalize_address(expected_subject)
            if parsed["subject_address"] != exp_subj:
                identity_errors.append(
                    f"subject_address mismatch: JSON {parsed['subject_address']}, expected on-chain {exp_subj}"
                )
        if expected_subject_chain_id is not None:
            if int(parsed["source_chain_id"]) != int(expected_subject_chain_id):
                identity_errors.append(
                    f"source_chain_id mismatch: JSON {parsed['source_chain_id']}, expected on-chain {int(expected_subject_chain_id)}"
                )
        if expected_model_version_hash_hex is not None:
            exp_mvh = normalize_bytes32_hex(expected_model_version_hash_hex)
            if parsed["model_version_hash"] != exp_mvh:
                identity_errors.append(
                    f"model_version_hash mismatch: JSON {parsed['model_version_hash']}, expected on-chain {exp_mvh}"
                )
        diag["identity_errors"] = identity_errors
        diag["identity_match"] = len(identity_errors) == 0
    else:
        diag["canonical_match"] = False
        diag["identity_match"] = False

    verified = (
        raw_hash_matches
        and diag["canonical_match"]
        and len(schema_errors) == 0
        and diag["identity_match"]
    )
    return verified, diag
