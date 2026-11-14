"""End-to-end Phase 6 integration tests: ML + SHAP -> JSON/IPFS -> D1 quorum -> Verifier & Tamper."""

from __future__ import annotations

import threading
from pathlib import Path

import requests
from web3 import Web3

from scripts.local_rpc_server import start_rpc_server
from src.evidence.canonical import (
    build_evidence_bundle,
    case_id_hex,
    evidence_hash_hex,
    verify_evidence_payload,
)
from src.evidence.chain_client import (
    build_signer_url,
    fetch_case_history,
    get_anvil_test_accounts,
    load_contract_abi,
    read_case,
    send_anvil_attest,
    send_anvil_register_case,
    verify_evidence_onchain,
)
from src.evidence.inference import (
    analyze_custom_bytecode,
    analyze_dataset_sample,
    load_baseline_model,
    load_s_code_catalog,
)
from src.evidence.storage import fetch_evidence_bytes, persist_evidence_bundle


def test_phase6_full_e2e_and_tamper_on_anvil_rpc_bridge(tmp_path: Path) -> None:
    server, bridge = start_rpc_server("127.0.0.1", 0, deploy_on_start=True)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        rpc_url = f"http://127.0.0.1:{port}"
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        assert w3.is_connected()
        assert w3.eth.chain_id == 31337

        # Verify GET status endpoint & CORS/signer URL formatting.
        health = requests.get(rpc_url, timeout=5).json()
        assert health["chain_id"] == 31337
        d1_addr = bridge.deployment_record["contracts"]["D1"]
        contract = w3.eth.contract(address=d1_addr, abi=load_contract_abi("D1"))

        # 1. Real ML + SHAP + CFG inference on an actual S_code Ponzi contract.
        model = load_baseline_model()
        df_s_code = load_s_code_catalog()
        ponzi_row = df_s_code[df_s_code["label"] == 1].iloc[0]
        analysis = analyze_dataset_sample(df_s_code, model, str(ponzi_row["sample_id"]))
        assert analysis.predicted_label in (0, 1)
        assert len(analysis.shap_top_k) == 10
        assert analysis.gsem_features["n_blocks"] >= 1

        # Also smoke-test custom bytecode path.
        custom_res = analyze_custom_bytecode(
            "0x000000000000000000000000000000000000cafe",
            analysis.stripped_bytecode_hex,
            model,
        )
        assert custom_res.account_features_imputed is True
        assert custom_res.code_hash == analysis.code_hash

        # 2. Canonical evidence JSON + CIDv1/Git mirror persistence.
        run_id = "0x" + ("ab" * 32)
        ev = build_evidence_bundle(
            source_chain_id=analysis.source_chain_id,
            subject_address=analysis.subject_address,
            code_hash=analysis.code_hash,
            dataset_id=analysis.dataset_id,
            sample_id=analysis.sample_id,
            feature_schema_hash=analysis.feature_schema_hash,
            model_version_hash=analysis.model_version_hash,
            score=analysis.score,
            threshold=analysis.threshold,
            predicted_label=analysis.predicted_label,
            shap_top_k=analysis.shap_top_k,
            run_id=run_id,
        )
        cid_case = case_id_hex(
            ev["source_chain_id"],
            ev["subject_address"],
            ev["model_version_hash"],
            ev["run_id"],
        )
        ev_hash = evidence_hash_hex(ev)

        ev_dir = tmp_path / "evidence"
        receipt = persist_evidence_bundle(
            ev,
            cid_case,
            evidence_dir=ev_dir,
            repo_root=tmp_path,
            ipfs_api_url="",
            pinata_jwt="",
        )
        assert receipt.evidence_hash == ev_hash

        # Verify client signer URL generation carries all parameters.
        signer_url = build_signer_url(
            "http://127.0.0.1:8502/index.html",
            action="register_case",
            chain_id=31337,
            contract_address=d1_addr,
            case_id_hex=cid_case,
            subject=ev["subject_address"],
            subject_chain_id=ev["source_chain_id"],
            evidence_hash_hex=ev_hash,
            model_version_hash_hex=ev["model_version_hash"],
            evidence_uri=receipt.evidence_uri,
            decision=1,
        )
        assert "case_id=" in signer_url and "evidence_uri=ipfs%3A%2F%2F" in signer_url

        # 3. Register case + 2-of-3 Approve attestations on D1 using Anvil test keys.
        anv = get_anvil_test_accounts(w3)
        rc_reg = send_anvil_register_case(
            w3,
            contract,
            anv["auditor_1"]["private_key"],
            case_id_hex=cid_case,
            subject=ev["subject_address"],
            subject_chain_id=ev["source_chain_id"],
            evidence_hash_hex=ev_hash,
            model_version_hash_hex=ev["model_version_hash"],
            evidence_uri=receipt.evidence_uri,
        )
        assert rc_reg["gas_used"] > 0

        rc_a1 = send_anvil_attest(
            w3,
            contract,
            anv["auditor_1"]["private_key"],
            case_id_hex=cid_case,
            decision=1,
            reason_text_or_hash="SHAP + CFG payout loop confirmed",
        )
        assert read_case(contract, cid_case)["status_label"] == "Open"

        rc_a2 = send_anvil_attest(
            w3,
            contract,
            anv["auditor_2"]["private_key"],
            case_id_hex=cid_case,
            decision=1,
            reason_text_or_hash="Second independent review concurs",
        )
        assert rc_a1["tx_hash"] != rc_a2["tx_hash"]

        final_case = read_case(contract, cid_case)
        assert final_case["status"] == 1
        assert final_case["status_label"] == "Approved"
        assert final_case["approve_count"] == 2

        history = fetch_case_history(w3, contract, cid_case, from_block=0)
        assert history["registered"]["evidence_uri"] == receipt.evidence_uri
        assert len(history["attestations"]) == 2
        assert len(history["status_changes"]) == 1

        # 4. Public verifier pass -> ✅
        raw_ok, _ = fetch_evidence_bytes(
            history["registered"]["evidence_uri"],
            case_id=cid_case,
            evidence_dir=ev_dir,
            repo_root=tmp_path,
        )
        ok_local, diag_ok = verify_evidence_payload(raw_ok, final_case["evidence_hash"])
        assert ok_local is True
        assert verify_evidence_onchain(contract, cid_case, diag_ok["recomputed_hash"]) is True

        # 5. Tamper test: mutate 1 byte of off-chain JSON -> ❌
        stored = ev_dir / f"{cid_case}.json"
        tampered = bytearray(stored.read_bytes())
        tampered[-2] = ord("X") if tampered[-2] != ord("X") else ord("Y")
        stored.write_bytes(bytes(tampered))

        raw_bad, _ = fetch_evidence_bytes(
            history["registered"]["evidence_uri"],
            case_id=cid_case,
            evidence_dir=ev_dir,
            repo_root=tmp_path,
        )
        ok_bad, diag_bad = verify_evidence_payload(raw_bad, final_case["evidence_hash"])
        assert ok_bad is False
        assert verify_evidence_onchain(contract, cid_case, diag_bad["recomputed_hash"]) is False
    finally:
        server.shutdown()
        server.server_close()
