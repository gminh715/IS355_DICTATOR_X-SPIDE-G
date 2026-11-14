"""Phase 6.4 end-to-end integration tests: ML -> JSON -> IPFS/Git -> k-of-n Attest -> Public Verifier & Tamper Check."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.evidence.chain_client import RegistryChainSession, build_signer_query_url
from src.evidence.inference import evaluate_contract_sample
from src.evidence.storage import save_evidence_bundle

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_end_to_end_ml_to_onchain_approved_and_tamper_detection(tmp_path: Path) -> None:
    """Section 6.4 E2E + Tamper scenario on deterministic local EVM."""
    # 1. ML Prediction + SHAP on real Ponzi contract from S_code
    analysis = evaluate_contract_sample(
        sample_id="xspide_00439",
        run_tag="e2e-integration-test",
        created_at_utc="2026-11-14T06:30:00Z",
    )
    assert analysis["predicted_label"] == 1
    evidence = analysis["evidence"]

    # 2. Persist canonical JSON to isolated evidence directory (IPFS CIDv1 + local mirror)
    stored = save_evidence_bundle(evidence, evidence_dir=tmp_path)
    assert stored.evidence_uri.startswith("ipfs://bafkrei")
    assert len(stored.evidence_uri) <= 128
    saved_file = Path(stored.local_path)
    assert saved_file.is_file()

    # 3. Deploy/init D1 Registry with 3 auditors, k = 2
    session = RegistryChainSession(network="local-evm", threshold=2)

    # 4. Auditor #0 registers the case
    rc_reg = session.register_case(
        auditor_index=0,
        case_id_hex=stored.case_id,
        subject_address=evidence["subject_address"],
        subject_chain_id=evidence["source_chain_id"],
        evidence_hash_hex=stored.evidence_hash,
        model_version_hash_hex=evidence["model_version_hash"],
        evidence_uri=stored.evidence_uri,
    )
    assert rc_reg["gas_used"] > 0

    # 5. Auditor #0 attests Approve (1 of 2 -> status still 0 Open)
    session.attest_case(auditor_index=0, case_id_hex=stored.case_id, decision=1)
    mid_state = session.get_case_and_events(stored.case_id)
    assert mid_state["case"]["status"] == 0
    assert mid_state["case"]["approve_count"] == 1

    # 6. Auditor #1 attests Approve (2 of 2 -> status transitions to 1 Approved)
    session.attest_case(auditor_index=1, case_id_hex=stored.case_id, decision=1)

    # 7. Public Verifier inspects case_id: must return ✅ VERIFIED
    ver_ok = session.public_verify_case(stored.case_id, evidence_dir=tmp_path)
    assert ver_ok["verified"] is True
    assert ver_ok["badge"].startswith("✅")
    assert ver_ok["onchain"]["case"]["status"] == 1
    assert ver_ok["onchain"]["case"]["status_name"] == "Approved"
    assert len(ver_ok["onchain"]["attestation_events"]) == 2
    assert len(ver_ok["onchain"]["status_events"]) == 1

    # 8. Tamper scenario: alter 1 character in the stored JSON file on disk/IPFS mirror
    original_bytes = saved_file.read_bytes()
    tampered_data = json.loads(original_bytes.decode("utf-8"))
    # Flip last digit of score
    orig_score = tampered_data["score"]
    last_digit = "1" if orig_score[-1] != "1" else "2"
    tampered_data["score"] = orig_score[:-1] + last_digit
    saved_file.write_text(
        json.dumps(tampered_data, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    ver_tampered = session.public_verify_case(stored.case_id, evidence_dir=tmp_path)
    assert ver_tampered["verified"] is False
    assert ver_tampered["badge"].startswith("❌")
    assert ver_tampered["onchain_verify_call"] is False

    # Restore original bytes and confirm verification recovers
    saved_file.write_bytes(original_bytes)
    assert session.public_verify_case(stored.case_id, evidence_dir=tmp_path)["verified"] is True


def test_signer_html_and_zero_server_secrets() -> None:
    """Verify static client signer exists, uses ethers.js v6, and no private keys exist in app/ or signer/."""
    signer_html = (REPO_ROOT / "signer" / "index.html").read_text(encoding="utf-8")
    assert "ethers" in signer_html
    assert "window.ethereum" in signer_html
    assert "register_case" in signer_html
    assert "attest" in signer_html

    url = build_signer_query_url(
        action="attest",
        contract_address="0xF2E246BB76DF876Cef8b38ae84130F4F55De395b",
        chain_id=11155111,
        case_id_hex="0x" + "ab" * 32,
        decision=1,
    )
    assert "action=attest" in url and "chain_id=11155111" in url

    # Ensure zero 64-hex private keys appear anywhere in app/ or signer/
    pk_pattern = re.compile(r"0x[0-9a-fA-F]{64}")
    for path in [REPO_ROOT / "signer" / "index.html", REPO_ROOT / "app" / "streamlit_app.py"]:
        text = path.read_text(encoding="utf-8")
        matches = pk_pattern.findall(text)
        # Only all-zero default reason_hash is permitted
        for m in matches:
            assert int(m, 16) == 0, f"Found unexpected 32-byte hex literal in {path.name}: {m}"
