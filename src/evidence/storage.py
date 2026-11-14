"""Off-chain evidence persistence: deterministic IPFS CIDv1, Kubo/Pinata pinning, and Git mirror."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from src.evidence.canonical import canonical_bytes, evidence_hash_hex, normalize_bytes32_hex

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = REPO_ROOT / "evidence"
CID_INDEX_PATH = EVIDENCE_DIR / "cid_index.json"


@dataclass(frozen=True)
class StorageReceipt:
    """Result of persisting canonical evidence JSON to IPFS and local Git mirror."""

    case_id: str
    evidence_hash: str
    cid: str
    evidence_uri: str
    git_rel_path: str
    git_commit: str
    backup_uri: str
    pin_status: str
    pin_detail: str
    byte_length: int


def compute_ipfs_cid_v1(raw_bytes: bytes) -> str:
    """Compute a standard IPFS CIDv1 (raw multicodec 0x55, sha2-256 multihash, base32lower)."""
    digest = hashlib.sha256(raw_bytes).digest()
    # CIDv1 (0x01) + raw codec (0x55) + sha2-256 (0x12) + 32-byte digest len (0x20)
    multihash_cid = b"\x01\x55\x12\x20" + digest
    b32 = base64.b32encode(multihash_cid).decode("ascii").lower().rstrip("=")
    return "b" + b32


def _git_commit_short(repo_root: Path = REPO_ROOT) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "uncommitted"


def _try_pin_kubo(raw_bytes: bytes, filename: str, api_url: str) -> tuple[bool, str, str]:
    """Attempt to add and pin raw bytes to a local Kubo IPFS node using CIDv1 raw-leaves."""
    endpoint = api_url.rstrip("/") + "/api/v0/add"
    try:
        resp = requests.post(
            endpoint,
            params={"pin": "true", "cid-version": "1", "raw-leaves": "true"},
            files={"file": (filename, raw_bytes, "application/json")},
            timeout=5,
        )
        resp.raise_for_status()
        payload = resp.json()
        kubo_cid = str(payload.get("Hash", "")).strip()
        if not kubo_cid:
            return False, "", "Kubo response missing Hash field"
        return True, kubo_cid, f"Pinned to Kubo node at {api_url}"
    except Exception as exc:
        return False, "", f"Kubo unreachable ({exc})"


def _try_pin_pinata(raw_bytes: bytes, filename: str, jwt: str) -> tuple[bool, str, str]:
    """Attempt to pin raw bytes via Pinata pinFileToIPFS API with CIDv1."""
    endpoint = "https://api.pinata.cloud/pinning/pinFileToIPFS"
    try:
        resp = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {jwt}"},
            files={"file": (filename, raw_bytes, "application/json")},
            data={"pinataOptions": json.dumps({"cidVersion": 1})},
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        cid = str(payload.get("IpfsHash", "")).strip()
        if not cid:
            return False, "", "Pinata response missing IpfsHash"
        return True, cid, "Pinned via Pinata API"
    except Exception as exc:
        return False, "", f"Pinata pin failed ({exc})"


def pin_evidence_bytes(
    raw_bytes: bytes,
    filename: str,
    *,
    ipfs_api_url: str | None = None,
    pinata_jwt: str | None = None,
) -> tuple[str, str, str]:
    """Compute CIDv1 and optionally pin to Kubo or Pinata.

    Returns ``(cid, pin_status, pin_detail)``. Never fabricates remote pin status.
    """
    local_cid = compute_ipfs_cid_v1(raw_bytes)
    kubo_url = (ipfs_api_url if ipfs_api_url is not None else os.environ.get("IPFS_API_URL", "http://127.0.0.1:5001")).strip()
    jwt = (pinata_jwt if pinata_jwt is not None else os.environ.get("PINATA_JWT", "")).strip()

    reasons: list[str] = []
    if kubo_url:
        ok, remote_cid, msg = _try_pin_kubo(raw_bytes, filename, kubo_url)
        if ok:
            if remote_cid != local_cid:
                reasons.append(f"Kubo returned {remote_cid}, keeping deterministic {local_cid}")
            return remote_cid, "pinned_kubo", msg
        reasons.append(msg)

    if jwt:
        ok, remote_cid, msg = _try_pin_pinata(raw_bytes, filename, jwt)
        if ok:
            return remote_cid, "pinned_pinata", msg
        reasons.append(msg)

    detail = "; ".join(reasons) if reasons else "No IPFS daemon or Pinata JWT configured"
    return local_cid, "local_content_addressed_unpinned", detail


def load_cid_index(index_path: Path = CID_INDEX_PATH) -> dict[str, Any]:
    """Load evidence/cid_index.json mapping CIDs and case_ids to Git mirror files."""
    if not index_path.is_file():
        return {"schema_version": "1.0", "entries": {}}
    return json.loads(index_path.read_text(encoding="utf-8"))


def _save_cid_index(index_data: dict[str, Any], index_path: Path = CID_INDEX_PATH) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(index_data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def persist_evidence_bundle(
    evidence: dict[str, Any],
    case_id: str,
    *,
    evidence_dir: Path = EVIDENCE_DIR,
    repo_root: Path = REPO_ROOT,
    ipfs_api_url: str | None = None,
    pinata_jwt: str | None = None,
) -> StorageReceipt:
    """Write canonical JSON bytes to Git mirror ``evidence/<case_id>.json`` and compute/pin IPFS CID."""
    cid_case = normalize_bytes32_hex(case_id)
    raw_bytes = canonical_bytes(evidence)
    ev_hash = evidence_hash_hex(evidence)

    evidence_dir.mkdir(parents=True, exist_ok=True)
    target_path = evidence_dir / f"{cid_case}.json"
    target_path.write_bytes(raw_bytes)

    cid, pin_status, pin_detail = pin_evidence_bytes(
        raw_bytes,
        target_path.name,
        ipfs_api_url=ipfs_api_url,
        pinata_jwt=pinata_jwt,
    )
    evidence_uri = f"ipfs://{cid}"
    if len(evidence_uri) > 128:
        raise ValueError(f"evidence_uri exceeds contract String[128] bound: len={len(evidence_uri)}")

    try:
        git_rel_path = target_path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        git_rel_path = target_path.as_posix()

    git_commit = _git_commit_short(repo_root)
    backup_uri = f"git://{git_commit}/{git_rel_path}"

    index_path = evidence_dir / "cid_index.json"
    index_data = load_cid_index(index_path)
    entries = index_data.setdefault("entries", {})
    entries[cid_case] = {
        "case_id": cid_case,
        "cid": cid,
        "evidence_uri": evidence_uri,
        "evidence_hash": ev_hash,
        "subject_address": evidence["subject_address"],
        "sample_id": evidence["sample_id"],
        "predicted_label": evidence["predicted_label"],
        "score": evidence["score"],
        "git_rel_path": git_rel_path,
        "git_commit": git_commit,
        "backup_uri": backup_uri,
        "pin_status": pin_status,
        "pin_detail": pin_detail,
        "updated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _save_cid_index(index_data, index_path)

    return StorageReceipt(
        case_id=cid_case,
        evidence_hash=ev_hash,
        cid=cid,
        evidence_uri=evidence_uri,
        git_rel_path=git_rel_path,
        git_commit=git_commit,
        backup_uri=backup_uri,
        pin_status=pin_status,
        pin_detail=pin_detail,
        byte_length=len(raw_bytes),
    )


def fetch_evidence_bytes(
    evidence_uri: str,
    *,
    case_id: str | None = None,
    evidence_dir: Path = EVIDENCE_DIR,
    repo_root: Path = REPO_ROOT,
    ipfs_gateway_url: str | None = None,
    ipfs_api_url: str | None = None,
) -> tuple[bytes, str]:
    """Retrieve raw evidence JSON bytes from local Git mirror, Kubo, IPFS gateway, or file/HTTP URI.

    Returns ``(raw_bytes, resolution_source)``.
    """
    uri = evidence_uri.strip()
    if uri.startswith("ipfs://"):
        cid = uri[len("ipfs://") :].strip().split("/")[0]
        index_path = evidence_dir / "cid_index.json"
        index_data = load_cid_index(index_path)
        entries = index_data.get("entries", {})

        # 1. Prefer matching Git mirror entry so local tamper tests are detected immediately.
        matched_rel: str | None = None
        if case_id:
            norm_cid = normalize_bytes32_hex(case_id)
            if norm_cid in entries and entries[norm_cid].get("cid") == cid:
                matched_rel = entries[norm_cid].get("git_rel_path")
        if matched_rel is None:
            for item in entries.values():
                if item.get("cid") == cid:
                    matched_rel = item.get("git_rel_path")
                    break

        if matched_rel:
            candidate = Path(matched_rel)
            if not candidate.is_absolute():
                candidate = repo_root / matched_rel
            if candidate.is_file():
                return candidate.read_bytes(), f"local_git_mirror:{matched_rel}"

        if case_id:
            direct_path = evidence_dir / f"{normalize_bytes32_hex(case_id)}.json"
            if direct_path.is_file():
                return direct_path.read_bytes(), f"local_case_file:{direct_path.name}"

        # 2. Try Kubo RPC /api/v0/cat
        kubo_url = (ipfs_api_url or os.environ.get("IPFS_API_URL", "http://127.0.0.1:5001")).strip()
        if kubo_url:
            try:
                resp = requests.post(
                    kubo_url.rstrip("/") + "/api/v0/cat",
                    params={"arg": cid},
                    timeout=4,
                )
                resp.raise_for_status()
                return resp.content, f"kubo_cat:{cid}"
            except Exception:
                pass

        # 3. Try configured HTTP IPFS gateway
        gw_base = (ipfs_gateway_url or os.environ.get("IPFS_GATEWAY_URL", "https://ipfs.io/ipfs")).strip()
        resp = requests.get(f"{gw_base.rstrip('/')}/{cid}", timeout=10)
        resp.raise_for_status()
        return resp.content, f"ipfs_gateway:{gw_base}/{cid}"

    if uri.startswith("git://"):
        # Format: git://<commit>/<rel_path>
        rest = uri[len("git://") :]
        parts = rest.split("/", 1)
        if len(parts) == 2:
            rel_path = parts[1]
            local_path = repo_root / rel_path
            if local_path.is_file():
                return local_path.read_bytes(), f"git_mirror:{rel_path}"
        raise FileNotFoundError(f"Git mirror URI not found locally: {uri}")

    if uri.startswith(("http://", "https://")):
        resp = requests.get(uri, timeout=10)
        resp.raise_for_status()
        return resp.content, f"http:{uri}"

    # Local path fallback
    local_p = Path(uri.removeprefix("file://"))
    if not local_p.is_absolute():
        local_p = repo_root / local_p
    if local_p.is_file():
        return local_p.read_bytes(), f"local_file:{local_p.as_posix()}"

    raise FileNotFoundError(f"Unable to retrieve evidence from URI: {evidence_uri}")
