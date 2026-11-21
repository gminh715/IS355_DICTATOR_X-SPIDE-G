"""Generate publication-grade IEEEtran vector PDF figures from verified results."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from mpl_toolkits.axes_grid1.inset_locator import inset_axes, mark_inset
from scipy.stats import spearmanr
from sklearn.metrics import precision_recall_curve

from src.contracts.e5_benchmark import generate_gas_vs_batch_plot
from src.models.phase4_xai import compute_oof_predictions_for_seed

plt.rcParams.update(
    {
        "font.family": "serif",
        "font.serif": ["Times New Roman", "DejaVu Serif", "Times"],
        "mathtext.fontset": "stix",
        "axes.edgecolor": "#222222",
        "axes.linewidth": 0.85,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    }
)


def _fmt_p(val: float) -> str:
    if val < 1e-3:
        return f"{val:.1e}"
    return f"{val:.4f}"


def build_pr_curves_pdf(
    repo_root: Path,
    results_dir: Path,
    out_pdf: Path,
    *,
    oof_cache: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Render pooled seed-42 OOF PR curves with high-recall zoom inset and 25-fold mean AP legend."""
    mc = pd.read_csv(results_dir / "model_comparison.csv").set_index("experiment")
    cache = oof_cache if oof_cache is not None else {}

    curve_specs = [
        ("E4b", "E4b: X-SPIDE + F-BIGRAM", "#0072B2", "-", 2.0),
        ("E4d", "E4d: X-SPIDE + F-BIGRAM + F-GSEM", "#D55E00", "--", 1.8),
        ("E3b", "E3b: F-BIGRAM only", "#009E73", "-.", 1.8),
        ("E4c", "E4c: X-SPIDE + F-GSEM", "#CC79A7", "-", 1.7),
        ("E1", "E1: 99 X-SPIDE baseline", "#333333", ":", 2.0),
        ("E3", "E3: F-GSTAT only", "#E69F00", "--", 1.8),
    ]

    for exp_id, *_ in curve_specs:
        if exp_id not in cache:
            cache[exp_id] = compute_oof_predictions_for_seed(
                repo_root, results_dir, exp_id, seed=42, compute_shap=False
            )

    fig, ax = plt.subplots(figsize=(6.4, 5.6))

    axins = inset_axes(
        ax,
        width="100%",
        height="100%",
        bbox_to_anchor=(0.09, 0.08, 0.43, 0.39),
        bbox_transform=ax.transAxes,
        loc="lower left",
        borderpad=0.0,
    )
    axins.set_xlim(0.68, 0.92)
    axins.set_ylim(0.65, 0.96)
    axins.set_title("High-Recall Regime", fontsize=9.5, pad=4)
    axins.grid(alpha=0.25, linestyle=":")
    axins.tick_params(labelsize=8.2)

    for exp_id, label, color, ls, lw in curve_specs:
        bundle = cache[exp_id]
        p, r, _ = precision_recall_curve(bundle["y"], bundle["oof_proba"])
        mean_ap = float(mc.loc[exp_id, "PR_AUC_mean"])
        ax.plot(r, p, color=color, linestyle=ls, linewidth=lw, label=f"{label} ({mean_ap:.4f})")
        axins.plot(r, p, color=color, linestyle=ls, linewidth=lw * 0.95)

    prevalence = float(cache["E1"]["y"].mean())
    ax.axhline(
        prevalence,
        color="#7f7f7f",
        linestyle=":",
        linewidth=1.1,
        label=f"No-skill prevalence ({prevalence:.3f})",
    )

    mark_inset(ax, axins, loc1=1, loc2=4, fc="none", ec="#777777", lw=0.8)

    ax.set_xlabel("Recall", fontsize=11)
    ax.set_ylabel("Precision", fontsize=11)
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.02)
    ax.grid(alpha=0.25, linestyle=":")
    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, 1.02),
        ncol=2,
        frameon=False,
        fontsize=8.6,
        columnspacing=1.2,
        handlelength=2.2,
    )
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_pdf, bbox_inches="tight")
    plt.close(fig)


