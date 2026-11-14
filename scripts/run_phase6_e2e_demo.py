"""Execute and record Phase 6.4 end-to-end + tamper verification against local Anvil RPC and check Sepolia."""

from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path

from web3 import Web3

from scripts.local_rpc_server import start_rpc_server
from src.evidence.canonical import (
    build_evidence_bundle,
    case_id_hex,
    evidence_hash_hex,
    verify_evidence_payload,
)
from src.evidence.chain_client import (
    connect_web3,
    fetch_case_history,
    get_anvil_test_accounts,
    get_registry_contract,
    load_contract_abi,
    read_case,
    send_anvil_attest,
    send_anvil_register_case,
    verify_evidence_onchain,
)
from src.evidence.inference import (
    analyze_dataset_sample,
    load_baseline_model,
    load_s_code_catalog,
)
from src.evidence.storage import EVIDENCE_DIR, fetch_evidence_bytes, persist_evidence_bundle


def run_demo(*, target_samples: list[str] | None = None, tamper_check: bool = True) -> dict:
    model = load_baseline_model()
    df_s_code = load_s_code_catalog()

    if not target_samples:
        ponzi_sid = str(df_s_code[df_s_code["label"] == 1].iloc[0]["sample_id"])
        non_ponzi_sid = str(df_s_code[df_s_code["label"] == 0].iloc[0]["sample_id"])
        target_samples = [ponzi_sid, non_ponzi_sid]

    server, bridge = start_rpc_server("127.0.0.1", 0, deploy_on_start=True)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    results = []
    try:
        w3 = Web3(Web3.HTTPProvider(f"http://127.0.0.1:{port}"))
        d1_addr = bridge.deployment_record["contracts"]["D1"]
        contract = w3.eth.contract(address=d1_addr, abi=load_contract_abi("D1"))
        anv = get_anvil_test_accounts(w3)

        for idx, sid in enumerate(target_samples):
            analysis = analyze_dataset_sample(df_s_code, model, sid)
            run_id = "0x" + f"{idx + 1:02x}" * 32
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
                created_at_utc="2026-11-14T09:00:00Z",
            )
            cid_case = case_id_hex(
                ev["source_chain_id"],
                ev["subject_address"],
                ev["model_version_hash"],
                ev["run_id"],
            )
            ev_hash = evidence_hash_hex(ev)
            receipt = persist_evidence_bundle(ev, cid_case)

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
            rc_a1 = send_anvil_attest(
                w3,
                contract,
                anv["auditor_1"]["private_key"],
                case_id_hex=cid_case,
                decision=1,
                reason_text_or_hash="Auditor 1 approves ML risk bundle",
            )
            rc_a2 = send_anvil_attest(
                w3,
                contract,
                anv["auditor_2"]["private_key"],
                case_id_hex=cid_case,
                decision=1,
                reason_text_or_hash="Auditor 2 approves ML risk bundle",
            )

            case_state = read_case(contract, cid_case)
            history = fetch_case_history(w3, contract, cid_case, from_block=0)
            raw_bytes, src = fetch_evidence_bytes(receipt.evidence_uri, case_id=cid_case)
            ok_local, diag_ok = verify_evidence_payload(raw_bytes, case_state["evidence_hash"])
            ok_onchain = verify_evidence_onchain(contract, cid_case, diag_ok["recomputed_hash"])

            tamper_result = None
            if tamper_check and idx == 0:
                tampered = bytearray(raw_bytes)
                tampered[-2] = ord("X") if tampered[-2] != ord("X") else ord("Y")
                bad_local, diag_bad = verify_evidence_payload(bytes(tampered), case_state["evidence_hash"])
                bad_onchain = verify_evidence_onchain(contract, cid_case, diag_bad["recomputed_hash"])
                tamper_result = {
                    "tampered_hash": diag_bad["recomputed_hash"],
                    "verified_local": bad_local,
                    "verified_onchain": bad_onchain,
                }

            results.append(
                {
                    "sample_id": sid,
                    "subject_address": ev["subject_address"],
                    "score": ev["score"],
                    "predicted_label": ev["predicted_label"],
                    "case_id": cid_case,
                    "evidence_hash": ev_hash,
                    "evidence_uri": receipt.evidence_uri,
                    "git_mirror_file": receipt.git_rel_path,
                    "pin_status": receipt.pin_status,
                    "register_gas_used": rc_reg["gas_used"],
                    "attest1_gas_used": rc_a1["gas_used"],
                    "attest2_gas_used": rc_a2["gas_used"],
                    "final_status": case_state["status_label"],
                    "attestation_events": len(history["attestations"]),
                    "fetch_source": src,
                    "verified_ok": ok_local and ok_onchain,
                    "tamper_check": tamper_result,
                }
            )
    finally:
        server.shutdown()
        server.server_close()

    sepolia_check = {}
    try:
        w3_sep = connect_web3("sepolia")
        sep_contract, sep_info = get_registry_contract(w3_sep, "sepolia", variant="D1")
        sepolia_check = {
            "connected": True,
            "address": sep_contract.address,
            "auditor_count": int(sep_contract.functions.auditor_count().call()),
            "threshold": int(sep_contract.functions.threshold().call()),
            "auditor_balances_eth": {
                aud: str(w3_sep.from_wei(w3_sep.eth.get_balance(aud), "ether"))
                for aud in sep_info.get("auditors", [])
            },
        }
    except Exception as exc:
        sepolia_check = {"connected": False, "error": str(exc)}

    return {"anvil_e2e": results, "sepolia_read_check": sepolia_check}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Phase 6 E2E demo & save evidence samples.")
    parser.add_argument("--samples", nargs="*", default=None)
    args = parser.parse_args()
    summary = run_demo(target_samples=args.samples)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
