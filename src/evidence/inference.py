"""ML inference, SHAP top-k extraction, and CFG summary helper for Phase 6 evidence."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import shap
from eth_utils import keccak

from src.data.bytecode import parse_hex_bytecode
from src.data.parquet_io import read_parquet
from src.evidence.canonical import build_evidence_bundle, format_decimal6
from src.features.disasm import disassemble
from src.features.gsem import build_cfg
from src.models.data_prep import load_contracts_dataset, prepare_xspide_99_features

REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO_ROOT / "models" / "baseline_v1"


@lru_cache(maxsize=1)
def load_frozen_model_and_data(repo_root: str | None = None) -> dict[str, Any]:
    """Load frozen baseline_v1 model, model_card.json, and S_code feature matrix."""
    root = Path(repo_root) if repo_root else REPO_ROOT
    m_dir = root / "models" / "baseline_v1"
    model_card = json.loads((m_dir / "model_card.json").read_text(encoding="utf-8"))
    feature_schema = json.loads((m_dir / "feature_schema.json").read_text(encoding="utf-8"))
    model = joblib.load(m_dir / "model.joblib")
    clf = model.named_steps["clf"] if hasattr(model, "named_steps") and "clf" in model.named_steps else model
    explainer = shap.TreeExplainer(clf)

    df_contracts = load_contracts_dataset(root, subset="S_code")
    X_99 = prepare_xspide_99_features(df_contracts, normalize_opcodes=True)

    gsem_path = root / "data" / "processed" / "features_gsem.parquet"
    df_gsem = read_parquet(gsem_path) if gsem_path.is_file() else None

    return {
        "model": model,
        "clf": clf,
        "explainer": explainer,
        "model_card": model_card,
        "feature_schema": feature_schema,
        "df_contracts": df_contracts,
        "X_99": X_99,
        "df_gsem": df_gsem,
    }


def _extract_single_positive_shap(explainer: shap.TreeExplainer, row_df: pd.DataFrame) -> tuple[np.ndarray, float]:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        raw_sv = explainer.shap_values(row_df)
    if isinstance(raw_sv, list):
        sv = np.asarray(raw_sv[1] if len(raw_sv) > 1 else raw_sv[0], dtype=np.float64)[0]
    else:
        arr = np.asarray(raw_sv, dtype=np.float64)
        sv = arr[0, :, 1] if arr.ndim == 3 else arr[0]

    ev = explainer.expected_value
    if isinstance(ev, (list, tuple, np.ndarray)):
        ev_arr = np.asarray(ev, dtype=np.float64).ravel()
        base_val = float(ev_arr[1] if len(ev_arr) > 1 else ev_arr[0])
    else:
        base_val = float(ev)
    return sv, base_val


def evaluate_contract_sample(
    *,
    sample_id: str | int | None = None,
    address: str | None = None,
    run_tag: str = "phase6-default-run",
    created_at_utc: str | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Run baseline_v1 prediction + SHAP on a contract in S_code and build canonical evidence."""
    ctx = load_frozen_model_and_data(str(repo_root or REPO_ROOT))
    df = ctx["df_contracts"]
    X_99 = ctx["X_99"]
    model = ctx["model"]
    explainer = ctx["explainer"]
    card = ctx["model_card"]

    if sample_id is not None:
        sid_q = str(sample_id).strip()
        matches = df.index[df["sample_id"].astype(str) == sid_q].tolist()
        if not matches and sid_q.isdigit():
            formatted = f"xspide_{int(sid_q):05d}"
            matches = df.index[df["sample_id"].astype(str) == formatted].tolist()
    elif address is not None:
        norm_addr = address.strip().lower()
        matches = df.index[df["address"].astype(str).str.lower() == norm_addr].tolist()
    else:
        raise ValueError("Provide either sample_id or address")

    if not matches:
        raise KeyError(f"Contract not found in S_code for sample_id={sample_id!r}, address={address!r}")

    idx = int(matches[0])
    row_meta = df.iloc[idx]
    row_X = X_99.iloc[[idx]]

    score = float(model.predict_proba(row_X)[0, 1])
    threshold = float(card["classification_threshold"])
    sv, base_val = _extract_single_positive_shap(explainer, row_X)

    feat_names = list(row_X.columns)
    feat_vals = row_X.iloc[0].to_numpy(dtype=np.float64)
    shap_items = [
        {
            "feature": fname,
            "feature_value": float(fval),
            "shap_value": float(sval),
        }
        for fname, fval, sval in zip(feat_names, feat_vals, sv)
    ]

    sid_str = str(row_meta["sample_id"])
    subj_addr = str(row_meta["address"]).lower()
    run_id_hex = "0x" + bytes(keccak(f"{run_tag}:{sid_str}:{subj_addr}".encode("utf-8"))).hex()

    evidence = build_evidence_bundle(
        subject_address=subj_addr,
        code_hash=str(row_meta["code_hash"]),
        sample_id=sid_str,
        feature_schema_hash=str(card["features"]["feature_schema_hash"]),
        model_version_hash=str(card["artifacts"]["model_version_hash"]),
        score=score,
        threshold=threshold,
        shap_items=shap_items,
        run_id=run_id_hex,
        source_chain_id=1,
        dataset_id="xspide_s_code",
        created_at_utc=created_at_utc,
    )

    # Extract CFG / GSEM summary for UI display
    gsem_summary: dict[str, Any] = {}
    if ctx["df_gsem"] is not None and idx < len(ctx["df_gsem"]):
        g_row = ctx["df_gsem"].iloc[idx]
        for col in ctx["df_gsem"].columns:
            if col not in ("sample_id", "address"):
                gsem_summary[col] = float(g_row[col])

    raw_hex = str(row_meta.get("stripped_bytecode_hex") or row_meta.get("bytecode_hex") or "")
    cfg_graph = None
    if raw_hex:
        try:
            insns, _ = disassemble(parse_hex_bytecode(raw_hex))
            cfg_res = build_cfg(insns)
            cfg_graph = cfg_res.graph
        except Exception:
            cfg_graph = None

    return {
        "row_index": idx,
        "sample_id": sid_str,
        "address": subj_addr,
        "ground_truth_label": int(row_meta["label"]),
        "score": float(format_decimal6(score)),
        "threshold": float(format_decimal6(threshold)),
        "predicted_label": int(evidence["predicted_label"]),
        "shap_base_value": base_val,
        "shap_top_k": evidence["shap_top_k"],
        "evidence": evidence,
        "gsem_summary": gsem_summary,
        "cfg_graph": cfg_graph,
    }
