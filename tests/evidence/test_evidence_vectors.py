"""Unit tests for canonical evidence JSON, keccak256 hashing, ABI case_id, and IPFS/Git storage."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from eth_utils import keccak

from src.evidence.canonical import (
    build_evidence_bundle,
    canonical_bytes,
    case_id,
    case_id_hex,
    evidence_hash,
    evidence_hash_hex,
    format_decimal6,
    validate_evidence_bundle,
    verify_evidence_payload,
)
from src.evidence.storage import (
    compute_ipfs_cid_v1,
    fetch_evidence_bytes,
    persist_evidence_bundle,
)

VECTORS_PATH = Path(__file__).resolve().parent / "vectors.json"


def _load_vectors() -> list[dict]:
    return json.loads(VECTORS_PATH.read_text(encoding="utf-8"))["vectors"]


def test_vectors_canonical_hashes_and_case_ids_match() -> None:
    vectors = _load_vectors()
    assert len(vectors) == 3

    for vec in vectors:
        ev = vec["evidence"]
        assert validate_evidence_bundle(ev) == []
        raw = canonical_bytes(ev)
        assert raw.decode("utf-8") == vec["canonical_json"]
        assert evidence_hash_hex(ev) == vec["expected_evidence_hash"]
        assert evidence_hash(ev) == keccak(raw)

        cid = case_id_hex(
            ev["source_chain_id"],
            ev["subject_address"],
            ev["model_version_hash"],
            ev["run_id"],
        )
        assert cid == vec["expected_case_id"]
        assert len(case_id(ev["source_chain_id"], ev["subject_address"], ev["model_version_hash"], ev["run_id"])) == 32


def test_key_order_invariance_vs_one_byte_value_sensitivity() -> None:
    vec = _load_vectors()[0]
    ev = vec["evidence"]

    # Reverse top-level and nested shap_top_k key insertion order.
    reversed_top = {k: ev[k] for k in reversed(list(ev.keys()))}
    reversed_top["shap_top_k"] = [
        {sk: item[sk] for sk in reversed(list(item.keys()))}
        for item in ev["shap_top_k"]
    ]
    assert canonical_bytes(reversed_top) == canonical_bytes(ev)
    assert evidence_hash_hex(reversed_top) == vec["expected_evidence_hash"]

    # Mutate a single character in score and in shap_top_k -> hash MUST change.
    mutated_score = copy.deepcopy(ev)
    last_digit = "0" if mutated_score["score"][-1] != "0" else "1"
    mutated_score["score"] = mutated_score["score"][:-1] + last_digit
    assert evidence_hash_hex(mutated_score) != vec["expected_evidence_hash"]

    mutated_bytes = bytearray(canonical_bytes(ev))
    idx = mutated_bytes.index(b"0.912346")
    mutated_bytes[idx + 7] = ord("7")
    ok, diag = verify_evidence_payload(bytes(mutated_bytes), vec["expected_evidence_hash"])
    assert ok is False
    assert diag["raw_hash_matches"] is False


def test_rejects_nan_infinity_raw_floats_and_case_id_sensitivity() -> None:
    vec = copy.deepcopy(_load_vectors()[0]["evidence"])

    with pytest.raises(ValueError):
        format_decimal6(float("nan"))
    with pytest.raises(ValueError):
        format_decimal6(float("inf"))

    vec_raw_float = copy.deepcopy(vec)
    vec_raw_float["score"] = 0.912346
    with pytest.raises(ValueError):
        canonical_bytes(vec_raw_float)
    assert validate_evidence_bundle(vec_raw_float)

    # abi.encode collision resistance: shifting boundary between chain_id / subject / hashes changes case_id.
    cid_base = case_id_hex(1, vec["subject_address"], vec["model_version_hash"], vec["run_id"])
    cid_chain = case_id_hex(11155111, vec["subject_address"], vec["model_version_hash"], vec["run_id"])
    cid_run = case_id_hex(1, vec["subject_address"], vec["model_version_hash"], "0x" + "12" * 32)
    assert len({cid_base, cid_chain, cid_run}) == 3

    # Re-building with uppercase subject address normalizes cleanly.
    rebuilt = build_evidence_bundle(
        source_chain_id=vec["source_chain_id"],
        subject_address=vec["subject_address"].upper().replace("0X", "0x"),
        code_hash=vec["code_hash"],
        dataset_id=vec["dataset_id"],
        sample_id=vec["sample_id"],
        feature_schema_hash=vec["feature_schema_hash"],
        model_version_hash=vec["model_version_hash"],
        score=float(vec["score"]),
        threshold=float(vec["threshold"]),
        predicted_label=vec["predicted_label"],
        shap_top_k=vec["shap_top_k"],
        run_id=vec["run_id"],
        created_at_utc=vec["created_at_utc"],
    )
    assert evidence_hash_hex(rebuilt) == _load_vectors()[0]["expected_evidence_hash"]


def test_storage_persistence_cidv1_and_tamper_detection(tmp_path: Path) -> None:
    vec = _load_vectors()[0]
    ev = vec["evidence"]
    cid_case = vec["expected_case_id"]

    receipt = persist_evidence_bundle(
        ev,
        cid_case,
        evidence_dir=tmp_path / "evidence",
        repo_root=tmp_path,
        ipfs_api_url="",
        pinata_jwt="",
    )
    assert receipt.evidence_uri.startswith("ipfs://bafkrei")
    assert len(receipt.evidence_uri) <= 128
    assert receipt.cid == compute_ipfs_cid_v1(canonical_bytes(ev))
    assert receipt.pin_status == "local_content_addressed_unpinned"

    fetched, src = fetch_evidence_bytes(
        receipt.evidence_uri,
        case_id=cid_case,
        evidence_dir=tmp_path / "evidence",
        repo_root=tmp_path,
    )
    assert src.startswith("local_git_mirror:")
    ok, _ = verify_evidence_payload(fetched, receipt.evidence_hash)
    assert ok is True

    # Tamper 1 byte in stored file and re-verify.
    stored_file = tmp_path / "evidence" / f"{cid_case}.json"
    tampered = bytearray(stored_file.read_bytes())
    tampered[5] = ord("X") if tampered[5] != ord("X") else ord("Y")
    stored_file.write_bytes(bytes(tampered))

    fetched_bad, _ = fetch_evidence_bytes(
        receipt.evidence_uri,
        case_id=cid_case,
        evidence_dir=tmp_path / "evidence",
        repo_root=tmp_path,
    )
    ok_bad, diag_bad = verify_evidence_payload(fetched_bad, receipt.evidence_hash)
    assert ok_bad is False
    assert diag_bad["raw_hash_matches"] is False


def test_verify_evidence_payload_checks_subject_chain_model_and_case_id() -> None:
    vec = _load_vectors()[0]
    ev = vec["evidence"]
    raw = canonical_bytes(ev)
    eh = vec["expected_evidence_hash"]
    cid = vec["expected_case_id"]

    # Full match across hash + all 4 identity fields -> True
    ok_all, diag_all = verify_evidence_payload(
        raw,
        eh,
        expected_case_id_hex=cid,
        expected_subject=ev["subject_address"],
        expected_subject_chain_id=ev["source_chain_id"],
        expected_model_version_hash_hex=ev["model_version_hash"],
    )
    assert ok_all is True
    assert diag_all["identity_match"] is True
    assert diag_all["identity_errors"] == []

    # Hash matches, but on-chain subject is Contract A while JSON is Contract B -> False
    ok_subj, diag_subj = verify_evidence_payload(
        raw,
        eh,
        expected_case_id_hex=cid,
        expected_subject="0x000000000000000000000000000000000000dead",
        expected_subject_chain_id=ev["source_chain_id"],
        expected_model_version_hash_hex=ev["model_version_hash"],
    )
    assert ok_subj is False
    assert diag_subj["raw_hash_matches"] is True
    assert diag_subj["identity_match"] is False
    assert any("subject_address mismatch" in e for e in diag_subj["identity_errors"])

    # Hash matches, but chain_id, model_version_hash, or case_id mismatches -> False
    ok_chain, diag_chain = verify_evidence_payload(
        raw,
        eh,
        expected_case_id_hex="0x" + ("11" * 32),
        expected_subject=ev["subject_address"],
        expected_subject_chain_id=11155111,
        expected_model_version_hash_hex="0x" + ("22" * 32),
    )
    assert ok_chain is False
    assert len(diag_chain["identity_errors"]) == 3


def test_persist_evidence_bundle_prevents_accidental_overwrite(tmp_path: Path) -> None:
    vec = _load_vectors()[0]
    ev = copy.deepcopy(vec["evidence"])
    cid_case = vec["expected_case_id"]
    ev_dir = tmp_path / "evidence"

    r1 = persist_evidence_bundle(
        ev,
        cid_case,
        evidence_dir=ev_dir,
        repo_root=tmp_path,
        ipfs_api_url="",
        pinata_jwt="",
    )
    # Saving identical bytes is idempotent
    r2 = persist_evidence_bundle(
        ev,
        cid_case,
        evidence_dir=ev_dir,
        repo_root=tmp_path,
        ipfs_api_url="",
        pinata_jwt="",
    )
    assert r1.evidence_hash == r2.evidence_hash

    # Changing created_at_utc while keeping the same case_id must raise FileExistsError by default
    ev_changed = copy.deepcopy(ev)
    ev_changed["created_at_utc"] = "2026-12-31T23:59:59Z"
    with pytest.raises(FileExistsError):
        persist_evidence_bundle(
            ev_changed,
            cid_case,
            evidence_dir=ev_dir,
            repo_root=tmp_path,
            ipfs_api_url="",
            pinata_jwt="",
        )
