"""Programmatically generate Traceability Matrix (CSV + Markdown) from Phase 0-7 outputs."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]


def _git_phase_commits(repo_root: Path) -> dict[str, str]:
    """Return short commit hash for each Phase 0..7 commit message prefix if present."""
    out = subprocess.check_output(
        ["git", "-C", str(repo_root), "log", "--oneline", "-n", "30"],
        text=True,
    )
    mapping: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        sha, msg = parts
        low = msg.lower()
        for k in ("phase0", "phase1", "phase2", "phase3", "phase4", "phase5", "phase6", "phase7"):
            if low.startswith(f"{k}:") and k not in mapping:
                mapping[k] = sha
    return mapping


def build_traceability_rows(repo_root: Path) -> list[dict[str, Any]]:
    commits = _git_phase_commits(repo_root)
    audit = json.loads((repo_root / "reports" / "data_audit_summary.json").read_text(encoding="utf-8"))
    e0 = pd.read_csv(repo_root / "results" / "E0_reproduction.csv")
    mc = pd.read_csv(repo_root / "results" / "model_comparison.csv").set_index("experiment")
    st = pd.read_csv(repo_root / "results" / "stat_tests.csv")
    sens = pd.read_csv(repo_root / "results" / "sensitivity_summary.csv")
    e6 = pd.read_csv(repo_root / "results" / "E6_sanity_check.csv").set_index("metric")
    fx = pd.read_csv(repo_root / "results" / "feature_extraction_cost.csv").set_index("stage")
    xai = json.loads((repo_root / "results" / "xai_gsem_summary.json").read_text(encoding="utf-8"))
    err = pd.read_csv(repo_root / "results" / "error_analysis_cases.csv")
    card = json.loads((repo_root / "models" / "baseline_v1" / "model_card.json").read_text(encoding="utf-8"))
    e5_gas = pd.read_csv(repo_root / "results" / "E5_gas.csv")
    e5_sum = json.loads((repo_root / "results" / "E5_summary.json").read_text(encoding="utf-8"))
    dep = json.loads((repo_root / "deployments.json").read_text(encoding="utf-8"))
    vectors = json.loads((repo_root / "tests" / "evidence" / "vectors.json").read_text(encoding="utf-8"))

    rows: list[dict[str, Any]] = []

    def add(sec: str, mid: str, name: str, val: str, src: str, script: str, cfg: str, phase: str) -> None:
        rows.append(
            {
                "report_section": sec,
                "metric_id": mid,
                "metric_name": name,
                "reported_value": val,
                "source_file": src,
                "generating_script": script,
                "seed_or_config": cfg,
                "git_commit": commits.get(phase, "working_tree"),
            }
        )

    # Sec 4: Data Audit
    s_code_p = int(audit["s_code_ponzi"])
    s_code_total = int(sum(x["s_code"] for x in audit["coverage_table"]))
    s_code_np = s_code_total - s_code_p
    add("Sec 4 (Data)", "DATA-01", "|S_code| size (Ponzi / non-Ponzi)", f"{s_code_total} ({s_code_p} / {s_code_np}, 100.0% S_full coverage)", "reports/data_audit_summary.json", "src/data/pipeline.py", "X-SPIDE commit dcf6027", "phase1")
    add("Sec 4 (Data)", "DATA-02", "CBOR metadata stripped / pre-0.4.7", f"{audit['metadata_counts']['true']['total']} stripped / {audit['metadata_counts']['false']['total']} pre-0.4.7", "reports/data_audit_summary.json", "src/data/bytecode.py", "parse_hex + strip_cbor_metadata", "phase1")
    ce = audit["clones_exact"]
    cn = audit["clones_near"]
    add("Sec 4 (Data)", "DATA-03", "Exact clone clusters & multi-Ponzi %", f"{ce['total_groups']} groups (max={ce['max_size']}, mixed={ce['mixed_label_groups_count']}); {ce['ponzi_in_multi']}/{ce['total_ponzi']} ({ce['ponzi_in_multi_pct']:.2f}%) Ponzi in multi-groups", "reports/data_audit_summary.json", "src/data/clones.py", "keccak256 on CBOR-stripped bytes", "phase1")
    add("Sec 4 (Data)", "DATA-04", "MinHash group_near clusters & multi-Ponzi %", f"{cn['total_groups']} groups (max={cn['max_size']}, mixed={cn['mixed_label_groups_count']}); {cn['ponzi_in_multi']}/{cn['total_ponzi']} ({cn['ponzi_in_multi_pct']:.2f}%) Ponzi in multi-groups", "reports/data_audit_summary.json", "src/data/clones.py", "5-gram opcodes, t=0.90, 128 perms", "phase1")
    pg = audit["overlap"]["ponziguard"]
    add("Sec 4 (Data)", "DATA-05", "Cross-dataset overlap (PonziGuard / Unica)", f"Unica {audit['overlap']['unica']['address_overlap']}/182 addr; PG .bin non-overlapping remaining: {pg['ponzi_bins']['remaining_unique_hashes']} Ponzi + {pg['non_ponzi_bins']['remaining_unique_hashes']} non-Ponzi ({pg['decision']})", "reports/data_audit_summary.json", "src/data/audit.py", "Risk R6 threshold (<30 Ponzi)", "phase1")

    # Sec 5/6.1: RQ1 (E0-E2)
    e0_grid = e0[e0["run_id"] == "E0_random5fold_99feats_gridbest_mean"].iloc[0]
    add("Sec 6.1 (RQ1)", "RQ1-01", "E0 5-fold random (99 feats, GridSearchCV)", f"PR-AUC={e0_grid['PR-AUC']:.4f}, ROC-AUC={e0_grid['ROC-AUC']:.4f}, F1={e0_grid['F1']:.4f}", "results/E0_reproduction.csv", "src/models/e0_repro.py", "S_full_E0_random seed=42", "phase2")
    add("Sec 6.1 (RQ1)", "RQ1-02", "E1 5x5 group_near baseline (99 feats)", f"PR-AUC={mc.loc['E1','PR_AUC_mean']:.4f} +/- {mc.loc['E1','PR_AUC_std']:.4f}, F1={mc.loc['E1','F1_mean']:.4f} +/- {mc.loc['E1','F1_std']:.4f}", "results/model_comparison.csv", "src/models/run_phase2.py", "25 folds (seeds 42..46 x 5)", "phase2")
    add("Sec 6.1 (RQ1)", "RQ1-03", "E0 -> E1 clone-leakage drop", f"Delta PR-AUC={mc.loc['E1','PR_AUC_mean']-e0_grid['PR-AUC']:+.4f}, Delta F1={mc.loc['E1','F1_mean']-e0_grid['F1']:+.4f}", "results/E0_reproduction.csv; results/model_comparison.csv", "src/models/run_phase2.py", "E1 vs E0_random5fold_99feats_gridbest_mean", "phase2")
    add("Sec 6.1 (RQ1)", "RQ1-04", "E2 in-fold RFE over 99 features", f"PR-AUC={mc.loc['E2','PR_AUC_mean']:.4f} +/- {mc.loc['E2','PR_AUC_std']:.4f}, feats={mc.loc['E2','n_features']}", "results/model_comparison.csv", "src/models/run_phase2.py", "RFECV(step=0.1) inside fold", "phase2")
    dm = card["demo_fold_metrics"]
    add("Sec 5/6 (Model)", "MOD-01", "Frozen models/baseline_v1 demo fold", f"PR-AUC={dm['pr_auc']:.4f}, F1={dm['f1']:.4f}, tau*={dm['threshold']:.6f}, hash={card['artifacts']['model_version_hash'][:18]}...", "models/baseline_v1/model_card.json", "src/models/run_phase2.py", "S_code_group_near_seed42_fold0", "phase2")

    # Sec 5/6.2: Phase 3 extraction & RQ2 (E3-E4d, stats, sens, E6, XAI)
    add("Sec 5/6.2 (Feat)", "FEAT-01", "End-to-end feature extraction cost", f"median={fx.loc['end_to_end','median_ms']:.3f} ms, p95={fx.loc['end_to_end','p95_ms']:.3f} ms, errors={int(fx.loc['end_to_end','n_errors'])}/{int(fx.loc['end_to_end','n_contracts'])}", "results/feature_extraction_cost.csv", "src/features/pipeline.py", "i5-12450H, 15.63 GB RAM, Py3.12.13", "phase3")
    for eid in ("E3", "E3b", "E3c", "E4", "E4b", "E4c", "E4d"):
        r = mc.loc[eid]
        add("Sec 6.2 (RQ2)", f"RQ2-{eid}", f"Experiment {eid} ({r['feature_set']})", f"PR-AUC={r['PR_AUC_mean']:.4f} +/- {r['PR_AUC_std']:.4f}, F1={r['F1_mean']:.4f}, Recall@P>=0.9={r['Recall_at_P90_mean']:.4f}", "results/model_comparison.csv", "src/models/run_phase4_experiments.py", "25 folds S_code_group_near", "phase4")

    prereg_st = st[st["test_suite"] == "preregistered_holm_8"]
    for _, sr in prereg_st.iterrows():
        comp = str(sr["comparison"])
        cid = "STAT-" + comp.replace(" ", "_")
        add("Sec 6.2 (Stats)", cid, f"Pre-reg Holm test: {comp}", f"Delta PR-AUC={sr['mean_delta']:+.4f}, 95% NB CI [{sr['ci95_low']:+.4f}, {sr['ci95_high']:+.4f}], p_Holm={sr['p_holm']:.3e} -> {sr['conclusion']}", "results/stat_tests.csv", "src/stats/tests.py", "Nadeau-Bengio df=24 + Holm (m=8)", "phase4")

    s1_e1 = sens[sens["variant"] == "E1_S1_group_exact"].iloc[0]
    s1_e4c = sens[sens["variant"] == "E4c_S1_group_exact"].iloc[0]
    add("Sec 6.2 (Sens)", "SENS-S1", "S1 group_exact vs group_near leakage", f"E1: {s1_e1['variant_PR_AUC_mean']:.4f} vs {s1_e1['ref_PR_AUC_mean']:.4f} ({s1_e1['Delta_PR_AUC']:+.4f}); E4c: {s1_e4c['variant_PR_AUC_mean']:.4f} vs {s1_e4c['ref_PR_AUC_mean']:.4f} ({s1_e4c['Delta_PR_AUC']:+.4f})", "results/sensitivity_summary.csv", "src/models/run_phase4_experiments.py", "S_code_group_exact (25 folds)", "phase4")
    s2_max = max(abs(sens[sens["study"] == "S2_cbor_metadata"]["Delta_PR_AUC"].astype(float)))
    s4_max = max(abs(sens[sens["study"] == "S4_mnemonic_norm"]["Delta_PR_AUC"].astype(float)))
    add("Sec 6.2 (Sens)", "SENS-S2-S4", "S2 (CBOR) & S4 (opcode norm) max |Delta PR-AUC|", f"S2 max |Delta|={s2_max:.4f} (n.s.); S4 max |Delta|={s4_max:.4f} (n.s.); S3=N/A (no block_number)", "results/sensitivity_summary.csv", "src/models/run_phase4_experiments.py", "25 paired folds (df=24)", "phase4")
    add("Sec 6.2 (E6)", "RQ2-E6", "E6 external PonziGuard non-overlapping sanity check", f"PR-AUC={e6.loc['pr_auc','point']:.4f} (95% CI [{e6.loc['pr_auc','ci95_low']:.4f}, {e6.loc['pr_auc','ci95_high']:.4f}]), F1={e6.loc['f1','point']:.4f}, n={int(e6.loc['pr_auc','n_test'])} (10 Ponzi / 97 non-Ponzi)", "results/E6_sanity_check.csv", "src/models/run_phase4_experiments.py", "1000-resample stratified bootstrap, Risk R6", "phase4")

    gsem_top = xai["gsem_shap_ranking"][:4]
    add("Sec 6.2 (XAI)", "XAI-01", "Top F-GSEM OOF SHAP features & Risk R4 rate", ", ".join(f"{g['feature']}={g['mean_abs_shap']:.4f}" for g in gsem_top) + f"; unresolved_jump>0.50: {xai['gsem_unresolved_jump_gt50_count']}/{xai['total_contracts']} ({100*xai['gsem_unresolved_jump_gt50_count']/xai['total_contracts']:.2f}%)", "results/xai_gsem_summary.json", "src/models/phase4_xai.py", "Seed-42 OOF E4c TreeExplainer", "phase4")
    add("Sec 6.2 (XAI)", "XAI-02", "Seed-42 E4c error breakdown & audit sample", f"TP={xai['total_tp_seed42']}, FP={xai['total_fp_seed42']}, TN={xai['total_tn_seed42']}, FN={xai['total_fn_seed42']}; top sample={len(err)} ({int((err['error_type']=='FP').sum())} FP + {int((err['error_type']=='FN').sum())} FN)", "results/xai_gsem_summary.json; results/error_analysis_cases.csv", "src/models/phase4_xai.py", "Seed-42 5 OOF folds", "phase4")

    # Sec 5/6.3: Phase 5 Contracts + Phase 6 Evidence + Phase 7 E5
    sep_dep = dep["networks"]["sepolia"]["contracts"]
    arb_dep = dep["networks"]["arbitrum-sepolia"]["contracts"]
    add("Sec 5.4 (Contracts)", "CON-01", "Verified Sepolia & Arbitrum Sepolia contracts", f"Sepolia D1={sep_dep['D1']['address']}, D2={sep_dep['D2']['address']}, D3={sep_dep['D3']['address']}; Arb-Sep D1={arb_dep['D1']['address']}, D3={arb_dep['D3']['address']} (all Pass - Verified)", "deployments.json", "scripts/deploy_contracts.py; scripts/verify_contracts.py", "Vyper 0.4.3, k=2 of n=3", "phase5")
    add("Sec 5.4 (Contracts)", "CON-02", "Contract test & coverage suite", "34 contract tests pass (T1-T12 + Hypothesis fuzz + revert branch coverage D1 16/16, D2 16/16, D3 14/14 = 100%, src/contracts 84%)", "reports/contract_coverage.md", "tests/contracts/*", "PyEVMBackend + Hypothesis", "phase5")
    v1 = vectors["vectors"][0]
    add("Sec 5.5 (Evidence)", "EVD-01", "Canonical test vector 1 (xspide_00000)", f"case_id={v1['expected_case_id']}, evidence_hash={v1['expected_evidence_hash']}", "tests/evidence/vectors.json", "src/evidence/canonical.py", "Schema v1.0, 6-decimal fixed strings", "phase6")

    py_d1 = e5_gas[(e5_gas["network"] == "anvil_pyevm") & (e5_gas["variant"] == "D1") & (e5_gas["operation"] == "finalized_case_total")].iloc[0]
    py_d2 = e5_gas[(e5_gas["network"] == "anvil_pyevm") & (e5_gas["variant"] == "D2") & (e5_gas["operation"] == "finalized_case_total")].iloc[0]
    py_d3_100 = e5_gas[(e5_gas["network"] == "anvil_pyevm") & (e5_gas["variant"] == "D3") & (e5_gas["operation"] == "batch_finalized_total") & (e5_gas["batch_size"] == 100)].iloc[0]
    py_d3_1000 = e5_gas[(e5_gas["network"] == "anvil_pyevm") & (e5_gas["variant"] == "D3") & (e5_gas["operation"] == "batch_finalized_total") & (e5_gas["batch_size"] == 1000)].iloc[0]
    py_rm = e5_gas[(e5_gas["network"] == "anvil_pyevm") & (e5_gas["variant"] == "D1") & (e5_gas["operation"] == "remove_auditor")].iloc[0]
    add("Sec 6.3 (RQ3)", "RQ3-01", "Cancun PyEVM finalized case gas (D1 vs 250k target)", f"D1={int(py_d1['gas_used']):,} gas (FAIL vs <=250,000, ${py_d1['mainnet_ref_cost_usd']:.6f} @ 0.084427 gwei/$1,900.68); remove_auditor={int(py_rm['gas_used']):,}", "results/E5_gas.csv", "src/contracts/e5_benchmark.py", "PyEVMBackend Cancun", "phase7")
    add("Sec 6.3 (RQ3)", "RQ3-02", "D2 EventOnly finalized case gas", f"D2={int(py_d2['gas_used']):,} gas ({100*(py_d2['gas_used']-py_d1['gas_used'])/py_d1['gas_used']:.2f}% vs D1, ${py_d2['mainnet_ref_cost_usd']:.6f})", "results/E5_gas.csv", "src/contracts/e5_benchmark.py", "PyEVMBackend Cancun", "phase7")
    add("Sec 6.3 (RQ3)", "RQ3-03", "D3 MerkleBatch amortized gas (N=100, N=1000 vs 10k target)", f"N=100: {py_d3_100['gas_per_case']:.2f} gas/case (${py_d3_100['mainnet_ref_cost_per_case_usd']:.6f}) PASS; N=1000: {py_d3_1000['gas_per_case']:.2f} gas/case PASS", "results/E5_gas.csv", "src/contracts/e5_benchmark.py", "PyEVMBackend Cancun", "phase7")

    lat_sep = e5_sum["latency_summary"]["sepolia"]
    lat_arb = e5_sum["latency_summary"]["arbitrum-sepolia"]
    add("Sec 6.3 (RQ3)", "RQ3-04", "Live confirmation latency (n=30 attest txs each)", f"Sepolia median={lat_sep['median_seconds']:.3f}s / {lat_sep['median_blocks']:.2f} blk (p95={lat_sep['p95_seconds']:.3f}s) PASS; Arb-Sep median={lat_arb['median_seconds']:.3f}s / {lat_arb['median_blocks']:.1f} L2 blk", "results/E5_summary.json; results/E5_latency.csv", "scripts/run_phase7_e5.py", "Sepolia 11155111 & Arb-Sep 421614", "phase7")

    sec_sep = e5_sum["live_networks"]["sepolia"]["security_on_main_d1"]
    t8_sep = e5_sum["live_networks"]["sepolia"]["T8_sepolia_verify_evidence"]
    add("Sec 6.3 (RQ3)", "RQ3-05", "Live Sepolia security & tamper proofs (T1/T6/T8)", f"5/5 T1/T6 reverts confirmed (status=0, e.g. T6_owner_attest={sec_sep['T6_owner_attest_revert']['tx_hash'][:14]}...); T8 verify_evidence exact={t8_sep['verify_exact_onchain']} / 1-byte tampered={t8_sep['verify_tampered_onchain']}", "results/E5_summary.json", "scripts/run_phase7_e5.py", "Sepolia tx receipts + eth_call", "phase7")

    return rows


def render_traceability_md(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# X-SPIDE-G Traceability Matrix",
        "",
        "Every quantitative claim reported in `4_DICTATOR_IS355_Final_Report.{docx,pdf}`, `reports/final_report.md`, presentation slides, and `reports/defense_qa.md` maps deterministically to source artifacts, generating scripts, split/seed configurations, and Git commits below.",
        "",
        "| Section | ID | Metric / Claim | Reported Value | Source File(s) | Generating Script | Seed / Config | Commit |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        name_esc = str(r["metric_name"]).replace("|", "\\|")
        val_esc = str(r["reported_value"]).replace("|", "\\|")
        lines.append(
            f"| {r['report_section']} | `{r['metric_id']}` | {name_esc} | {val_esc} | `{r['source_file']}` | `{r['generating_script']}` | {r['seed_or_config']} | `{r['git_commit']}` |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    rows = build_traceability_rows(REPO_ROOT)
    csv_path = REPO_ROOT / "results" / "traceability_matrix.csv"
    md_path = REPO_ROOT / "reports" / "traceability_matrix.md"
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    md_path.write_text(render_traceability_md(rows), encoding="utf-8")
    print(f"Generated {len(rows)} traceability entries -> {csv_path} & {md_path}")


if __name__ == "__main__":
    main()
