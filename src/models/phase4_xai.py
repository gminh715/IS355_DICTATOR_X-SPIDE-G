"""Phase 4.5 & 4.6: Out-of-fold SHAP explanations, publication figures, CFG visuals, and error analysis."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd
import shap
from scipy.stats import spearmanr
from sklearn.metrics import average_precision_score, precision_recall_curve
from sklearn.pipeline import Pipeline

from src.data.bytecode import parse_hex_bytecode
from src.features.disasm import disassemble
from src.features.gsem import GSEM_FEATURE_NAMES, build_cfg
from src.models.data_prep import load_split_indices
from src.models.phase4_features import load_phase4_dataset
from src.models.tuning import build_lgbm_classifier


def _extract_positive_shap(
    explainer: shap.TreeExplainer,
    X_slice: pd.DataFrame,
) -> tuple[np.ndarray, float]:
    """Extract 2D positive-class SHAP values and scalar base value robustly across SHAP versions."""
    raw_sv = explainer.shap_values(X_slice)
    if isinstance(raw_sv, list):
        sv = np.asarray(raw_sv[1] if len(raw_sv) > 1 else raw_sv[0], dtype=np.float64)
    else:
        arr = np.asarray(raw_sv, dtype=np.float64)
        sv = arr[:, :, 1] if arr.ndim == 3 else arr

    ev = explainer.expected_value
    if isinstance(ev, (list, tuple, np.ndarray)):
        ev_arr = np.asarray(ev, dtype=np.float64).ravel()
        base_val = float(ev_arr[1] if len(ev_arr) > 1 else ev_arr[0])
    else:
        base_val = float(ev)
    return sv, base_val


def compute_oof_predictions_for_seed(
    repo_root: Path,
    results_dir: Path,
    config_name: str,
    *,
    seed: int = 42,
    compute_shap: bool = False,
) -> dict[str, Any]:
    """Re-fit the 5 outer folds of `seed` using frozen tuned params and evaluate strictly out-of-fold."""
    df_meta, X, pre_steps = load_phase4_dataset(repo_root, config_name)
    y = df_meta["label"].to_numpy(dtype=int)
    fold_df = pd.read_csv(results_dir / f"{config_name}_folds.csv")
    seed_rows = fold_df[fold_df["seed"].astype(int) == seed].sort_values("fold")
    if len(seed_rows) != 5:
        raise ValueError(f"Expected 5 folds for {config_name} seed={seed}, found {len(seed_rows)}")

    n = len(df_meta)
    oof_proba = np.zeros(n, dtype=np.float64)
    oof_tau = np.zeros(n, dtype=np.float64)
    oof_fold = np.full(n, -1, dtype=int)
    seen = np.zeros(n, dtype=bool)

    shap_values: np.ndarray | None = None
    shap_base = np.zeros(n, dtype=np.float64)
    feature_names: list[str] | None = None
    X_eval_df: pd.DataFrame | None = None

    from sklearn.base import clone

    for _, row in seed_rows.iterrows():
        fold = int(row["fold"])
        split_path = repo_root / "splits" / f"S_code_group_near_seed{seed}_fold{fold}.json"
        tr_idx, te_idx, _ = load_split_indices(df_meta, split_path)
        params = json.loads(str(row["best_params_json"]))
        tau_star = float(row["threshold"])

        steps = [(nm, clone(est)) for nm, est in pre_steps] if pre_steps else []
        steps.append(("clf", build_lgbm_classifier(params, random_state=seed, n_jobs=4)))
        pipe = Pipeline(steps)
        pipe.fit(X.iloc[tr_idx], y[tr_idx])

        proba_te = pipe.predict_proba(X.iloc[te_idx])[:, 1]
        ap_te = float(average_precision_score(y[te_idx], proba_te))
        if abs(ap_te - float(row["PR-AUC"])) > 1e-4:
            raise AssertionError(
                f"Re-fitted PR-AUC mismatch on {config_name} seed={seed} fold={fold}: "
                f"{ap_te:.6f} vs {float(row['PR-AUC']):.6f}"
            )

        oof_proba[te_idx] = proba_te
        oof_tau[te_idx] = tau_star
        oof_fold[te_idx] = fold
        seen[te_idx] = True

        if compute_shap:
            if pre_steps:
                # Transform strictly using training-fitted pre_steps.
                X_te_trans = pipe[:-1].transform(X.iloc[te_idx])
            else:
                X_te_trans = X.iloc[te_idx]
            clf = pipe.named_steps["clf"]
            explainer = shap.TreeExplainer(clf)
            sv_te, base_val = _extract_positive_shap(explainer, X_te_trans)
            if shap_values is None:
                feature_names = list(X_te_trans.columns)
                shap_values = np.zeros((n, len(feature_names)), dtype=np.float64)
                X_eval_df = pd.DataFrame(np.zeros((n, len(feature_names))), columns=feature_names, index=df_meta.index)
            shap_values[te_idx] = sv_te
            shap_base[te_idx] = base_val
            X_eval_df.iloc[te_idx] = X_te_trans.to_numpy(dtype=np.float64)

    if not seen.all():
        raise AssertionError(f"Unassigned samples in {seed} pooled CV for {config_name}")

    return {
        "df_meta": df_meta,
        "y": y,
        "oof_proba": oof_proba,
        "oof_tau": oof_tau,
        "oof_fold": oof_fold,
        "oof_pred": (oof_proba >= oof_tau).astype(int),
        "shap_values": shap_values,
        "shap_base": shap_base,
        "feature_names": feature_names,
        "X_eval": X_eval_df if X_eval_df is not None else X,
    }


def plot_pooled_pr_curves(
    oof_map: dict[str, dict[str, Any]],
    out_path: Path,
) -> None:
    """Plot pooled held-out PR curves (seed=42, all 7,446 contracts) across key configurations."""
    plt.figure(figsize=(8.2, 6.2), dpi=220)
    styles = {
        "E1": ("#1f77b4", "-", 2.1, "E1 (99 X-SPIDE)"),
        "E4b": ("#ff7f0e", "--", 1.9, "E4b (99 + F-BIGRAM)"),
        "E4c": ("#2ca02c", "-", 2.3, "E4c (99 + F-GSEM)"),
        "E4d": ("#9467bd", "-.", 2.0, "E4d (99 + BIGRAM + GSEM)"),
        "E3b": ("#8c564b", ":", 1.8, "E3b (Code-only BIGRAM)"),
        "E3c": ("#d62728", ":", 1.9, "E3c (Code-only GSEM)"),
    }
    for exp_id, (color, ls, lw, label) in styles.items():
        bundle = oof_map[exp_id]
        y = bundle["y"]
        proba = bundle["oof_proba"]
        p, r, _ = precision_recall_curve(y, proba)
        ap = float(average_precision_score(y, proba))
        plt.plot(r, p, color=color, linestyle=ls, linewidth=lw, label=f"{label} (AP={ap:.4f})")

    baseline = float(oof_map["E1"]["y"].mean())
    plt.axhline(baseline, color="#7f7f7f", linestyle="--", linewidth=1.0, label=f"No-skill baseline ({baseline:.3f})")
    plt.axhline(0.90, color="#333333", linestyle=":", linewidth=1.0, alpha=0.7, label="Precision = 0.90 target")
    plt.xlabel("Recall", fontsize=11)
    plt.ylabel("Precision", fontsize=11)
    plt.title("Pooled Held-Out Precision-Recall Curves (S_code, 5-Fold CV Seed=42, n=7,446)", fontsize=12)
    plt.xlim(0.0, 1.01)
    plt.ylim(0.0, 1.03)
    plt.grid(alpha=0.28)
    plt.legend(loc="lower left", fontsize=8.8, framealpha=0.92)
    plt.tight_layout()
    plt.savefig(out_path, dpi=220)
    plt.close()


def plot_delta_pr_auc_ci(stat_df: pd.DataFrame, out_path: Path) -> None:
    """Plot Nadeau-Bengio 95% CIs and Holm-adjusted verdicts for the 8 pre-registered comparisons."""
    sub = stat_df[stat_df["test_suite"] == "preregistered_holm_8"].copy().reset_index(drop=True)
    sub = sub.iloc[::-1].reset_index(drop=True)

    color_map = {
        "Confirmed Improvement": "#2ca02c",
        "No Significant Difference": "#7f7f7f",
        "Inconclusive": "#d95f02",
    }

    fig, ax = plt.subplots(figsize=(9.5, 5.2), dpi=220)
    y_pos = np.arange(len(sub))

    for i, r in sub.iterrows():
        c = color_map.get(str(r["conclusion"]), "#1f77b4")
        x = float(r["mean_delta"])
        lo = float(r["ci95_low"])
        hi = float(r["ci95_high"])
        ax.errorbar(
            x,
            i,
            xerr=[[max(0.0, x - lo)], [max(0.0, hi - x)]],
            fmt="o",
            color=c,
            ecolor=c,
            elinewidth=2.2,
            capsize=4.5,
            markersize=6.5,
        )
        text_x = max(hi, 0.025) + 0.004
        ax.text(
            text_x,
            i,
            f"Δ={x:+.4f}, p_Holm={float(r['p_holm']):.4f} [{r['conclusion']}]",
            va="center",
            fontsize=8.3,
            color=c,
        )

    ax.axvline(0.0, color="#222222", linestyle="-", linewidth=1.1, label="Null (ΔPR-AUC = 0)")
    ax.axvline(0.02, color="#d62728", linestyle="--", linewidth=1.2, label="Pre-registered MDE (+0.02)")
    ax.set_yticks(y_pos)
    ax.set_yticklabels(sub["comparison"], fontsize=9.8)
    ax.set_xlabel("ΔPR-AUC (25 Paired Folds, 95% Nadeau-Bengio Corrected CI)", fontsize=10.5)
    ax.set_title("Pre-Registered 8-Comparison Holm-Bonferroni Family on S_code", fontsize=12)

    min_lo = float(sub["ci95_low"].min())
    max_hi = float(sub["ci95_high"].max())
    span = max(0.05, max_hi - min_lo)
    ax.set_xlim(min_lo - 0.02, max(max_hi, 0.03) + span * 0.95)
    ax.grid(axis="x", alpha=0.28)
    ax.legend(loc="lower right", fontsize=8.8)
    plt.tight_layout()
    plt.savefig(out_path, dpi=220)
    plt.close()


def plot_shap_beeswarm(
    shap_vals: np.ndarray,
    X_eval: pd.DataFrame,
    out_path: Path,
    *,
    title: str,
    max_display: int = 20,
) -> None:
    """Render and save a clean SHAP beeswarm summary plot on held-out test instances."""
    plt.figure(figsize=(9.2, 6.8), dpi=220)
    shap.summary_plot(shap_vals, X_eval, max_display=max_display, show=False)
    plt.title(title, fontsize=11.5, pad=10)
    plt.tight_layout()
    plt.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close()


def plot_gsem_importance_and_sanity(
    shap_vals: np.ndarray,
    X_eval: pd.DataFrame,
    out_path: Path,
) -> dict[str, Any]:
    """Compute F-GSEM SHAP importance, directional Spearman r, and save summary bar plot."""
    cols = list(X_eval.columns)
    rows: list[dict[str, Any]] = []
    for feat in GSEM_FEATURE_NAMES:
        j = cols.index(feat)
        sv = shap_vals[:, j]
        xv = X_eval[feat].to_numpy(dtype=np.float64)
        mean_abs = float(np.mean(np.abs(sv)))
        rho, pval = spearmanr(xv, sv)
        rho_f = 0.0 if np.isnan(rho) else float(rho)

        # Conditional mean SHAP when feature > 0 vs == 0 vs < 0 (e.g., fragmented cyclomatic).
        mask_pos = xv > 0.0
        mask_eq0 = xv == 0.0
        mask_neg = xv < 0.0
        mean_sv_pos = float(np.mean(sv[mask_pos])) if np.any(mask_pos) else float("nan")
        mean_sv_le0 = float(np.mean(sv[~mask_pos])) if np.any(~mask_pos) else float("nan")
        mean_sv_eq0 = float(np.mean(sv[mask_eq0])) if np.any(mask_eq0) else float("nan")
        mean_sv_lt0 = float(np.mean(sv[mask_neg])) if np.any(mask_neg) else float("nan")

        rows.append(
            {
                "feature": feat,
                "mean_abs_shap": mean_abs,
                "spearman_val_vs_shap": rho_f,
                "spearman_pval": 1.0 if np.isnan(pval) else float(pval),
                "mean_shap_when_gt0": mean_sv_pos,
                "mean_shap_when_le0": mean_sv_le0,
                "mean_shap_when_eq0": mean_sv_eq0,
                "mean_shap_when_lt0": mean_sv_lt0,
                "frac_gt0": float(np.mean(mask_pos)),
                "frac_eq0": float(np.mean(mask_eq0)),
                "frac_lt0": float(np.mean(mask_neg)),
                "frac_nonzero": float(np.mean(xv != 0.0)),
            }
        )

    df_gsem = pd.DataFrame(rows).sort_values("mean_abs_shap", ascending=True).reset_index(drop=True)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.5, 5.5), dpi=220, sharey=True)
    y_pos = np.arange(len(df_gsem))

    ax1.barh(y_pos, df_gsem["mean_abs_shap"], color="#2ca02c", alpha=0.88)
    ax1.set_yticks(y_pos)
    ax1.set_yticklabels(df_gsem["feature"], fontsize=9.2)
    ax1.set_xlabel("Mean |SHAP value| (log-odds impact on Ponzi score)", fontsize=9.8)
    ax1.set_title("F-GSEM Global Importance in E4c", fontsize=11)
    ax1.grid(axis="x", alpha=0.25)

    dir_colors = ["#d62728" if r >= 0 else "#1f77b4" for r in df_gsem["spearman_val_vs_shap"]]
    ax2.barh(y_pos, df_gsem["spearman_val_vs_shap"], color=dir_colors, alpha=0.88)
    ax2.axvline(0.0, color="#222222", linewidth=1.0)
    ax2.set_xlabel("Spearman rho(feature value, SHAP value)", fontsize=9.8)
    ax2.set_title("Directional Sanity Check (+ = pushes toward Ponzi)", fontsize=11)
    ax2.set_xlim(-1.05, 1.05)
    ax2.grid(axis="x", alpha=0.25)

    plt.tight_layout()
    plt.savefig(out_path, dpi=220)
    plt.close()

    df_desc = df_gsem.sort_values("mean_abs_shap", ascending=False).reset_index(drop=True)
    return {"gsem_shap_ranking": df_desc.to_dict(orient="records")}


def plot_case_waterfall(
    sv_row: np.ndarray,
    base_value: float,
    x_row: np.ndarray,
    feature_names: list[str],
    *,
    title: str,
    out_path: Path,
    max_display: int = 12,
) -> None:
    """Plot a single-contract SHAP Explanation waterfall on held-out E4c predictions."""
    exp = shap.Explanation(
        values=sv_row,
        base_values=base_value,
        data=x_row,
        feature_names=feature_names,
    )
    plt.figure(figsize=(8.8, 5.4), dpi=220)
    shap.plots.waterfall(exp, max_display=max_display, show=False)
    plt.title(title, fontsize=10.5, pad=12)
    plt.tight_layout()
    plt.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close()


def plot_contract_cfg(
    stripped_hex: str,
    *,
    title: str,
    out_path: Path,
) -> None:
    """Render recovered EVM CFG highlighting CALL/CALLVALUE/SSTORE/SELFDESTRUCT and SCC loop blocks."""
    code = parse_hex_bytecode(stripped_hex)
    dis = disassemble(code, log_truncated=False)
    cfg_res = build_cfg(dis)
    g = cfg_res.graph
    blocks = cfg_res.blocks

    loop_nodes: set[int] = set()
    for scc in nx.strongly_connected_components(g):
        if len(scc) > 1 or (len(scc) == 1 and g.has_edge(next(iter(scc)), next(iter(scc)))):
            loop_nodes.update(scc)

    # For very large CFGs (>120 blocks), keep entry, loop, call, sstore, and selfdestruct neighborhoods.
    if g.number_of_nodes() > 120:
        keep: set[int] = {0} | loop_nodes
        for b in blocks:
            if b.has_call or b.has_callvalue or b.has_selfdestruct or b.has_sstore:
                keep.add(b.block_id)
                keep.update(g.predecessors(b.block_id))
                keep.update(g.successors(b.block_id))
        if len(keep) > 100:
            keep = set(sorted(keep)[:100])
        g_plot = g.subgraph(keep).copy()
        subtitle_note = f"Subgraph of {g_plot.number_of_nodes()}/{g.number_of_nodes()} key blocks"
    else:
        g_plot = g
        subtitle_note = f"{g.number_of_nodes()} blocks, {g.number_of_edges()} edges"

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
            colors.append("#d62728")  # Red: CALL inside SCC loop
        elif b.has_selfdestruct:
            colors.append("#9467bd")  # Purple: SELFDESTRUCT
        elif b.has_call or b.has_callvalue:
            colors.append("#ff7f0e")  # Orange: CALL / CALLVALUE
        elif b.has_sstore:
            colors.append("#1f77b4")  # Blue: SSTORE
        elif in_loop:
            colors.append("#bcbd22")  # Olive: non-CALL SCC loop
        else:
            colors.append("#cccccc")

    fig, ax = plt.subplots(figsize=(9.5, 6.2), dpi=220)
    try:
        pos = nx.kamada_kawai_layout(g_plot)
    except Exception:
        pos = nx.spring_layout(g_plot, seed=42)

    nx.draw_networkx_edges(g_plot, pos, ax=ax, edge_color="#666666", alpha=0.55, arrows=True, arrowsize=9)
    nx.draw_networkx_nodes(g_plot, pos, ax=ax, node_color=colors, node_size=340, edgecolors="#222222", linewidths=0.8)
    nx.draw_networkx_labels(g_plot, pos, labels=labels, ax=ax, font_size=6.0)
    ax.set_title(
        f"{title}\n({subtitle_note}, unresolved_jump_ratio={cfg_res.unresolved_jump_ratio:.2f})",
        fontsize=10.5,
    )
    ax.axis("off")
    plt.tight_layout()
    plt.savefig(out_path, dpi=220)
    plt.close()


def _top_shap_contributors(
    sv_row: np.ndarray,
    x_row: np.ndarray,
    feature_names: list[str],
    *,
    top_k: int = 3,
) -> tuple[str, str]:
    pos_idx = np.argsort(-sv_row)[:top_k]
    neg_idx = np.argsort(sv_row)[:top_k]
    pos_str = "; ".join(f"{feature_names[i]}={x_row[i]:.4g} ({sv_row[i]:+.3f})" for i in pos_idx if sv_row[i] > 0)
    neg_str = "; ".join(f"{feature_names[i]}={x_row[i]:.4g} ({sv_row[i]:+.3f})" for i in neg_idx if sv_row[i] < 0)
    return pos_str, neg_str


def _categorize_error(row_info: dict[str, Any]) -> str:
    err_type = row_info["error_type"]
    if row_info["group_near_has_mixed_labels"]:
        return "mixed_label_near_clone_cluster"
    if row_info["bytecode_len_bytes"] <= 120 or row_info["n_blocks"] <= 3:
        return "minimal_or_proxy_stub_bytecode"
    if row_info["unresolved_jump_ratio"] > 0.50:
        return "high_unresolved_dynamic_jumps"
    if err_type == "FP":
        if row_info["has_loop_with_call"] > 0.0:
            return "benign_contract_with_payout_loop_motif"
        return "acct_tx_asymmetry_mimicking_ponzi"
    if row_info["tx_in"] <= 2 and row_info["tx_out"] == 0:
        return "low_activity_or_early_ponzi_tx_signal"
    if row_info["has_loop_with_call"] == 0.0:
        return "atypical_ponzi_without_static_call_loop"
    return "borderline_ponzi_signal_below_threshold"


def run_phase4_xai_and_error_analysis(repo_root: Path) -> None:
    """Run all Phase 4.5 XAI figures and Phase 4.6 manual error analysis audit."""
    results_dir = repo_root / "results"
    figures_dir = repo_root / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    stat_df = pd.read_csv(results_dir / "stat_tests.csv")
    plot_delta_pr_auc_ci(stat_df, figures_dir / "delta_pr_auc_ci.png")

    oof_map: dict[str, dict[str, Any]] = {}
    for exp_id in ("E1", "E3b", "E3c", "E4b", "E4c", "E4d"):
        oof_map[exp_id] = compute_oof_predictions_for_seed(
            repo_root,
            results_dir,
            exp_id,
            seed=42,
            compute_shap=exp_id in ("E1", "E4c"),
        )

    plot_pooled_pr_curves(oof_map, figures_dir / "pr_curves.png")

    e1_b = oof_map["E1"]
    e4c_b = oof_map["E4c"]

    plot_shap_beeswarm(
        e1_b["shap_values"],
        e1_b["X_eval"],
        figures_dir / "shap_beeswarm_E1.png",
        title="E1 (99 X-SPIDE Features) - Held-Out Test SHAP Summary (Seed=42, n=7,446)",
    )
    plot_shap_beeswarm(
        e4c_b["shap_values"],
        e4c_b["X_eval"],
        figures_dir / "shap_beeswarm_E4c.png",
        title="E4c (99 X-SPIDE + F-GSEM) - Held-Out Test SHAP Summary (Seed=42, n=7,446)",
    )

    gsem_summary = plot_gsem_importance_and_sanity(
        e4c_b["shap_values"],
        e4c_b["X_eval"],
        figures_dir / "shap_gsem_importance.png",
    )

    # Inspect mixed-label near-clone clusters for diagnostic error tagging.
    df_meta = e4c_b["df_meta"].copy()
    X_e4c = e4c_b["X_eval"]
    sv_e4c = e4c_b["shap_values"]
    base_e4c = e4c_b["shap_base"]
    fnames = list(e4c_b["feature_names"])
    y = e4c_b["y"]
    proba = e4c_b["oof_proba"]
    tau = e4c_b["oof_tau"]
    pred = e4c_b["oof_pred"]
    folds = e4c_b["oof_fold"]

    cluster_sizes = df_meta.groupby("group_near")["label"].agg(["size", "nunique"]).rename(
        columns={"size": "cluster_size", "nunique": "cluster_label_nunique"}
    )
    df_meta = df_meta.join(cluster_sizes, on="group_near")

    # Select 3 case studies (TP Ponzi, FP, FN) with readable CFGs (10..80 blocks preferred).
    tp_mask = (y == 1) & (pred == 1)
    fp_mask = (y == 0) & (pred == 1)
    fn_mask = (y == 1) & (pred == 0)

    def _pick_case(mask: np.ndarray, *, prefer_high_prob: bool) -> int:
        idxs = np.flatnonzero(mask)
        if len(idxs) == 0:
            raise ValueError("Empty selection mask for XAI case study")
        readable = [
            i
            for i in idxs
            if 10.0 <= float(X_e4c.iloc[i]["n_blocks"]) <= 80.0
            and float(X_e4c.iloc[i]["unresolved_jump_ratio"]) <= 0.45
        ]
        pool = np.asarray(readable if readable else idxs, dtype=int)
        if prefer_high_prob:
            # For TP, prefer contracts where has_loop_with_call == 1 if available.
            loop_pool = [i for i in pool if float(X_e4c.iloc[i]["has_loop_with_call"]) > 0.0]
            sub = np.asarray(loop_pool if loop_pool else pool, dtype=int)
            return int(sub[np.argmax(proba[sub])])
        return int(pool[np.argmin(proba[pool])])

    tp_idx = _pick_case(tp_mask, prefer_high_prob=True)
    fp_idx = _pick_case(fp_mask, prefer_high_prob=True)
    fn_idx = _pick_case(fn_mask, prefer_high_prob=False)

    case_records: list[dict[str, Any]] = []
    for case_tag, idx in [("tp", tp_idx), ("fp", fp_idx), ("fn", fn_idx)]:
        sid = str(df_meta.iloc[idx]["sample_id"])
        addr = str(df_meta.iloc[idx]["address"])
        plot_case_waterfall(
            sv_e4c[idx],
            float(base_e4c[idx]),
            X_e4c.iloc[idx].to_numpy(dtype=np.float64),
            fnames,
            title=(
                f"Case {case_tag.upper()}: {addr[:12]}... "
                f"(y={int(y[idx])}, p={proba[idx]:.3f}, tau*={tau[idx]:.3f}, fold={int(folds[idx])})"
            ),
            out_path=figures_dir / f"shap_waterfall_{case_tag}.png",
        )
        plot_contract_cfg(
            str(df_meta.iloc[idx]["stripped_bytecode_hex"]),
            title=f"CFG {case_tag.upper()}: {addr}",
            out_path=figures_dir / f"cfg_{case_tag}.png",
        )
        case_records.append(
            {
                "case_type": case_tag.upper(),
                "sample_id": sid,
                "address": addr,
                "label": int(y[idx]),
                "y_proba": float(proba[idx]),
                "tau_star": float(tau[idx]),
                "fold": int(folds[idx]),
                "n_blocks": float(X_e4c.iloc[idx]["n_blocks"]),
                "n_scc_cycles": float(X_e4c.iloc[idx]["n_scc_cycles"]),
                "n_loops_with_call": float(X_e4c.iloc[idx]["n_loops_with_call"]),
                "has_loop_with_call": float(X_e4c.iloc[idx]["has_loop_with_call"]),
                "path_callvalue_to_call": float(X_e4c.iloc[idx]["path_callvalue_to_call"]),
                "unresolved_jump_ratio": float(X_e4c.iloc[idx]["unresolved_jump_ratio"]),
            }
        )

    # Error analysis table: top 12 highest-confidence FPs + 12 most-missed FNs (plus summary stats over all FP/FN).
    fp_idxs = np.flatnonzero(fp_mask)
    fn_idxs = np.flatnonzero(fn_mask)
    top_fp = fp_idxs[np.argsort(-proba[fp_idxs])[:12]]
    top_fn = fn_idxs[np.argsort(proba[fn_idxs])[:12]]

    err_rows: list[dict[str, Any]] = []
    for err_type, idxs in [("FP", top_fp), ("FN", top_fn)]:
        for idx in idxs:
            pos_sh, neg_sh = _top_shap_contributors(
                sv_e4c[idx], X_e4c.iloc[idx].to_numpy(dtype=np.float64), fnames, top_k=3
            )
            raw_bytes = parse_hex_bytecode(str(df_meta.iloc[idx]["stripped_bytecode_hex"]))
            info = {
                "error_type": err_type,
                "sample_id": str(df_meta.iloc[idx]["sample_id"]),
                "address": str(df_meta.iloc[idx]["address"]),
                "label": int(y[idx]),
                "y_pred": int(pred[idx]),
                "fold": int(folds[idx]),
                "y_proba": float(proba[idx]),
                "tau_star": float(tau[idx]),
                "margin": float(proba[idx] - tau[idx]),
                "group_near": str(df_meta.iloc[idx]["group_near"]),
                "group_near_size": int(df_meta.iloc[idx]["cluster_size"]),
                "group_near_has_mixed_labels": bool(df_meta.iloc[idx]["cluster_label_nunique"] > 1),
                "bytecode_source": str(df_meta.iloc[idx]["bytecode_source"]),
                "bytecode_len_bytes": len(raw_bytes),
                "n_blocks": float(X_e4c.iloc[idx]["n_blocks"]),
                "n_cfg_edges": float(X_e4c.iloc[idx]["n_cfg_edges"]),
                "cyclomatic": float(X_e4c.iloc[idx]["cyclomatic"]),
                "n_scc_cycles": float(X_e4c.iloc[idx]["n_scc_cycles"]),
                "n_loops_with_call": float(X_e4c.iloc[idx]["n_loops_with_call"]),
                "has_loop_with_call": float(X_e4c.iloc[idx]["has_loop_with_call"]),
                "path_callvalue_to_call": float(X_e4c.iloc[idx]["path_callvalue_to_call"]),
                "pagerank_CALL": float(X_e4c.iloc[idx]["pagerank_CALL"]),
                "unresolved_jump_ratio": float(X_e4c.iloc[idx]["unresolved_jump_ratio"]),
                "tx_in": float(X_e4c.iloc[idx]["tx_in"]),
                "tx_out": float(X_e4c.iloc[idx]["tx_out"]),
                "lifetime": float(X_e4c.iloc[idx]["lifetime"]),
                "paid_one": float(X_e4c.iloc[idx]["paid_one"]),
                "top_pos_shap": pos_sh,
                "top_neg_shap": neg_sh,
            }
            info["error_category"] = _categorize_error(info)
            err_rows.append(info)

    err_df = pd.DataFrame(err_rows)
    err_df.to_csv(results_dir / "error_analysis_cases.csv", index=False)

    summary_payload = {
        "seed": 42,
        "total_contracts": int(len(df_meta)),
        "total_fp_seed42": int(len(fp_idxs)),
        "total_fn_seed42": int(len(fn_idxs)),
        "total_tp_seed42": int(tp_mask.sum()),
        "total_tn_seed42": int(((y == 0) & (pred == 0)).sum()),
        "fp_mixed_cluster_count": int(
            sum(df_meta.iloc[i]["cluster_label_nunique"] > 1 for i in fp_idxs)
        ),
        "fn_mixed_cluster_count": int(
            sum(df_meta.iloc[i]["cluster_label_nunique"] > 1 for i in fn_idxs)
        ),
        "case_studies": case_records,
        "gsem_unresolved_jump_median": float(X_e4c["unresolved_jump_ratio"].median()),
        "gsem_unresolved_jump_mean": float(X_e4c["unresolved_jump_ratio"].mean()),
        "gsem_unresolved_jump_gt50_count": int((X_e4c["unresolved_jump_ratio"] > 0.50).sum()),
        **gsem_summary,
    }
    (results_dir / "xai_gsem_summary.json").write_text(
        json.dumps(summary_payload, indent=2), encoding="utf-8"
    )
    print(
        f"[XAI] Done: seed42 TP={summary_payload['total_tp_seed42']} FP={summary_payload['total_fp_seed42']} "
        f"FN={summary_payload['total_fn_seed42']}; saved 11 figures and error_analysis_cases.csv",
        flush=True,
    )


if __name__ == "__main__":
    run_phase4_xai_and_error_analysis(Path("."))
