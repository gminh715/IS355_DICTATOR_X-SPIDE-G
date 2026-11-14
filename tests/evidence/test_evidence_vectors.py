"""Phase 6.1 unit tests for canonical evidence JSON, vectors.json, key order, and tamper detection."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

from src.evidence.canonical import (
    canonical_bytes,
    case_id_hex,
    compute_ipfs_cidv1_raw,
    evidence_hash_hex,
    format_decimal6,
    validate_evidence_dict,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
VECTORS_PATH = REPO_ROOT / "tests" / "evidence" / "vectors.json"


def _load_vectors() -> list[dict]:
    data = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
    return data["vectors"]


def test_vectors_json_has_three_valid_vectors_matching_hashes() -> None:
    vectors = _load_vectors()
    assert len(vectors) == 3

    for vec in vectors:
        ev = vec["evidence"]
        validate_evidence_dict(ev)
        raw = canonical_bytes(ev)
        assert raw.decode("utf-8") == vec["expected_canonical_json"]
        assert evidence_hash_hex(ev) == vec["expected_evidence_hash"]
        assert (
            case_id_hex(
                ev["source_chain_id"],
                ev["subject_address"],
                ev["model_version_hash"],
                ev["run_id"],
            )
            == vec["expected_case_id"]
        )
        assert compute_ipfs_cidv1_raw(raw) == vec["expected_ipfs_cidv1"]


def test_key_order_permutation_preserves_exact_hash_and_bytes() -> None:
    for vec in _load_vectors():
        original = vec["evidence"]
        orig_bytes = canonical_bytes(original)
        orig_hash = evidence_hash_hex(original)

        # Reverse top-level key insertion order AND reverse nested shap_top_k dict key order
        reversed_ev = {}
        for k in reversed(list(original.keys())):
            if k == "shap_top_k":
                reversed_ev[k] = [
                    {sk: item[sk] for sk in reversed(list(item.keys()))}
                    for item in original["shap_top_k"]
                ]
            else:
                reversed_ev[k] = original[k]

        assert canonical_bytes(reversed_ev) == orig_bytes
        assert evidence_hash_hex(reversed_ev) == orig_hash


def test_single_character_value_mutation_changes_evidence_hash() -> None:
    base = copy.deepcopy(_load_vectors()[2]["evidence"])
    base_hash = evidence_hash_hex(base)

    # Change 1 character in score ("0.873421" -> "0.873422")
    mutated_score = copy.deepcopy(base)
    mutated_score["score"] = "0.873422"
    assert evidence_hash_hex(mutated_score) != base_hash

    # Change 1 character in sample_id
    mutated_sample = copy.deepcopy(base)
    mutated_sample["sample_id"] = "boundary_test_9998"
    assert evidence_hash_hex(mutated_sample) != base_hash

    # Change 1 character in created_at_utc
    mutated_ts = copy.deepcopy(base)
    mutated_ts["created_at_utc"] = "2026-11-14T06:10:01Z"
    assert evidence_hash_hex(mutated_ts) != base_hash


def test_rejects_raw_floats_nan_infinity_and_invalid_formats() -> None:
    base = copy.deepcopy(_load_vectors()[2]["evidence"])

    with pytest.raises(ValueError, match="Non-finite"):
        format_decimal6(math.nan)
    with pytest.raises(ValueError, match="Non-finite"):
        format_decimal6(math.inf)

    bad_float = copy.deepcopy(base)
    bad_float["score"] = 0.873421  # raw float instead of 6-decimal string
    with pytest.raises(ValueError, match="Raw float"):
        canonical_bytes(bad_float)

    bad_dec = copy.deepcopy(base)
    bad_dec["score"] = "0.87"  # not 6 decimal places
    with pytest.raises(ValueError, match="6-decimal"):
        validate_evidence_dict(bad_dec)

    bad_addr = copy.deepcopy(base)
    bad_addr["subject_address"] = "0xABCDEF1111111111111111111111111111111111"  # uppercase
    with pytest.raises(ValueError, match="subject_address"):
        validate_evidence_dict(bad_addr)