def build_delta_pr_auc_ci_pdf(results_dir: Path, out_pdf: Path) -> None:
    """Render forest plot of 8 pre-registered paired Delta PR-AUC tests with NB/Wilcoxon Holm columns."""
    stat_df = pd.read_csv(results_dir / "stat_tests.csv")
    prereg = stat_df[stat_df["test_suite"] == "preregistered_holm_8"].set_index("comparison")

    ordered_rows = [
        ("E4b vs E1", "E4b vs. E1  (+F-BIGRAM over baseline)"),
        ("E3c vs E3", "E3c vs. E3  (F-GSEM vs. F-GSTAT code-only)"),
        ("E4 vs E1", "E4 vs. E1  (+F-GSTAT over baseline)"),
        ("E4c vs E1", "E4c vs. E1  (+F-GSEM over baseline)"),
        ("E4d vs E4b", "E4d vs. E4b  (+F-GSEM atop F-BIGRAM)"),
        ("E2 vs E1", "E2 vs. E1  (In-fold RFECV vs. all 99)"),
        ("E4c vs E4b", "E4c vs. E4b  (F-GSEM vs. F-BIGRAM + base)"),
        ("E3c vs E3b", "E3c vs. E3b  (F-GSEM vs. F-BIGRAM code-only)"),
    ]

    fig = plt.figure(figsize=(11.4, 4.9))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.12, 1.0], wspace=0.04)
    ax = fig.add_subplot(gs[0, 0])
    ax_tbl = fig.add_subplot(gs[0, 1])

    n_rows = len(ordered_rows)
    y_positions = np.arange(n_rows)[::-1]

    ax.axvspan(-0.02, 0.02, color="#f0f0f0", zorder=0)
    ax.axvline(0.0, color="#222222", linestyle="--", linewidth=1.0, zorder=1)
    ax.axvline(0.02, color="#009E73", linestyle=":", linewidth=1.1, zorder=1)

    ax_tbl.set_xlim(0.0, 1.0)
    ax_tbl.set_ylim(-0.6, n_rows - 0.1)
    ax_tbl.axis("off")

    header_y = n_rows - 0.15
    ax_tbl.text(0.01, header_y, r"$\Delta$PR-AUC [95% NB CI]", fontsize=9.2, fontweight="bold", va="bottom")
    ax_tbl.text(0.51, header_y, r"$p_{\mathrm{Holm,\,NB}}$", fontsize=9.2, fontweight="bold", va="bottom", ha="center")
    ax_tbl.text(0.72, header_y, r"$p_{\mathrm{Holm,\,W}}$", fontsize=9.2, fontweight="bold", va="bottom", ha="center")
    ax_tbl.text(0.83, header_y, "Verdict", fontsize=9.2, fontweight="bold", va="bottom")
    ax_tbl.plot([0.0, 0.99], [n_rows - 0.35, n_rows - 0.35], color="#222222", linewidth=0.9)

    for y_pos, (comp_key, disp_label) in zip(y_positions, ordered_rows):
        r = prereg.loc[comp_key]
        delta = float(r["mean_delta"])
        lo = float(r["ci95_low"])
        hi = float(r["ci95_high"])
        p_nb = float(r.get("nb_p_holm", r["p_holm"]))
        p_w = float(r.get("wilcoxon_p_holm", r["p_holm"]))
        concl = str(r["conclusion"])

        if concl == "Confirmed Improvement":
            color, marker, short_v, bold = "#009E73", "D", "Confirmed", True
        elif hi < 0.0:
            color, marker, short_v, bold = "#D55E00", "s", "Neg. shift", p_nb < 0.05
        else:
            color, marker, short_v, bold = "#0072B2", "o", "Null", False

        ax.errorbar(
            delta,
            y_pos,
            xerr=[[max(0.0, delta - lo)], [max(0.0, hi - delta)]],
            fmt=marker,
            color=color,
            ecolor=color,
            elinewidth=1.8,
            capsize=3.8,
            markersize=6.0,
            zorder=3,
        )

        fw = "bold" if bold else "normal"
        ax_tbl.text(0.01, y_pos, f"{delta:+.4f} [{lo:+.4f}, {hi:+.4f}]", fontsize=8.8, fontweight=fw, va="center")
        ax_tbl.text(0.51, y_pos, _fmt_p(p_nb), fontsize=8.8, fontweight=fw, va="center", ha="center")
        ax_tbl.text(0.72, y_pos, _fmt_p(p_w), fontsize=8.8, va="center", ha="center")
        ax_tbl.text(0.83, y_pos, short_v, fontsize=8.8, fontweight="bold", color=color, va="center")

    ax.set_yticks(y_positions)
    ax.set_yticklabels([lbl for _, lbl in ordered_rows], fontsize=8.8)
    ax.set_ylim(-0.6, n_rows - 0.1)
    lo_min = float(prereg["ci95_low"].min())
    hi_max = float(prereg["ci95_high"].max())
    ax.set_xlim(min(-0.18, lo_min - 0.02), max(0.25, hi_max + 0.02))
    ax.set_xlabel(r"Paired $\Delta$PR-AUC (Model A $-$ Model B) with 95% Nadeau–Bengio CI ($\rho = 0.25$)", fontsize=9.2)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="x", alpha=0.2, linestyle=":")

    legend_handles = [
        Line2D([0], [0], color="#009E73", marker="D", lw=1.8, markersize=6, label=r"Confirmed ($\Delta \geq 0.02, \mathrm{CI}_{\mathrm{low}}>0, p_{\mathrm{Holm,NB}}<0.05$)"),
        Line2D([0], [0], color="#0072B2", marker="o", lw=1.8, markersize=6, label="No significant difference (CI overlaps 0)"),
        Line2D([0], [0], color="#D55E00", marker="s", lw=1.8, markersize=6, label=r"Negative shift ($\mathrm{CI}_{\mathrm{high}}<0$)"),
        Line2D([0], [0], color="#222222", linestyle="--", lw=1.0, label=r"Null ($\Delta = 0$)"),
        Line2D([0], [0], color="#009E73", linestyle=":", lw=1.2, label="MDE (+0.020)"),
    ]
    fig.legend(
        handles=legend_handles,
        loc="upper center",
        bbox_to_anchor=(0.56, 1.07),
        ncol=3,
        frameon=False,
        fontsize=8.5,
        columnspacing=1.2,
    )
    fig.subplots_adjust(top=0.84, bottom=0.14, left=0.28, right=0.99)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_pdf, bbox_inches="tight")
    plt.close(fig)


