"""4-Page X-SPIDE-G Streamlit DApp: Risk Analysis, Evidence Packaging, Signing & Public Verifier."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from web3 import Web3

from src.evidence.canonical import (
    build_evidence_bundle,
    canonical_bytes,
    case_id_hex,
    evidence_hash_hex,
    normalize_utc_timestamp,
    verify_evidence_payload,
)
from src.evidence.chain_client import (
    DECISION_LABELS,
    EXPLORER_TX_URLS,
    NETWORK_CHAIN_IDS,
    build_signer_url,
    compute_reason_hash,
    connect_web3,
    fetch_case_history,
    get_anvil_test_accounts,
    get_registry_contract,
    inspect_tx_receipt,
    list_registered_cases,
    load_deployments,
    read_case,
    read_registry_meta,
    send_anvil_attest,
    send_anvil_register_case,
    verify_evidence_onchain,
)
from src.evidence.inference import (
    RISK_DISCLAIMER,
    AnalysisResult,
    analyze_custom_bytecode,
    analyze_dataset_sample,
    fetch_bytecode_from_rpc,
    load_baseline_model,
    load_s_code_catalog,
    render_cfg_figure,
    render_shap_waterfall_figure,
    render_transition_graph_figure,
)
from src.evidence.storage import (
    EVIDENCE_DIR,
    fetch_evidence_bytes,
    load_cid_index,
    persist_evidence_bundle,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

st.set_page_config(
    page_title="X-SPIDE-G · Ponzi Risk Attestation",
    page_icon="🛡️",
    layout="wide",
)


@st.cache_resource
def _cached_model():
    return load_baseline_model()


@st.cache_data
def _cached_catalog() -> pd.DataFrame:
    return load_s_code_catalog()


@st.cache_data
def _cached_curated_samples(_df: pd.DataFrame) -> list[dict[str, Any]]:
    ponzis = _df[_df["label"] == 1].head(5)
    non_ponzis = _df[_df["label"] == 0].head(5)
    rows = []
    for _, r in pd.concat([ponzis, non_ponzis], ignore_index=True).iterrows():
        lbl = "Ponzi" if int(r["label"]) == 1 else "Non-Ponzi"
        rows.append(
            {
                "label": f"{r['sample_id']} · {r['address']} (Ground truth: {lbl})",
                "sample_id": str(r["sample_id"]),
                "address": str(r["address"]),
            }
        )
    return rows


def _init_session_state() -> None:
    defaults: dict[str, Any] = {
        "current_analysis": None,
        "current_evidence": None,
        "current_case_id": "",
        "current_evidence_hash": "",
        "current_evidence_uri": "",
        "current_storage_receipt": None,
        "last_run_id": "0x" + secrets.token_hex(32),
        "last_created_at_utc": normalize_utc_timestamp(),
        "last_tx_hashes": [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _render_sidebar() -> tuple[str, str | None, str]:
    st.sidebar.title("X-SPIDE-G DApp")
    st.sidebar.caption("Graph-Enhanced Explainable Ponzi Detection & k-of-n Attestation")

    page = st.sidebar.radio(
        "Điều hướng (4 trang)",
        [
            "1. Phân tích (Analysis)",
            "2. Tạo bằng chứng (Evidence)",
            "3. Ký & gửi giao dịch (Sign & Submit)",
            "4. Kiểm chứng công khai (Verifier)",
        ],
    )

    st.sidebar.divider()
    network = st.sidebar.selectbox(
        "Mạng blockchain mục tiêu",
        ["anvil", "sepolia", "arbitrum-sepolia"],
        index=0,
    )
    custom_rpc = st.sidebar.text_input(
        "RPC URL tùy chỉnh (để trống = dùng .env)",
        value="",
        placeholder="http://127.0.0.1:8545",
    ).strip() or None
    signer_base_url = st.sidebar.text_input(
        "URL trang ký tĩnh (ethers.js)",
        value=os.environ.get("SIGNER_BASE_URL", "http://127.0.0.1:8502/index.html"),
    ).strip()

    try:
        dep = load_deployments()
        d1_info = dep.get("networks", {}).get(network, {}).get("contracts", {}).get("D1", {})
        if d1_info:
            st.sidebar.markdown(
                f"**D1 Registry (`{network}`):**  \n`{d1_info.get('address')}`  \n"
                f"Quorum: `{d1_info.get('threshold', 2)}`-of-`{d1_info.get('auditor_count', 3)}`"
            )
    except Exception as exc:
        st.sidebar.warning(f"Không đọc được deployments.json: {exc}")

    return page, custom_rpc, signer_base_url, network  # type: ignore[return-value]


def _render_page_1_analysis(model: Any, df_s_code: pd.DataFrame) -> None:
    st.header("1. Phân tích rủi ro Smart Contract (LightGBM + SHAP + CFG)")
    st.warning(RISK_DISCLAIMER)

    mode = st.radio(
        "Nguồn dữ liệu phân tích",
        ["Chọn mẫu từ tập S_code (hoặc nhập địa chỉ / sample_id)", "Bytecode runtime tùy chỉnh / Fetch qua RPC"],
        horizontal=True,
    )

    analysis: AnalysisResult | None = st.session_state.get("current_analysis")

    if mode.startswith("Chọn mẫu"):
        curated = _cached_curated_samples(df_s_code)
        col_a, col_b = st.columns([2, 1])
        with col_a:
            preset_labels = [c["label"] for c in curated]
            selected_idx = st.selectbox("Mẫu tiêu biểu trong S_code", range(len(preset_labels)), format_func=lambda i: preset_labels[i])
        with col_b:
            manual_ident = st.text_input(
                "Hoặc nhập địa chỉ (0x...) / sample_id",
                value="",
                placeholder="xspide_00000 hoặc 0x...",
            ).strip()

        if st.button("Chạy phân tích ML + SHAP + CFG", type="primary"):
            target = manual_ident or curated[selected_idx]["sample_id"]
            try:
                analysis = analyze_dataset_sample(df_s_code, model, target)
                st.session_state["current_analysis"] = analysis
                st.session_state["current_evidence"] = None
                st.session_state["current_storage_receipt"] = None
                st.session_state["last_run_id"] = "0x" + secrets.token_hex(32)
                st.session_state["last_created_at_utc"] = analysis.created_at_utc or normalize_utc_timestamp()
            except Exception as exc:
                st.error(f"Không tìm thấy hoặc lỗi phân tích: {exc}")
    else:
        c1, c2 = st.columns(2)
        with c1:
            custom_addr = st.text_input("Địa chỉ hợp đồng (subject)", value="0x000000000000000000000000000000000000dead")
            chain_id_src = int(st.number_input("Source Chain ID", min_value=1, value=1, step=1))
        with c2:
            fetch_rpc = st.text_input("RPC URL để fetch eth_getCode (tùy chọn)", value="")
            if st.button("Fetch bytecode từ RPC") and fetch_rpc.strip():
                try:
                    fetched = fetch_bytecode_from_rpc(custom_addr, fetch_rpc.strip())
                    st.session_state["custom_hex_input"] = fetched
                    st.success(f"Đã lấy runtime bytecode ({len(fetched)//2 - 1} bytes).")
                except Exception as exc:
                    st.error(f"Lỗi fetch RPC: {exc}")

        custom_hex = st.text_area(
            "Runtime Bytecode Hex (0x...)",
            value=st.session_state.get("custom_hex_input", ""),
            height=110,
            placeholder="0x6080604052...",
        )
        st.info("Lưu ý: Nếu chỉ cung cấp bytecode mà không có lịch sử giao dịch, 23 đặc trưng tài khoản sẽ được điền 0.0.")
        if st.button("Phân tích Bytecode tùy chỉnh", type="primary"):
            try:
                analysis = analyze_custom_bytecode(
                    custom_addr,
                    custom_hex,
                    model,
                    source_chain_id=chain_id_src,
                )
                st.session_state["current_analysis"] = analysis
                st.session_state["current_evidence"] = None
                st.session_state["current_storage_receipt"] = None
                st.session_state["last_run_id"] = "0x" + secrets.token_hex(32)
                st.session_state["last_created_at_utc"] = analysis.created_at_utc or normalize_utc_timestamp()
            except Exception as exc:
                st.error(f"Lỗi phân tích bytecode: {exc}")

    analysis = st.session_state.get("current_analysis")
    if analysis is None:
        return

    st.divider()
    pred_text = "Ponzi (1)" if analysis.predicted_label == 1 else "Non-Ponzi (0)"
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Điểm rủi ro (Score)", f"{analysis.score:.6f}")
    m2.metric("Ngưỡng phân loại (τ*)", f"{analysis.threshold:.6f}")
    m3.metric("Nhãn dự đoán", pred_text)
    gt_text = "N/A" if analysis.ground_truth_label is None else ("Ponzi (1)" if analysis.ground_truth_label == 1 else "Non-Ponzi (0)")
    m4.metric("Nhãn gốc (Dataset)", gt_text)

    if analysis.account_features_imputed:
        st.warning(analysis.notes)

    st.caption(
        f"Subject: `{analysis.subject_address}` | Sample: `{analysis.sample_id}` | "
        f"`code_hash`: `{analysis.code_hash}` | `model_version_hash`: `{analysis.model_version_hash}`"
    )

    col_left, col_right = st.columns(2)
    with col_left:
        st.subheader("SHAP Waterfall (TreeExplainer)")
        fig_shap = render_shap_waterfall_figure(analysis, max_display=12)
        st.pyplot(fig_shap, clear_figure=True)
        plt.close(fig_shap)
        st.dataframe(pd.DataFrame(analysis.shap_top_k), use_container_width=True, hide_index=True)

    with col_right:
        st.subheader("Cấu trúc Bytecode & Đồ thị")
        graph_tab_cfg, graph_tab_op = st.tabs(["Basic-Block CFG (F-GSEM)", "Opcode Transition Graph (F-GSTAT)"])
        with graph_tab_cfg:
            fig_cfg = render_cfg_figure(analysis)
            st.pyplot(fig_cfg, clear_figure=True)
            plt.close(fig_cfg)
        with graph_tab_op:
            fig_op = render_transition_graph_figure(analysis)
            st.pyplot(fig_op, clear_figure=True)
            plt.close(fig_op)

        gsem_summary = {
            "n_blocks": int(analysis.gsem_features["n_blocks"]),
            "n_cfg_edges": int(analysis.gsem_features["n_cfg_edges"]),
            "n_scc_cycles": int(analysis.gsem_features["n_scc_cycles"]),
            "has_loop_with_call": int(analysis.gsem_features["has_loop_with_call"]),
            "path_callvalue_to_call": int(analysis.gsem_features["path_callvalue_to_call"]),
            "has_selfdestruct": int(analysis.gsem_features["has_selfdestruct"]),
            "unresolved_jump_ratio": round(float(analysis.gsem_features["unresolved_jump_ratio"]), 4),
        }
        st.json(gsem_summary)


def _render_page_2_evidence() -> None:
    st.header("2. Tạo & Lưu trữ gói bằng chứng chuẩn hóa (Evidence Packaging)")
    analysis: AnalysisResult | None = st.session_state.get("current_analysis")
    if analysis is None:
        st.info("Chưa có kết quả phân tích. Hãy chạy Trang 1 trước để tạo gói bằng chứng.")
        return

    c1, c2 = st.columns([2, 1])
    with c1:
        run_id_val = st.text_input("run_id (bytes32)", value=st.session_state["last_run_id"]).strip()
    with c2:
        if st.button("Sinh run_id mới"):
            st.session_state["last_run_id"] = "0x" + secrets.token_hex(32)
            st.session_state["last_created_at_utc"] = normalize_utc_timestamp()
            st.session_state["current_storage_receipt"] = None
            st.rerun()

    frozen_ts = st.session_state.get("last_created_at_utc") or analysis.created_at_utc or None

    try:
        evidence = build_evidence_bundle(
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
            run_id=run_id_val,
            created_at_utc=frozen_ts,
        )
        raw_bytes = canonical_bytes(evidence)
        ev_hash = evidence_hash_hex(evidence)
        cid_case = case_id_hex(
            analysis.source_chain_id,
            analysis.subject_address,
            analysis.model_version_hash,
            run_id_val,
        )
    except Exception as exc:
        st.error(f"Lỗi chuẩn hóa evidence JSON: {exc}")
        return

    st.session_state["current_evidence"] = evidence
    st.session_state["current_case_id"] = cid_case
    st.session_state["current_evidence_hash"] = ev_hash

    k1, k2, k3 = st.columns(3)
    k1.metric("Canonical Size (bytes)", len(raw_bytes))
    k2.code(f"case_id:\n{cid_case}")
    k3.code(f"evidence_hash:\n{ev_hash}")

    col_json, col_actions = st.columns([3, 2])
    with col_json:
        st.subheader("Canonical JSON (UTF-8, sort_keys, 6-decimal strings)")
        st.code(raw_bytes.decode("utf-8"), language="json")
        st.download_button(
            label="Tải xuống Canonical JSON",
            data=raw_bytes,
            file_name=f"{cid_case}.json",
            mime="application/json",
        )

    with col_actions:
        st.subheader("Lưu trữ Off-Chain (IPFS + Git Mirror)")
        if st.button("Đẩy lên IPFS & lưu vào evidence/", type="primary"):
            try:
                receipt = persist_evidence_bundle(evidence, cid_case)
                st.session_state["current_evidence_uri"] = receipt.evidence_uri
                st.session_state["current_storage_receipt"] = receipt
                st.success(f"Đã lưu thành công! URI: `{receipt.evidence_uri}`")
            except Exception as exc:
                st.error(f"Lỗi lưu bằng chứng: {exc}")

        receipt = st.session_state.get("current_storage_receipt")
        if receipt is not None:
            st.markdown(
                f"- **evidence_uri:** `{receipt.evidence_uri}` (`{len(receipt.evidence_uri)}` / 128 chars)\n"
                f"- **Git mirror:** `{receipt.git_rel_path}`\n"
                f"- **Backup URI:** `{receipt.backup_uri}`\n"
                f"- **Pin status:** `{receipt.pin_status}` ({receipt.pin_detail})"
            )


def _render_page_3_sign(network: str, custom_rpc: str | None, signer_base_url: str) -> None:
    st.header("3. Ký & Gửi giao dịch (Client-Side MetaMask / Local Anvil Test)")

    try:
        w3 = connect_web3(network, rpc_url=custom_rpc)
        contract, dep_info = get_registry_contract(w3, network, variant="D1")
        meta = read_registry_meta(contract, known_auditors=dep_info.get("auditors", []))
        chain_id = int(w3.eth.chain_id)
    except Exception as exc:
        st.error(f"Không kết nối được tới `{network}` RPC: {exc}")
        st.caption("Gợi ý: Nếu dùng Anvil local trên Windows, chạy `python -m scripts.local_rpc_server` ở terminal khác.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Chain ID", chain_id)
    c2.metric("Quorum (k)", meta["threshold"])
    c3.metric("Auditors (n)", meta["auditor_count"])
    c4.code(meta["address"])

    with st.expander("Danh sách Auditor hợp lệ trên contract"):
        st.json(meta["auditor_status"])

    ev = st.session_state.get("current_evidence") or {}
    default_cid = st.session_state.get("current_case_id", "")
    default_subj = ev.get("subject_address", "")
    default_scid = int(ev.get("source_chain_id", 1))
    default_ehash = st.session_state.get("current_evidence_hash", "")
    default_mvh = ev.get("model_version_hash", "")
    default_uri = st.session_state.get("current_evidence_uri", "")

    st.subheader("Tham số giao dịch")
    col_l, col_r = st.columns(2)
    with col_l:
        case_id_input = st.text_input("case_id (bytes32)", value=default_cid).strip()
        subject_input = st.text_input("subject (address)", value=default_subj).strip()
        subject_chain_input = int(st.number_input("subject_chain_id", min_value=1, value=default_scid, step=1))
    with col_r:
        ev_hash_input = st.text_input("evidence_hash (bytes32)", value=default_ehash).strip()
        mvh_input = st.text_input("model_version_hash (bytes32)", value=default_mvh).strip()
        ev_uri_input = st.text_input("evidence_uri (<=128 chars)", value=default_uri).strip()

    action = st.radio("Hành động", ["register_case", "attest"], horizontal=True)
    decision_label_map = {1: "1 = Approve", 2: "2 = Reject", 3: "3 = NeedsReview"}
    decision = st.selectbox("Decision (cho attest)", [1, 2, 3], format_func=lambda d: decision_label_map[d])
    reason_note = st.text_input("Ghi chú lý do (sẽ hash thành reason_hash, có thể để trống)", value="")
    reason_hash_hex = compute_reason_hash(reason_note)

    st.divider()
    st.subheader("Luồng ký an toàn qua trình duyệt (ethers.js v6 + MetaMask)")
    if case_id_input and subject_input and ev_hash_input and mvh_input and ev_uri_input:
        signer_url = build_signer_url(
            signer_base_url,
            action=action,
            chain_id=chain_id,
            contract_address=meta["address"],
            case_id_hex=case_id_input,
            subject=subject_input,
            subject_chain_id=subject_chain_input,
            evidence_hash_hex=ev_hash_input,
            model_version_hash_hex=mvh_input,
            evidence_uri=ev_uri_input,
            decision=decision,
            reason_hash=reason_hash_hex,
        )
        st.link_button("Mở trang ký MetaMask (signer/index.html)", signer_url, type="primary")
        st.code(signer_url, language="text")
    else:
        st.info("Điền đầy đủ `case_id`, `subject`, `evidence_hash`, `model_version_hash`, `evidence_uri` để tạo URL trang ký.")

    st.subheader("Theo dõi Transaction Receipt bằng Tx Hash")
    tx_hash_input = st.text_input("Dán tx_hash từ MetaMask để xác nhận", value="").strip()
    if st.button("Kiểm tra Receipt trên chain") and tx_hash_input:
        try:
            rc = inspect_tx_receipt(w3, contract, tx_hash_input)
            st.json(rc)
            if case_id_input:
                st.write("Trạng thái Case hiện tại trên chain:")
                st.json(read_case(contract, case_id_input))
        except Exception as exc:
            st.error(f"Không đọc được receipt: {exc}")

    # Local Anvil test-only server signing mode (strictly gated to chain_id == 31337).
    if network == "anvil" and chain_id == 31337:
        st.divider()
        st.error(
            "⚠️ TEST KEY – ANVIL ONLY (chain_id = 31337): Chỉ dùng các tài khoản test mặc định của Anvil "
            "để kiểm thử cục bộ. Không bao giờ lưu khóa Sepolia/Mainnet trên server."
        )
        anvil_accts = get_anvil_test_accounts(w3)
        auditor_choice = st.selectbox(
            "Chọn Anvil Test Auditor",
            list(anvil_accts.keys()),
            format_func=lambda k: f"{k} ({anvil_accts[k]['address']}) [TEST KEY – ANVIL ONLY]",
        )
        chosen_pk = anvil_accts[auditor_choice]["private_key"]

        b1, b2 = st.columns(2)
        with b1:
            if st.button("Gửi register_case() bằng Anvil Test Key"):
                try:
                    res = send_anvil_register_case(
                        w3,
                        contract,
                        chosen_pk,
                        case_id_hex=case_id_input,
                        subject=subject_input,
                        subject_chain_id=subject_chain_input,
                        evidence_hash_hex=ev_hash_input,
                        model_version_hash_hex=mvh_input,
                        evidence_uri=ev_uri_input,
                    )
                    st.session_state["last_tx_hashes"].append(res["tx_hash"])
                    st.success(f"register_case thành công! tx={res['tx_hash']} (gasUsed={res['gas_used']})")
                except Exception as exc:
                    st.error(f"register_case lỗi: {exc}")
        with b2:
            if st.button("Gửi attest() bằng Anvil Test Key"):
                try:
                    res = send_anvil_attest(
                        w3,
                        contract,
                        chosen_pk,
                        case_id_hex=case_id_input,
                        decision=decision,
                        reason_text_or_hash=reason_note,
                    )
                    st.session_state["last_tx_hashes"].append(res["tx_hash"])
                    st.success(f"attest thành công! tx={res['tx_hash']} (gasUsed={res['gas_used']})")
                    st.json(read_case(contract, case_id_input))
                except Exception as exc:
                    st.error(f"attest lỗi: {exc}")
    else:
        st.caption("Chế độ ký server-side bị tắt hoàn toàn trên mạng live testnet (chỉ cho phép ký qua MetaMask).")


def _render_page_4_verifier(network: str, custom_rpc: str | None) -> None:
    st.header("4. Kiểm chứng công khai (Public Verifier — Zero-Trust Verification)")

    try:
        w3 = connect_web3(network, rpc_url=custom_rpc)
        contract, dep_info = get_registry_contract(w3, network, variant="D1")
        from_blk = int(dep_info.get("block_number", 0)) if network != "anvil" else 0
    except Exception as exc:
        st.error(f"Không kết nối được tới `{network}` RPC: {exc}")
        return

    onchain_cases = []
    try:
        onchain_cases = list_registered_cases(w3, contract, from_block=from_blk)
    except Exception:
        pass

    cid_index = load_cid_index(EVIDENCE_DIR / "cid_index.json").get("entries", {})
    candidate_ids = list(
        dict.fromkeys(
            [c["case_id"] for c in onchain_cases]
            + ([st.session_state["current_case_id"]] if st.session_state.get("current_case_id") else [])
            + list(cid_index.keys())
        )
    )

    col_sel, col_man = st.columns([2, 2])
    with col_sel:
        selected_cid = st.selectbox("Chọn case_id đã ghi nhận", [""] + candidate_ids)
    with col_man:
        manual_cid = st.text_input("Hoặc nhập case_id (bytes32)", value=selected_cid).strip()

    target_cid = manual_cid or selected_cid
    if not target_cid:
        st.info("Nhập hoặc chọn một `case_id` để truy vấn trực tiếp trạng thái on-chain và đối chiếu bằng chứng.")
        return

    try:
        case_data = read_case(contract, target_cid)
        meta = read_registry_meta(contract)
        history = fetch_case_history(w3, contract, target_cid, from_block=from_blk)
    except Exception as exc:
        st.error(f"Lỗi truy vấn on-chain: {exc}")
        return

    if not case_data.get("exists"):
        st.warning(f"Case `{target_cid}` chưa được đăng ký trên contract `{contract.address}` ({network}).")
        return

    reg = history.get("registered") or {}
    onchain_uri = reg.get("evidence_uri", "")

    st.subheader("Trạng thái Quorum On-Chain")
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Status", f"{case_data['status_label']} ({case_data['status']})")
    s2.metric("Approve", f"{case_data['approve_count']} / {meta['threshold']}")
    s3.metric("Reject", f"{case_data['reject_count']} / {meta['threshold']}")
    s4.metric("NeedsReview", str(case_data["review_count"]))

    st.markdown(
        f"- **Subject:** `{case_data['subject']}` (source chain `{case_data['subject_chain_id']}`)\n"
        f"- **On-chain `evidence_hash`:** `{case_data['evidence_hash']}`\n"
        f"- **On-chain `model_version_hash`:** `{case_data['model_version_hash']}`\n"
        f"- **On-chain `evidence_uri`:** `{onchain_uri or 'N/A'}`"
    )

    st.subheader("Đối chiếu Hash Bằng Chứng Off-Chain")
    verify_src = st.radio(
        "Nguồn JSON kiểm chứng",
        ["Tự động tải từ evidence_uri (IPFS / Git mirror)", "Tải lên / Dán JSON thủ công (kiểm thử giả mạo)"],
        horizontal=True,
    )

    raw_bytes: bytes | None = None
    source_desc = ""
    if verify_src.startswith("Tự động"):
        if onchain_uri:
            try:
                raw_bytes, source_desc = fetch_evidence_bytes(onchain_uri, case_id=target_cid)
            except Exception as exc:
                st.error(f"Không tải được dữ liệu từ `{onchain_uri}`: {exc}")
        else:
            st.error("Không tìm thấy event CaseRegistered chứa evidence_uri.")
    else:
        uploaded = st.file_uploader("Upload file JSON bằng chứng", type=["json"])
        pasted = st.text_area("Hoặc dán nội dung JSON", height=120)
        if uploaded is not None:
            raw_bytes = uploaded.getvalue()
            source_desc = f"uploaded:{uploaded.name}"
        elif pasted.strip():
            raw_bytes = pasted.encode("utf-8")
            source_desc = "pasted_text"

    if raw_bytes is not None:
        verified_local, diag = verify_evidence_payload(
            raw_bytes,
            case_data["evidence_hash"],
            expected_case_id_hex=target_cid,
            expected_subject=case_data.get("subject"),
            expected_subject_chain_id=case_data.get("subject_chain_id"),
            expected_model_version_hash_hex=case_data.get("model_version_hash"),
        )
        onchain_match = verify_evidence_onchain(contract, target_cid, diag["recomputed_hash"])
        passed = verified_local and onchain_match

        if passed:
            st.success(
                f"✅ VERIFIED — Bằng chứng khớp 100% với on-chain `verify_evidence == True` và toàn bộ trường định danh (`subject`, `chain_id`, `model_version_hash`, `case_id`) (nguồn: `{source_desc}`)"
            )
        else:
            st.error(
                f"❌ TAMPERED / MISMATCH — Hash, schema hoặc trường định danh KHÔNG khớp on-chain (`verify_evidence == {onchain_match}`, `identity_match == {diag.get('identity_match')}`)"
            )

        c_a, c_b = st.columns(2)
        c_a.code(f"On-chain evidence_hash:\n{case_data['evidence_hash']}")
        c_b.code(f"Recomputed keccak256:\n{diag['recomputed_hash']}")
        if diag["schema_errors"]:
            st.warning("Lỗi schema/digest: " + "; ".join(diag["schema_errors"]))
        if diag.get("identity_errors"):
            st.warning("Lỗi đối chiếu định danh on-chain: " + "; ".join(diag["identity_errors"]))

        if isinstance(diag.get("evidence"), dict):
            ev_obj = diag["evidence"]
            with st.expander("Nội dung bằng chứng & Top-10 SHAP"):
                st.write(
                    f"Score: `{ev_obj.get('score')}` | Threshold: `{ev_obj.get('threshold')}` | "
                    f"Predicted: `{ev_obj.get('predicted_label')}` | `shap_digest`: `{ev_obj.get('shap_digest')}`"
                )
                if isinstance(ev_obj.get("shap_top_k"), list):
                    st.dataframe(pd.DataFrame(ev_obj["shap_top_k"]), use_container_width=True, hide_index=True)

    st.subheader("Lịch sử xác nhận Append-Only (Events)")
    att_rows = history.get("attestations", [])
    if att_rows:
        df_att = pd.DataFrame(att_rows)
        if network in EXPLORER_TX_URLS:
            df_att["explorer"] = EXPLORER_TX_URLS[network] + df_att["tx_hash"]
        st.dataframe(df_att, use_container_width=True, hide_index=True)
    else:
        st.info("Chưa có lượt xác nhận (Attested) nào cho case này.")

    if history.get("status_changes"):
        st.write("Lịch sử chuyển trạng thái (`StatusChanged`):")
        st.dataframe(pd.DataFrame(history["status_changes"]), use_container_width=True, hide_index=True)


def main() -> None:
    _init_session_state()
    page, custom_rpc, signer_base_url, network = _render_sidebar()  # type: ignore[misc]

    if page.startswith("1."):
        model = _cached_model()
        df_s_code = _cached_catalog()
        _render_page_1_analysis(model, df_s_code)
    elif page.startswith("2."):
        _render_page_2_evidence()
    elif page.startswith("3."):
        _render_page_3_sign(network, custom_rpc, signer_base_url)
    else:
        _render_page_4_verifier(network, custom_rpc)


if __name__ == "__main__":
    main()
