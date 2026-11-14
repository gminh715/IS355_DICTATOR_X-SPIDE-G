"""Off-chain persistence (IPFS CIDv1 + optional Kubo/Pinata pin + Git mirror in evidence/)."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from src.evidence.canonical import (
    canonical_bytes,
    case_id_hex,
    compute_ipfs_cidv1_raw,
    evidence_hash_hex,
    normalize_bytes32_hex,
    validate_evidence_dict,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = REPO_ROOT / "evidence"


@dataclass(frozen=True)
class StoredEvidence:
    """Metadata returned when a canonical evidence bundle is persisted off-chain."""

    case_id: str
    evidence_hash: str
    cid: str
    evidence_uri: str
    git_fallback_uri: str
    local_path: str
    pin_status: str


def _git_commit_short() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
        ).strip()
    except Exception:
        return "working-tree"


def _try_pin_ipfs(raw_bytes: bytes, filename: str) -> tuple[str | None, str]:
    """Attempt to pin raw canonical bytes to a local Kubo daemon or Pinata if configured."""
    ipfs_api = os.environ.get("IPFS_API_URL", "").strip()
    if ipfs_api:
        try:
            resp = requests.post(
                f"{ipfs_api.rstrip('/')}/api/v0/add",
                params={"cid-version": "1", "raw-leaves": "true", "pin": "true"},
                files={"file": (filename, raw_bytes, "application/json")},
                timeout=5,
            )
            resp.raise_for_status()
            cid = resp.json().get("Hash")
            if cid:
                return str(cid), "pinned_kubo"
        except Exception:
            pass

    pinata_jwt = os.environ.get("PINATA_JWT", "").strip()
    if pinata_jwt:
        try:
            resp = requests.post(
                "https://api.pinata.cloud/pinning/pinFileToIPFS",
                headers={"Authorization": f"Bearer {pinata_jwt}"},
                files={"file": (filename, raw_bytes, "application/json")},
                data={"pinataOptions": json.dumps({"cidVersion": 1})},
                timeout=10,
            )
            resp.raise_for_status()
            cid = resp.json().get("IpfsHash")
            if cid:
                return str(cid), "pinned_pinata"
        except Exception:
            pass

    return None, "local_cidv1_and_git_mirror"


def save_evidence_bundle(
    evidence: dict[str, Any],
    *,
    evidence_dir: Path | None = None,
) -> StoredEvidence:
    """Validate and persist canonical JSON to `evidence/<case_id>.json` and compute IPFS URI."""
    validate_evidence_dict(evidence)
    raw = canonical_bytes(evidence)
    ev_hash = evidence_hash_hex(evidence)
    cid_val = case_id_hex(
        evidence["source_chain_id"],
        evidence["subject_address"],
        evidence["model_version_hash"],
        evidence["run_id"],
    )

    target_dir = evidence_dir if evidence_dir is not None else EVIDENCE_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / f"{cid_val}.json"
    file_path.write_bytes(raw)

    # Also write an index mapping ipfs CID -> case_id so local verifiers can resolve ipfs://<cid> offline
    computed_cid = compute_ipfs_cidv1_raw(raw)
    pinned_cid, pin_status = _try_pin_ipfs(raw, file_path.name)
    final_cid = pinned_cid or computed_cid

    cid_index_path = target_dir / "cid_index.json"
    cid_index: dict[str, str] = {}
    if cid_index_path.is_file():
        try:
            cid_index = json.loads(cid_index_path.read_text(encoding="utf-8"))
        except Exception:
            cid_index = {}
    cid_index[final_cid] = file_path.name
    cid_index_path.write_text(json.dumps(cid_index, indent=2, sort_keys=True), encoding="utf-8")

    commit_ref = _git_commit_short()
    rel_file = f"evidence/{file_path.name}"
    git_uri = f"git://{commit_ref}/{rel_file}"

    return StoredEvidence(
        case_id=cid_val,
        evidence_hash=ev_hash,
        cid=final_cid,
        evidence_uri=f"ipfs://{final_cid}",
        git_fallback_uri=git_uri,
        local_path=str(file_path),
        pin_status=pin_status,
    )


def load_and_recompute_evidence(
    *,
    case_id_value: str | None = None,
    evidence_uri: str | None = None,
    evidence_dir: Path | None = None,
) -> dict[str, Any]:
    """Load evidence JSON from local mirror or IPFS URI and recompute its keccak256 hash.

    Important: hashes BOTH the raw file bytes on disk and the re-canonicalized JSON dict
    so any tampering (even 1 byte) is immediately detected.
    """
    target_dir = evidence_dir if evidence_dir is not None else EVIDENCE_DIR
    candidate_path: Path | None = None

    if case_id_value:
        norm_cid = normalize_bytes32_hex(case_id_value, "case_id")
        p = target_dir / f"{norm_cid}.json"
        if p.is_file():
            candidate_path = p

    if candidate_path is None and evidence_uri:
        uri = evidence_uri.strip()
        if uri.startswith("ipfs://"):
            cid = uri[len("ipfs://") :].strip("/")
            cid_index_path = target_dir / "cid_index.json"
            if cid_index_path.is_file():
                idx_map = json.loads(cid_index_path.read_text(encoding="utf-8"))
                fname = idx_map.get(cid)
                if fname and (target_dir / fname).is_file():
                    candidate_path = target_dir / fname
        elif (target_dir / Path(uri).name).is_file():
            candidate_path = target_dir / Path(uri).name

    if candidate_path is None or not candidate_path.is_file():
        raise FileNotFoundError(
            f"Off-chain evidence file not found for case_id={case_id_value!r}, uri={evidence_uri!r}"
        )

    raw_file_bytes = candidate_path.read_bytes()
    from eth_utils import keccak

    raw_file_hash = "0x" + bytes(keccak(raw_file_bytes)).hex()
    parsed = json.loads(raw_file_bytes.decode("utf-8"))

    schema_valid = True
    schema_error = ""
    try:
        validate_evidence_dict(parsed)
        canonical_recomputed_hash = evidence_hash_hex(parsed)
    except Exception as exc:
        schema_valid = False
        schema_error = str(exc)
        canonical_recomputed_hash = raw_file_hash

    return {
        "path": str(candidate_path),
        "evidence": parsed,
        "raw_file_hash": raw_file_hash,
        "canonical_recomputed_hash": canonical_recomputed_hash,
        "is_canonical_byte_identical": (
            schema_valid and raw_file_bytes == canonical_bytes(parsed)
        ),
        "schema_valid": schema_valid,
        "schema_error": schema_error,
    }