def build_shap_comparison_pdf(
    repo_root: Path,
    results_dir: Path,
    out_pdf: Path,
) -> dict[str, Any]:
    """Render two-panel Top-10 F-GSEM (E4c) vs Top-10 F-BIGRAM (E4b) TreeSHAP vector PDF."""
    xai = json.loads((results_dir / "xai_gsem_summary.json").read_text(encoding="utf-8"))
    gsem_top10 = xai["gsem_shap_ranking"][:10][::-1]

    e4b_bundle = compute_oof_predictions_for_seed(
        repo_root, results_dir, "E4b", seed=42, compute_shap=True
    )
    sv_4b = e4b_bundle["shap_values"]
    X_4b = e4b_bundle["X_eval"]
    bg_rows: list[dict[str, Any]] = []
    for j, col in enumerate(X_4b.columns):
        if not str(col).startswith("bigram__"):
            continue
        sv = sv_4b[:, j]
        xv = X_4b[col].to_numpy(dtype=np.float64)
        rho, _ = spearmanr(xv, sv)
        bg_rows.append(
            {
                "feature": str(col).removeprefix("bigram__"),
                "mean_abs_shap": float(np.mean(np.abs(sv))),
                "spearman_val_vs_shap": 0.0 if np.isnan(rho) else float(rho),
            }
        )
    bg_rows.sort(key=lambda r: r["mean_abs_shap"], reverse=True)
    bigram_top10 = bg_rows[:10][::-1]

    pos_color = "#c44e3a"
    neg_color = "#2f74a5"

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.2, 4.7))

    for ax, rows, title, xlabel in [
        (ax1, gsem_top10, "(a) Top-10 F-GSEM CFG Descriptors", "Mean |SHAP| (log-odds impact, E4c OOF)"),
        (ax2, bigram_top10, "(b) Top-10 F-BIGRAM Idioms (E4b)", "Mean |SHAP| (log-odds impact, E4b OOF)"),
    ]:
        y_pos = np.arange(len(rows))
        vals = [float(r["mean_abs_shap"]) for r in rows]
        rhos = [float(r["spearman_val_vs_shap"]) for r in rows]
        labels = [str(r["feature"]) for r in rows]
        colors = [pos_color if rho >= 0 else neg_color for rho in rhos]

        ax.barh(y_pos, vals, color=colors, height=0.68, alpha=0.95)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels, fontsize=8.8)
        ax.set_xlabel(xlabel, fontsize=9.2)
        ax.set_title(title, fontsize=10.5, pad=8)
        max_v = max(vals) if vals else 0.1
        ax.set_xlim(0.0, max_v * 1.48)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="x", alpha=0.22, linestyle=":")

        for yp, v, rho in zip(y_pos, vals, rhos):
            ax.text(v + max_v * 0.02, yp, f"{v:.3f} (r={rho:+.2f})", va="center", fontsize=8.3, color="#222222")

    legend_handles = [
        Patch(facecolor=pos_color, label=r"Higher feature value raises Ponzi risk ($\rho > 0$)"),
        Patch(facecolor=neg_color, label=r"Higher feature value lowers Ponzi risk ($\rho < 0$)"),
    ]
    fig.legend(
        handles=legend_handles,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.06),
        ncol=2,
        frameon=False,
        fontsize=9.2,
    )
    fig.tight_layout(rect=[0.0, 0.0, 1.0, 0.94], w_pad=3.2)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_pdf, bbox_inches="tight")
    plt.close(fig)

    return {"e4b_top10_bigrams": bg_rows[:10]}


