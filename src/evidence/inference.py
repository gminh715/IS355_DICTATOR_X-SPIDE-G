"""ML inference, SHAP TreeExplainer attribution, and CFG/transition-graph rendering for Phase 6."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd
import shap
from web3 import Web3

from src.data.bytecode import parse_hex_bytecode, strip_cbor_metadata
from src.data.parquet_io import read_parquet
from src.features.disasm import disassemble
from src.features.gsem import CFGResult, GSEM_FEATURE_NAMES, build_cfg, extract_gsem_features
from src.features.gstat import build_transition_graph
from src.models.data_prep import get_xspide_feature_columns, prepare_xspide_99_features
from src.models.phase4_features import _DISASM_TO_XSPIDE_OPCODE
from src.models.phase4_xai import _extract_positive_shap

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_DIR = REPO_ROOT / "models" / "baseline_v1"
DEFAULT_PARQUET_PATH = REPO_ROOT / "data" / "processed" / "contracts.parquet"

RISK_DISCLAIMER = (
    "Cảnh báo diễn giải: Điểm rủi ro và nhãn dự đoán là chỉ báo xác suất từ mô hình ML "
    "(LightGBM E1 baseline), KHÔNG phải kết luận gian lận hay phán quyết pháp lý."
)


@dataclass(frozen=True)
class LoadedBaselineModel:
    """Loaded frozen Phase 2 E1 baseline model, schema, and cryptographic version hashes."""

    pipeline: Any
    model_card: dict[str, Any]
    feature_schema: dict[str, Any]
    feature_order: tuple[str, ...]
    account_features: tuple[str, ...]
    opcode_features: tuple[str, ...]
    threshold: float
    model_version_hash: str
    feature_schema_hash: str


@dataclass
class AnalysisResult:
    """Complete off-chain risk analysis output for one contract."""

    sample_id: str
    dataset_id: str
    source_chain_id: int
    subject_address: str
    code_hash: str
    stripped_bytecode_hex: str
    score: float
    threshold: float
    predicted_label: int
    ground_truth_label: int | None
    model_version_hash: str
    feature_schema_hash: str
    feature_vector: pd.Series
    shap_values: np.ndarray
    shap_base_value: float
    shap_top_k: list[dict[str, str]]
    gsem_features: dict[str, float]
    cfg_result: CFGResult
    transition_graph: nx.DiGraph
    account_features_imputed: bool
    notes: str = ""


def load_baseline_model(model_dir: Path = DEFAULT_MODEL_DIR) -> LoadedBaselineModel:
    """Load frozen baseline_v1 joblib pipeline, feature_schema.json, and model_card.json."""
    card = json.loads((model_dir / "model_card.json").read_text(encoding="utf-8"))
    schema = json.loads((model_dir / "feature_schema.json").read_text(encoding="utf-8"))
    pipe = joblib.load(model_dir / "model.joblib")
    return LoadedBaselineModel(
        pipeline=pipe,
        model_card=card,
        feature_schema=schema,
        feature_order=tuple(schema["feature_order"]),
        account_features=tuple(schema["account_features"]),
        opcode_features=tuple(schema["opcode_features"]),
        threshold=float(card["classification_threshold"]),
        model_version_hash=str(card["artifacts"]["model_version_hash"]).lower(),
        feature_schema_hash=str(card["features"]["feature_schema_hash"]).lower(),
    )


def load_s_code_catalog(parquet_path: Path = DEFAULT_PARQUET_PATH) -> pd.DataFrame:
    """Load S_code contracts table for sample lookup in Streamlit and E2E tests."""
    df = read_parquet(parquet_path)
    df = df[df["bytecode_source"] != "missing"].copy().reset_index(drop=True)
    return df


def _score_and_explain(
    model: LoadedBaselineModel,
    X_row_df: pd.DataFrame,
    *,
    top_k: int = 10,
) -> tuple[float, int, np.ndarray, float, list[dict[str, str]]]:
    X_ordered = X_row_df[list(model.feature_order)].astype("float64")
    score = float(model.pipeline.predict_proba(X_ordered)[0, 1])
    pred_label = int(score >= model.threshold)

    clf = model.pipeline.named_steps["clf"]
    explainer = shap.TreeExplainer(clf)
    sv_2d, base_val = _extract_positive_shap(explainer, X_ordered)
    sv = sv_2d[0]
    vals = X_ordered.iloc[0].to_numpy(dtype=np.float64)

    order = sorted(
        range(len(model.feature_order)),
        key=lambda idx: (-abs(float(sv[idx])), model.feature_order[idx]),
    )[:top_k]

    shap_top_k = [
        {
            "feature": model.feature_order[idx],
            "value": f"{float(vals[idx]):.6f}",
            "shap_value": f"{float(sv[idx]):.6f}",
        }
        for idx in order
    ]
    return score, pred_label, sv, float(base_val), shap_top_k


def analyze_dataset_sample(
    df_s_code: pd.DataFrame,
    model: LoadedBaselineModel,
    identifier: str,
    *,
    source_chain_id: int = 1,
    dataset_id: str = "xspide_S_code",
) -> AnalysisResult:
    """Run baseline LightGBM inference, TreeExplainer SHAP, and CFG/GSEM analysis on a dataset row."""
    ident = identifier.strip().lower()
    mask = (df_s_code["sample_id"].astype(str).str.lower() == ident) | (
        df_s_code["address"].astype(str).str.lower() == ident
    )
    matches = df_s_code[mask]
    if matches.empty:
        raise KeyError(f"Contract sample_id or address not found in S_code: {identifier!r}")

    row_df = matches.iloc[[0]].copy()
    row = row_df.iloc[0]
    X_99 = prepare_xspide_99_features(row_df, normalize_opcodes=True)
    score, pred_label, sv, base_val, shap_top_k = _score_and_explain(model, X_99, top_k=10)

    stripped_hex = str(row["stripped_bytecode_hex"])
    raw_bytes = parse_hex_bytecode(stripped_hex)
    dis = disassemble(raw_bytes, log_truncated=False)
    cfg_res = build_cfg(dis)
    gsem_feats = extract_gsem_features(dis, normalize=True)
    trans_graph, _ = build_transition_graph(dis.mnemonics(normalize=True))

    gt_raw = row.get("label")
    gt_label = int(gt_raw) if pd.notna(gt_raw) else None

    return AnalysisResult(
        sample_id=str(row["sample_id"]),
        dataset_id=dataset_id,
        source_chain_id=source_chain_id,
        subject_address=str(row["address"]).lower(),
        code_hash=str(row["code_hash"]).lower(),
        stripped_bytecode_hex=stripped_hex,
        score=score,
        threshold=model.threshold,
        predicted_label=pred_label,
        ground_truth_label=gt_label,
        model_version_hash=model.model_version_hash,
        feature_schema_hash=model.feature_schema_hash,
        feature_vector=X_99.iloc[0],
        shap_values=sv,
        shap_base_value=base_val,
        shap_top_k=shap_top_k,
        gsem_features=gsem_feats,
        cfg_result=cfg_res,
        transition_graph=trans_graph,
        account_features_imputed=False,
        notes="Evaluated using exact S_code 99 features (23 account + 76 opcode frequencies).",
    )


def fetch_bytecode_from_rpc(address: str, rpc_url: str) -> str:
    """Fetch deployed runtime bytecode via eth_getCode for a custom contract address."""
    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 8}))
    if not w3.is_connected():
        raise ConnectionError(f"Cannot connect to RPC at {rpc_url}")
    code = w3.eth.get_code(Web3.to_checksum_address(address))
    if not code:
        raise ValueError(f"No runtime bytecode found at {address} (EOA or self-destructed).")
    return "0x" + bytes(code).hex()


def analyze_custom_bytecode(
    subject_address: str,
    bytecode_hex: str,
    model: LoadedBaselineModel,
    *,
    account_features: dict[str, float] | None = None,
    source_chain_id: int = 1,
    sample_id: str | None = None,
) -> AnalysisResult:
    """Analyze arbitrary runtime EVM bytecode with optional account features (zero-filled if omitted)."""
    raw = parse_hex_bytecode(bytecode_hex)
    if not raw:
        raise ValueError("Runtime bytecode hex is empty or invalid.")
    stripped = strip_cbor_metadata(raw)
    code_hash = stripped.code_hash or ("0x" + "00" * 32)
    stripped_hex = "0x" + stripped.stripped_bytes.hex()

    dis = disassemble(stripped.stripped_bytes, log_truncated=False)
    cfg_res = build_cfg(dis)
    gsem_feats = extract_gsem_features(dis, normalize=True)
    trans_graph, _ = build_transition_graph(dis.mnemonics(normalize=True))

    op_set = set(model.opcode_features)
    counts: Counter[str] = Counter()
    for m in dis.mnemonics(normalize=True):
        mapped = _DISASM_TO_XSPIDE_OPCODE.get(m, m)
        if mapped in op_set:
            counts[mapped] += 1
    total_ops = float(sum(counts.values()))

    row_dict: dict[str, float] = {}
    imputed = account_features is None
    for feat in model.account_features:
        row_dict[feat] = float(account_features.get(feat, 0.0)) if account_features else 0.0
    for feat in model.opcode_features:
        row_dict[feat] = (counts.get(feat, 0) / total_ops) if total_ops > 0.0 else 0.0

    X_row = pd.DataFrame([row_dict], columns=list(model.feature_order), dtype=np.float64)
    score, pred_label, sv, base_val, shap_top_k = _score_and_explain(model, X_row, top_k=10)

    resolved_sample_id = sample_id or f"custom_{code_hash[2:12]}"
    note = (
        "Custom bytecode analysis: 23 account transaction features were zero-filled."
        if imputed
        else "Custom bytecode analysis with user-supplied account features."
    )

    return AnalysisResult(
        sample_id=resolved_sample_id,
        dataset_id="custom_bytecode",
        source_chain_id=source_chain_id,
        subject_address=subject_address.strip().lower(),
        code_hash=code_hash.lower(),
        stripped_bytecode_hex=stripped_hex,
        score=score,
        threshold=model.threshold,
        predicted_label=pred_label,
        ground_truth_label=None,
        model_version_hash=model.model_version_hash,
        feature_schema_hash=model.feature_schema_hash,
        feature_vector=X_row.iloc[0],
        shap_values=sv,
        shap_base_value=base_val,
        shap_top_k=shap_top_k,
        gsem_features=gsem_feats,
        cfg_result=cfg_res,
        transition_graph=trans_graph,
        account_features_imputed=imputed,
        notes=note,
    )


def render_shap_waterfall_figure(analysis: AnalysisResult, *, max_display: int = 12) -> plt.Figure:
    """Create a Matplotlib SHAP waterfall Figure for display in Streamlit."""
    exp = shap.Explanation(
        values=analysis.shap_values,
        base_values=analysis.shap_base_value,
        data=analysis.feature_vector.to_numpy(dtype=np.float64),
        feature_names=list(analysis.feature_vector.index),
    )
    plt.close("all")
    shap.plots.waterfall(exp, max_display=max_display, show=False)
    fig = plt.gcf()
    fig.set_size_inches(8.6, 5.2)
    fig.suptitle(
        f"SHAP Waterfall — {analysis.sample_id} (score={analysis.score:.4f}, tau*={analysis.threshold:.4f})",
        fontsize=10.5,
        y=1.02,
    )
    fig.tight_layout()
    return fig


def render_cfg_figure(analysis: AnalysisResult) -> plt.Figure:
    """Render recovered basic-block CFG highlighting payout-loop, CALL, CALLVALUE, and SSTORE nodes."""
    cfg_res = analysis.cfg_result
    g = cfg_res.graph
    blocks = cfg_res.blocks

    fig, ax = plt.subplots(figsize=(8.8, 5.6), dpi=180)
    if g.number_of_nodes() == 0:
        ax.text(0.5, 0.5, "Empty CFG (no disassembled blocks)", ha="center", va="center")
        ax.axis("off")
        return fig

    loop_nodes: set[int] = set()
    for scc in nx.strongly_connected_components(g):
        if len(scc) > 1 or (len(scc) == 1 and g.has_edge(next(iter(scc)), next(iter(scc)))):
            loop_nodes.update(scc)

    if g.number_of_nodes() > 110:
        keep: set[int] = {0} | loop_nodes
        for b in blocks:
            if b.has_call or b.has_callvalue or b.has_selfdestruct or b.has_sstore:
                keep.add(b.block_id)
                keep.update(g.predecessors(b.block_id))
                keep.update(g.successors(b.block_id))
        if len(keep) > 90:
            keep = set(sorted(keep)[:90])
        g_plot = g.subgraph(keep).copy()
        subtitle = f"Subgraph {g_plot.number_of_nodes()}/{g.number_of_nodes()} key blocks"
    else:
        g_plot = g
        subtitle = f"{g.number_of_nodes()} blocks, {g.number_of_edges()} edges"

    colors: list[str] = []
    labels: dict[int, str] = {}
    for nid in g_plot.nodes():
        b = blocks[nid]
        in_loop = nid in loop_nodes
        tags: list[str] = []
        if b.has_callvalue:
            tags.append("CV")
        if b.has_call:
            tags.append("CALL")
        if b.has_sstore:
            tags.append("SS")
        if b.has_selfdestruct:
            tags.append("SD")
        if in_loop:
            tags.append("LOOP")
        labels[nid] = f"B{nid}\n" + ("/".join(tags) if tags else f"0x{b.start_pc:x}")

        if in_loop and b.has_call:
            colors.append("#d62728")
        elif b.has_selfdestruct:
            colors.append("#9467bd")
        elif b.has_call or b.has_callvalue:
            colors.append("#ff7f0e")
        elif b.has_sstore:
            colors.append("#1f77b4")
        elif in_loop:
            colors.append("#bcbd22")
        else:
            colors.append("#d3d3d3")

    try:
        pos = nx.kamada_kawai_layout(g_plot)
    except Exception:
        pos = nx.spring_layout(g_plot, seed=42)

    nx.draw_networkx_edges(g_plot, pos, ax=ax, edge_color="#666666", alpha=0.55, arrows=True, arrowsize=9)
    nx.draw_networkx_nodes(g_plot, pos, ax=ax, node_color=colors, node_size=330, edgecolors="#222222", linewidths=0.8)
    nx.draw_networkx_labels(g_plot, pos, labels=labels, ax=ax, font_size=6.2)
    ax.set_title(
        f"Basic-Block CFG — {analysis.sample_id}\n({subtitle}, unresolved_jump_ratio={cfg_res.unresolved_jump_ratio:.2f})",
        fontsize=10,
    )
    ax.axis("off")
    fig.tight_layout()
    return fig


def render_transition_graph_figure(analysis: AnalysisResult, *, top_edges: int = 35) -> plt.Figure:
    """Render top-weighted edges of the normalized opcode transition graph (F-GSTAT view)."""
    tg = analysis.transition_graph
    fig, ax = plt.subplots(figsize=(8.8, 5.4), dpi=180)
    if tg.number_of_edges() == 0:
        ax.text(0.5, 0.5, "Empty opcode transition graph", ha="center", va="center")
        ax.axis("off")
        return fig

    sorted_edges = sorted(tg.edges(data=True), key=lambda e: -float(e[2]["weight"]))[:top_edges]
    sub = nx.DiGraph()
    for u, v, d in sorted_edges:
        sub.add_edge(u, v, weight=float(d["weight"]))

    pos = nx.spring_layout(sub, seed=42, k=0.9)
    weights = [float(d["weight"]) for _, _, d in sub.edges(data=True)]
    max_w = max(weights) if weights else 1.0
    widths = [0.7 + 3.0 * (w / max_w) for w in weights]

    key_ops = {"CALL", "CALLVALUE", "SSTORE", "SLOAD", "SELFDESTRUCT", "JUMP", "JUMPI"}
    node_colors = ["#ff7f0e" if n in key_ops else "#4c78a8" for n in sub.nodes()]

    nx.draw_networkx_edges(sub, pos, ax=ax, width=widths, edge_color="#666666", alpha=0.6, arrows=True, arrowsize=10)
    nx.draw_networkx_nodes(sub, pos, ax=ax, node_color=node_colors, node_size=460, edgecolors="#222222", linewidths=0.8)
    nx.draw_networkx_labels(sub, pos, ax=ax, font_size=6.8, font_color="#ffffff", font_weight="bold")
    ax.set_title(
        f"Opcode Transition Graph (Top {len(sorted_edges)}/{tg.number_of_edges()} edges) — {analysis.sample_id}",
        fontsize=10,
    )
    ax.axis("off")
    fig.tight_layout()
    return fig
