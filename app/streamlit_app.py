"""X-SPIDE-G 4-Page Streamlit DApp for Explainable Ponzi Risk Attestation (Phase 6.3).

Pages:
  1. Risk Analysis (LightGBM score, threshold, legal disclaimer, SHAP waterfall, CFG graph)
  2. Evidence Packaging (Canonical JSON v1.0, evidence_hash, case_id, IPFS CIDv1 + Git mirror)
  3. Sign & Submit (Client-side ethers.js + MetaMask signer URL + local TEST KEY - ANVIL ONLY mode)
  4. Public Verifier (Independent on-chain + off-chain hash recomputation & event log timeline)
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd
import streamlit as st

from src.evidence.canonical import canonical_bytes, case_id_hex, evidence_hash_hex
from src.evidence.chain_client import (
    DECISION_NAMES,
    RegistryChainSession,
    build_signer_query_url,
)
from src.evidence.inference import evaluate_contract_sample, load_frozen_model_and_data
from src.evidence.storage import save_evidence_bundle

REPO_ROOT = Path(__file__).resolve().parents[1]


def _get_chain_session() -> RegistryChainSession:
    if "chain_session" not in st.session_state:
        st.session_state["chain_session"] = RegistryChainSession(network="local-evm", threshold=2)
    return st.session_state["chain_session"]


def _plot_shap_top_k(shap_top_k: list[dict]) -> plt.Figure:
    items = list(reversed(shap_top_k))
    labels = [f"#{it['rank']} {it['feature']} ({it['feature_value']})" for it in items]
    vals = [float(it["shap_value"]) for it in items]
    colors = ["#dc2626" if v >= 0 else "#2563eb" for v in vals]

    fig, ax = plt.subplots(figsize=(7.5, 4.0), dpi=140)
    ax.barh(labels, vals, color=colors)
    ax.axvline(0.0, color="#334155", linewidth=1.0)
    ax.set_xlabel("SHAP Contribution (log-odds towards Ponzi = 1)")
    ax.set_title("Top-10 Local SHAP Feature Attributions")
    fig.tight_layout()
    return fig


def _plot_cfg_preview(G: nx.DiGraph) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(6.5, 4.0), dpi=130)
    sub_nodes = list(G.nodes())[:35]
    H = G.subgraph(sub_nodes)
    pos = nx.spring_layout(H, seed=42)
    node_colors = [
        "#ef4444" if H.nodes[n].get("has_call") else "#38bdf8" for n in H.nodes()
    ]
    nx.draw_networkx(
        H,
        pos=pos,
        ax=ax,
        node_size=260,
        node_color=node_colors,
        font_size=7,
        arrows=True,
    )
    ax.set_title(f"Basic-Block CFG Preview (showing {len(H.nodes())}/{len(G.nodes())} blocks)")
    ax.axis("off")
    fig.tight_layout()
    return fig


def main() -> None:
    st.set_page_config(page_title="X-SPIDE-G Risk Attestation DApp", layout="wide")
    st.title("X-SPIDE-G: Explainable Ponzi Detection & k-of-n On-Chain Risk Attestation")
    st.caption("IS355 – Blockchain Technology · Group 4 – DICTATOR")

    ctx = load_frozen_model_and_data(str(REPO_ROOT))
    df_contracts = ctx["df_contracts"]
    session = _get_chain_session()

    page = st.sidebar.radio(
        "Navigation (4 Pages)",
        [
            "1. Phân tích rủi ro (Risk Analysis)",
            "2. Tạo bằng chứng (Evidence Packaging)",
            "3. Ký & gửi giao dịch (Sign & Submit)",
            "4. Kiểm chứng công khai (Public Verifier)",
        ],
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**Contract (`D1`):** `{session.contract.address}`")
    st.sidebar.markdown(f"**Quorum:** `k = {session.contract.functions.threshold().call()}` of `n = {len(session.auditors)}`")
    st.sidebar.info(session.test_key_banner)

    if page.startswith("1."):
        st.header("Trang 1 – Phân tích rủi ro hợp đồng thông minh (ML + SHAP + CFG)")
        st.warning(
            "⚠️ **Cảnh báo trách nhiệm:** Đây là dự đoán xác suất của mô hình học máy (LightGBM), "
            "**không phải** kết luận pháp lý hay bằng chứng khẳng định gian lận."
        )

        col1, col2 = st.columns([1, 2])
        with col1:
            sample_options = df_contracts["sample_id"].astype(str).tolist()[:200]
            selected_sid = st.selectbox("Chọn sample_id từ tập S_code", sample_options, index=0)
            custom_addr = st.text_input("Hoặc nhập địa chỉ hợp đồng (0x...)", value="")
            run_tag = st.text_input("Run Tag", value="streamlit-demo-v1")
            if st.button("Chạy phân tích ML + SHAP", type="primary"):
                res = evaluate_contract_sample(
                    sample_id=None if custom_addr.strip() else selected_sid,
                    address=custom_addr.strip() or None,
                    run_tag=run_tag,
                )
                st.session_state["last_analysis"] = res

        if "last_analysis" in st.session_state:
            res = st.session_state["last_analysis"]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Điểm rủi ro (Score)", f"{res['score']:.6f}")
            c2.metric("Ngưỡng (Threshold τ*)", f"{res['threshold']:.6f}")
            c3.metric(
                "Nhãn dự đoán",
                "1 - High Risk (Ponzi)" if res["predicted_label"] == 1 else "0 - Low Risk (Non-Ponzi)",
            )
            c4.metric("Nhãn thực (Dataset)", str(res["ground_truth_label"]))

            left, right = st.columns(2)
            with left:
                st.pyplot(_plot_shap_top_k(res["shap_top_k"]))
            with right:
                if res["cfg_graph"] is not None:
                    st.pyplot(_plot_cfg_preview(res["cfg_graph"]))
                if res["gsem_summary"]:
                    st.subheader("Đặc trưng đồ thị ngữ nghĩa CFG (F-GSEM)")
                    st.json(res["gsem_summary"])

    elif page.startswith("2."):
        st.header("Trang 2 – Chuẩn hóa gói bằng chứng JSON & lưu trữ IPFS / Git")
        if "last_analysis" not in st.session_state:
            st.info("Hãy chạy phân tích một hợp đồng ở Trang 1 trước, hoặc bấm nút bên dưới để nạp mẫu mặc định.")
            if st.button("Nạp mẫu mặc định (xspide_00439 - Ponzi)"):
                st.session_state["last_analysis"] = evaluate_contract_sample(sample_id="xspide_00439")

        if "last_analysis" in st.session_state:
            ev = st.session_state["last_analysis"]["evidence"]
            ev_hash = evidence_hash_hex(ev)
            cid = case_id_hex(
                ev["source_chain_id"],
                ev["subject_address"],
                ev["model_version_hash"],
                ev["run_id"],
            )
            st.code(f"case_id           = {cid}\nevidence_hash     = {ev_hash}\nmodel_version_hash = {ev['model_version_hash']}")

            if st.button("Lưu gói bằng chứng chuẩn hóa (IPFS CIDv1 + Git mirror)", type="primary"):
                stored = save_evidence_bundle(ev)
                st.session_state["last_stored"] = stored
                st.success(f"Đã lưu thành công: {stored.local_path} | URI: {stored.evidence_uri}")

            if "last_stored" in st.session_state:
                stored = st.session_state["last_stored"]
                st.json(
                    {
                        "case_id": stored.case_id,
                        "evidence_hash": stored.evidence_hash,
                        "evidence_uri": stored.evidence_uri,
                        "git_fallback_uri": stored.git_fallback_uri,
                        "local_path": stored.local_path,
                        "pin_status": stored.pin_status,
                    }
                )

            st.subheader("Canonical JSON Payload (`sort_keys=True, separators=(',', ':')`)")
            st.code(canonical_bytes(ev).decode("utf-8"), language="json")

    elif page.startswith("3."):
        st.header("Trang 3 – Ký & gửi giao dịch (ethers.js + MetaMask / Local Test Mode)")
        stored = st.session_state.get("last_stored")
        ev = st.session_state.get("last_analysis", {}).get("evidence")

        default_cid = stored.case_id if stored else "0x" + "11" * 32
        default_eh = stored.evidence_hash if stored else "0x" + "22" * 32
        default_uri = stored.evidence_uri if stored else "ipfs://bafkreidemo"
        default_subj = ev["subject_address"] if ev else "0x1111111111111111111111111111111111111111"
        default_mvh = ev["model_version_hash"] if ev else "0x" + "33" * 32

        st.subheader("A. Ký phía trình duyệt bằng MetaMask (`signer/index.html`, không qua server)")
        reg_url = build_signer_query_url(
            action="register_case",
            contract_address=session.contract.address,
            chain_id=int(session.w3.eth.chain_id),
            case_id_hex=default_cid,
            subject_address=default_subj,
            subject_chain_id=1,
            evidence_hash_hex=default_eh,
            model_version_hash_hex=default_mvh,
            evidence_uri=default_uri,
        )
        att_url = build_signer_query_url(
            action="attest",
            contract_address=session.contract.address,
            chain_id=int(session.w3.eth.chain_id),
            case_id_hex=default_cid,
            decision=1,
        )
        st.markdown(f"- **Link mở trang ký `register_case`:** `{reg_url}`")
        st.markdown(f"- **Link mở trang ký `attest`:** `{att_url}`")

        tx_lookup = st.text_input("Theo dõi Transaction Receipt qua tx_hash (Web3.py):", value="")
        if tx_lookup.strip():
            try:
                rc = session.w3.eth.get_transaction_receipt(tx_lookup.strip())
                st.json({"blockNumber": rc.blockNumber, "gasUsed": rc.gasUsed, "status": rc.status})
            except Exception as exc:
                st.error(f"Không tìm thấy receipt: {exc}")

        st.markdown("---")
        st.subheader("B. Chế độ kiểm thử cục bộ (`TEST KEY – ANVIL / LOCAL-EVM ONLY`)")
        st.warning("🔑 **TEST KEY – ANVIL ONLY:** Chỉ dùng khóa kiểm thử cục bộ; tuyệt đối không đặt khóa Sepolia hay khóa thật trên server.")

        c_reg, c_att = st.columns(2)
        with c_reg:
            if st.button("1. Auditor #1 gọi register_case", disabled=not session.is_test_key_allowed):
                try:
                    rc_info = session.register_case(
                        auditor_index=0,
                        case_id_hex=default_cid,
                        subject_address=default_subj,
                        subject_chain_id=1,
                        evidence_hash_hex=default_eh,
                        model_version_hash_hex=default_mvh,
                        evidence_uri=default_uri,
                    )
                    st.success(f"Đã đăng ký case! tx_hash = {rc_info['tx_hash']} (gas={rc_info['gas_used']})")
                except Exception as exc:
                    st.error(f"Revert / Lỗi: {exc}")

        with c_att:
            aud_idx = st.selectbox("Chọn Auditor ký xác nhận", [0, 1, 2], format_func=lambda i: f"Auditor #{i+1} ({session.auditors[i][:10]}...)")
            dec_val = st.selectbox("Quyết định (Decision)", [1, 2, 3], format_func=lambda d: f"{d} = {DECISION_NAMES[d]}")
            if st.button("2. Gửi giao dịch attest(case_id, decision)", disabled=not session.is_test_key_allowed):
                try:
                    rc_att = session.attest_case(
                        auditor_index=aud_idx,
                        case_id_hex=default_cid,
                        decision=dec_val,
                    )
                    st.success(f"Đã ghi nhận attest! tx_hash = {rc_att['tx_hash']} (gas={rc_att['gas_used']})")
                except Exception as exc:
                    st.error(f"Revert / Lỗi: {exc}")

    elif page.startswith("4."):
        st.header("Trang 4 – Kiểm chứng công khai (Public Third-Party Verifier)")
        stored = st.session_state.get("last_stored")
        query_cid = st.text_input(
            "Nhập case_id (bytes32) cần kiểm chứng:",
            value=stored.case_id if stored else "",
        )
        if st.button("Kiểm chứng On-Chain + Off-Chain JSON", type="primary") and query_cid.strip():
            ver = session.public_verify_case(query_cid.strip())
            if ver["verified"]:
                st.success(f"### {ver['badge']}")
            else:
                st.error(f"### {ver['badge']}")

            st.json(
                {
                    "verified": ver["verified"],
                    "onchain_verify_evidence_call": ver.get("onchain_verify_call"),
                    "onchain_evidence_hash": ver.get("onchain_evidence_hash"),
                    "recomputed_raw_file_hash": ver.get("recomputed_raw_hash"),
                    "recomputed_canonical_hash": ver.get("recomputed_canonical_hash"),
                }
            )
            st.subheader("Trạng thái Case On-Chain")
            st.json(ver["onchain"]["case"])
            st.subheader("Lịch sử sự kiện `Attested` (Append-Only Event Log)")
            st.dataframe(pd.DataFrame(ver["onchain"]["attestation_events"]))
            st.subheader("Lịch sử sự kiện `StatusChanged`")
            st.dataframe(pd.DataFrame(ver["onchain"]["status_events"]))


if __name__ == "__main__":
    main()
