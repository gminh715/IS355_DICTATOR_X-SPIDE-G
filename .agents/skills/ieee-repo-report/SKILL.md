---
name: ieee-repo-report
description: >-
  Write and verify the English 2-column IEEEtran LaTeX report (max 10 pages) for
  the X-SPIDE-G repository using strictly verified empirical outputs,
  traceability records, and existing figures. Use when drafting, compressing,
  compiling, or auditing the IEEE paper for this repository.
---

# X-SPIDE-G IEEE LaTeX Paper Workflow (Max 10 Pages, 2-Column)

Use this project skill together with the installed skills (`ieee-paper-writing`,
`ieee-latex-writer`, `empirical-paper-writer`, `results-backfill`,
`latex-paper-en`, `latex-rhythm-refiner`, and `paper-audit`) whenever writing
or revising the English IEEE paper for this repository.

## Target Format & Hard Constraints

1. **Class & Layout:** Official 2-column IEEE format via
   `\documentclass[conference]{IEEEtran}` or `\documentclass[journal]{IEEEtran}`
   (reuse `IEEEtran.cls` from
   `.agents/skills/ieee-latex-writer/assets/ieee-official-templates/IEEEtran.cls`).
2. **Page Budget:** **At most 10 pages** in the compiled PDF (including title,
   abstract, index terms, all figures/tables, and references).
   - Never estimate page count from word count. Compile to PDF (`pdflatex` +
     `bibtex`) and verify the exact page count from the PDF before finishing.
3. **Recommended Output Directory:** `paper/` (`paper/main.tex`,
   `paper/references.bib`, `paper/IEEEtran.cls`, `paper/main.pdf`).

## Authoritative Data & Evidence Sources (Do Not Fabricate)

Every quantitative claim, dataset count, model score, statistical test, gas
figure, latency metric, deployment address, and citation must trace to files in
this repository:

- **Traceability Matrix (Primary Ground Truth):**
  - `reports/traceability_matrix.md` and `results/traceability_matrix.csv`
- **Synthesized & Per-Phase Reports:**
  - `reports/final_report.md` (includes verified reference list `[1]`–`[13]`)
  - `reports/data_audit.md`, `reports/data_audit_summary.json`
  - `reports/rq1_reproduction.md`, `reports/rq2_results.md`, `reports/rq3_onchain.md`
  - `docs/preregistration.md`, `docs/threat_model.md`, `docs/contract_spec.md`,
    `docs/evidence_schema_v1.md`
  - `deployments.json`, `reports/contract_coverage.md`
- **Raw Result Tables & JSONs (`results/`):**
  - `results/E0_reproduction.csv`, `results/model_comparison.csv`,
    `results/stat_tests.csv`, `results/sensitivity_summary.csv`,
    `results/feature_extraction_cost.csv`, `results/E6_sanity_check.csv`,
    `results/xai_gsem_summary.json`, `results/error_analysis_cases.csv`,
    `results/E5_gas.csv`, `results/E5_latency.csv`, `results/E5_summary.json`
- **Pre-Rendered Figures (`figures/`):**
  - `pr_curves.png`, `delta_pr_auc_ci.png`, `gas_vs_batch.png`,
    `shap_beeswarm_E1.png`, `shap_beeswarm_E4c.png`,
    `shap_gsem_importance.png`, `shap_waterfall_tp.png`,
    `shap_waterfall_fp.png`, `shap_waterfall_fn.png`,
    `cfg_tp.png`, `cfg_fp.png`, `cfg_fn.png`

## Non-Negotiable Content & Academic Rules

1. **Zero Fabrication & Verbatim Honesty:**
   - Do not invent numbers, p-values, confidence intervals, baselines, or DOIs.
   - Report pre-registered negative and constrained results honestly:
     - `F-GSEM` (`E4c`, `E4d`) failed MDE ($\Delta\text{PR-AUC} \ge 0.02$) /
       statistical significance vs `E1` and `E4b`, whereas in-fold `F-BIGRAM`
       (`E4b`) achieved a Confirmed Improvement (`+0.0227 PR-AUC`).
     - Temporal holdout `S3` is `N/A` (missing `block_number` / BigQuery).
     - External `E6` PonziGuard check (`n=107`, 10 Ponzis) is `SANITY_CHECK_ONLY`
       (Risk `R6`).
     - `D1` single-case attestation (`427,461` Cancun gas) **fails** the
       `250,000`-gas ceiling, motivating `D3_MerkleBatch` (`3,574.53` gas/case
       at $N=100$, passing `<= 10,000`).
     - Testnet boundaries (`owner_type='eoa_demo_limit'`, Arbitrum Sepolia
       `gasUsedForL1 = 0x0`, Sepolia EIP-8037 state-creation repricing).
2. **Academic Style Cleanup:**
   - Convert internal course/project jargon (`Phase 0..8`, raw file paths like
     `src/...`, internal task codes `DATA-01`/`STAT-...`) into clean IEEE
     academic prose; define experiment abbreviations (`E0`–`E6`, `F-BIGRAM`,
     `F-GSTAT`, `F-GSEM`, `D1`–`D3`) clearly on first use if retained.
   - Write in cohesive English academic paragraphs; avoid bullet-heavy prose.
   - Follow `latex-paper-en` + `latex-rhythm-refiner` to remove AI-sounding
     filler phrases, and run `paper-audit` + `ieee-latex-writer` static checks.

## Suggested Section Budget (<= 10 Pages IEEE 2-Column)

- **Title, Authors, Abstract & Index Terms** (~0.4 page)
- **I. Introduction** (~1.0 page): motivation, RQ1–RQ3, 3–4 crisp contributions
- **II. Related Work & Research Gaps** (~0.8 page): unigram/n-gram detectors,
  CFG/CRBG methods, on-chain audit provenance
- **III. Threat Model, Corpus Audit & Anti-Leakage Protocol** (~1.3 pages):
  4-role trust model, CBOR stripping + MinHash LSH (`group_near`)
- **IV. Methodology** (~2.2 pages): bytecode feature families (`F-BIGRAM`,
  `F-GSTAT`, `F-GSEM`), nested Optuna/CV + Nadeau–Bengio/Holm stats, Vyper
  `D1`/`D2`/`D3` + canonical evidence & client-side signer
- **V. Experimental Evaluation (RQ1–RQ3)** (~2.5 pages): clone leakage
  (`E0`–`E2`), feature ablations & SHAP/error audit (`E3`–`E4d`, `S1`–`S4`,
  `E6`), on-chain gas/latency/security (`E5`) with compact tables & 3–4 key
  figures (`pr_curves`, `delta_pr_auc_ci`, `shap_gsem_importance`, `gas_vs_batch`)
- **VI. Discussion, Threats to Validity & Limitations** (~0.8 page)
- **VII. Conclusion & References** (~1.0 page)

## Build & Verification Checklist

1. Copy `IEEEtran.cls` from
   `.agents/skills/ieee-latex-writer/assets/ieee-official-templates/IEEEtran.cls`
   into `paper/` (or ensure `kpsewhich IEEEtran.cls` resolves).
2. Compile with `pdflatex` + `bibtex` + `pdflatex` x2 (zero undefined references
   `??`, zero missing figures, inspect overfull `\hbox` warnings).
3. Verify exact page count (`<= 10`) on `paper/main.pdf` using `pdfinfo paper/main.pdf` (bundled with MiKTeX).
4. Run `paper-audit` and `ieee-latex-writer` checks before delivering.