def build_gas_vs_batch_pdf(results_dir: Path, out_pdf: Path) -> None:
    """Render publication-grade vector PDF (and synced PNG) of E5 gas scaling curve."""
    gas_df = pd.read_csv(results_dir / "E5_gas.csv")
    generate_gas_vs_batch_plot(gas_df, out_pdf)
    generate_gas_vs_batch_plot(gas_df, out_pdf.with_suffix(".png"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate vector PDF paper figures from results.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--only", nargs="*", default=None, help="Subset: pr, ci, shap, gas")
    args = parser.parse_args()

    root = args.repo_root.resolve()
    results_dir = root / "results"
    paper_figs = root / "paper" / "figures"
    selected = set(args.only) if args.only else {"pr", "ci", "shap", "gas"}

    if "pr" in selected:
        build_pr_curves_pdf(root, results_dir, paper_figs / "pr_curves.pdf")
        print(f"Saved {paper_figs / 'pr_curves.pdf'}", flush=True)
    if "ci" in selected:
        build_delta_pr_auc_ci_pdf(results_dir, paper_figs / "delta_pr_auc_ci.pdf")
        print(f"Saved {paper_figs / 'delta_pr_auc_ci.pdf'}", flush=True)
    if "shap" in selected:
        info = build_shap_comparison_pdf(root, results_dir, paper_figs / "shap_gsem_importance.pdf")
        print(f"Saved {paper_figs / 'shap_gsem_importance.pdf'} (top bigram: {info['e4b_top10_bigrams'][0]['feature']})", flush=True)
    if "gas" in selected:
        build_gas_vs_batch_pdf(results_dir, paper_figs / "gas_vs_batch.pdf")
        print(f"Saved {paper_figs / 'gas_vs_batch.pdf'}", flush=True)


if __name__ == "__main__":
    main()
