# X-SPIDE-G

**Graph-Enhanced Explainable Ponzi Detection and On-Chain Risk Attestation for Ethereum Smart Contracts**  
*IS355 – Blockchain Technology · Group 4 – DICTATOR · UIT – VNU-HCM*

## Overview

X-SPIDE-G reproduces the X-SPIDE LightGBM Ethereum Ponzi detector under strict CBOR-stripped exact and MinHash clone-grouped validation (`5 × 5` repeated `StratifiedGroupKFold`), evaluates whether explicit opcode bigrams (`F-BIGRAM`), transition-graph statistics (`F-GSTAT`), and lightweight basic-block CFG semantic features (`F-GSEM`) improve `PR-AUC` over the 99-feature baseline (`ΔPR-AUC ≥ 0.02` MDE), and anchors canonical SHAP-backed risk evidence to a $k$-of-$n$ (default 2-of-3) Vyper `RiskAttestationRegistry` signed client-side via `ethers.js v6` + MetaMask.

## Execution Plan & Phase Specifications

- Master plan: [KE_HOACH_THUC_HIEN_X-SPIDE-G.md](KE_HOACH_THUC_HIEN_X-SPIDE-G.md)
- Phase 0 Design Specification: [docs/design_v2.md](docs/design_v2.md)
- Threat Model & "Why Blockchain?": [docs/threat_model.md](docs/threat_model.md)
- Pre-Registered Evaluation Protocol: [docs/preregistration.md](docs/preregistration.md)
- Phase 1 Data Audit Report: [reports/data_audit.md](reports/data_audit.md)
- Phase 2 RQ1 Reproduction Report: [reports/rq1_reproduction.md](reports/rq1_reproduction.md)
- Phase 3 Feature Extraction Cost Report: [results/feature_extraction_cost.csv](results/feature_extraction_cost.csv)
- Phase 4 RQ2 Experiments & XAI Report: [reports/rq2_results.md](reports/rq2_results.md)
- Phase 5 Contract Spec, Security Review, Coverage & Deployments: [docs/contract_spec.md](docs/contract_spec.md) · [docs/security_review.md](docs/security_review.md) · [reports/contract_coverage.md](reports/contract_coverage.md) · [deployments.json](deployments.json)
- Frozen Baseline Model Card: [models/baseline_v1/model_card.json](models/baseline_v1/model_card.json)

## Repository Status

- **Phase 0 (Design Freeze & Pre-Registration):** Completed — unified design, threat model, pre-registration criteria, and aligned Week 3 report (`4_DICTATOR_IS355_Week3.docx`).
- **Phase 1 (Data Audit, Clone Clustering & Splits):** Completed — verified `data/manifest.json`, `data/processed/contracts.parquet` (`|S_full| = |S_code| = 7,446`: 880 Ponzi / 6,566 non-Ponzi), CBOR metadata stripping, `group_exact` & MinHash `group_near` clustering, Dataset 2 overlap decision (`SANITY_CHECK_ONLY`, Risk R6), and 55 frozen split JSONs (`splits/`). Note: `S_code_temporal_holdout.json` (`S3`) was not generated due to missing `block_number` and BigQuery credentials.
- **Phase 2 (X-SPIDE Baseline Reproduction `E0`–`E2`):** Completed — `results/E0_reproduction.csv`, `results/E1_folds.csv`, `results/E1_full_folds.csv`, `results/E2_folds.csv`, frozen `models/baseline_v1/` artifact (`modelVersionHash` recorded in `model_card.json`), and `reports/rq1_reproduction.md`.
- **Phase 3 (Opcode Feature Extraction: `F-BIGRAM`, `F-GSTAT`, `F-GSEM`):** Completed — `src/features/{disasm,bigram,gstat,gsem,pipeline}.py` generated `data/processed/features_{bigram,gstat,gsem}.parquet` (`7,446` contracts, `0` extraction errors, median `16.58 ms`/contract end-to-end) and `results/feature_extraction_cost.csv`, with leak-free in-fold `BigramTopKVectorizer` (`top_k=200`).
- **Phase 4 (Feature Engineering Ablations `E3`–`E4d`, Sensitivity `S1`–`S4`, Conditional `E6`, Stats & XAI):** Completed — 25-fold `5 × 5` grouped CV across `E3`–`E4d` and `S1`/`S2`/`S4` (`S3` `N/A`), Holm-adjusted Nadeau–Bengio & Wilcoxon tests (`E4b vs E1`: `ΔPR-AUC = +0.0227`, 95% CI `[+0.0096, +0.0358]`, `p_Holm = 4.77e-7` Confirmed Improvement; `E4c vs E1`: `95% CI [-0.0037, +0.0152]`), PonziGuard `E6` sanity check (`SANITY_CHECK_ONLY`, Risk R6, `PR-AUC = 0.6535`, `n_test = 107`), global/local SHAP + CFG visualizations (`figures/`, `11` PNGs), `12 FP + 12 FN` error analysis (`results/error_analysis_cases.csv`), and `reports/rq2_results.md`.
- **Phase 5 (Vyper Smart Contracts, Security Review & Deployments):** Completed — compiled Vyper `0.4.3` contracts (`D1`: `contracts/RiskAttestationRegistry.vy`, `D2`: `contracts/variants/D2_EventOnly.vy`, `D3`: `contracts/variants/D3_MerkleBatch.vy`) + artifacts (`contracts/artifacts/`), `docs/contract_spec.md`, `docs/security_review.md`, `reports/contract_coverage.md`, `ape-config.yaml`, `.env.example`, and `scripts/{deploy_contracts,verify_contracts}.py`. All `34` contract tests (`T1`–`T12`, `100%` revert-branch coverage across `D1` 16/16, `D2` 16/16, `D3` 14/14, Hypothesis fuzzing + `set_threshold` deferral regression, and deploy/verify script checks) pass on `PyEVMBackend`. Recorded `3`-auditor / `threshold = 2` deployments in [deployments.json](deployments.json) across `local-evm`, `anvil` (`chain_id = 31337` via local `PyEVMBackend` JSON-RPC bridge because native `anvil.exe` is blocked by Windows Application Control and Docker Desktop is offline), live `sepolia` (`D1`, `D2`, `D3` `"Pass - Verified"` on Etherscan v2, `owner_type = "eoa_demo_limit"`), and live `arbitrum-sepolia` (`D1`, `D3` `"Pass - Verified"` on Etherscan v2 / Arbiscan Sepolia, `owner_type = "eoa_demo_limit"`).
- **Phases 6–8:** Pending execution following exit-criteria gates (see [KE_HOACH_THUC_HIEN_X-SPIDE-G.md](KE_HOACH_THUC_HIEN_X-SPIDE-G.md)).

## Deployed Contracts (`deployments.json`)

| Network | Chain ID | Variant | Address | Verification |
|---|---|---|---|---|
| `sepolia` | `11155111` | `D1` (`RiskAttestationRegistry`) | `0x14895F5e1f7F1aC5C58b35dA6d57674Aa5951b77` | Pass - Verified |
| `sepolia` | `11155111` | `D2` (`D2_EventOnly`) | `0x693632c45108A9ca25a7F9d693c00554EeDD1EB1` | Pass - Verified |
| `sepolia` | `11155111` | `D3` (`D3_MerkleBatch`) | `0xf04fd7BD0Ee4DBf28d19D7D02988ac01fD989eF2` | Pass - Verified |
| `arbitrum-sepolia` | `421614` | `D1` (`RiskAttestationRegistry`) | `0x14895F5e1f7F1aC5C58b35dA6d57674Aa5951b77` | Pass - Verified |
| `arbitrum-sepolia` | `421614` | `D3` (`D3_MerkleBatch`) | `0x693632c45108A9ca25a7F9d693c00554EeDD1EB1` | Pass - Verified |
| `anvil` (`PyEVM` RPC) | `31337` | `D1` / `D2` / `D3` | `0x5FbDB...0aa3` / `0x5FC8d...5707` / `0x61017...D788` | Local dev RPC |

*(Live `sepolia` and `arbitrum-sepolia` deployments use EOA owner `0x950e0416b13153d542d07Bf7f9AB586B0e903465`, recorded as `owner_type = "eoa_demo_limit"`, with `3` auditors and `threshold = 2`.)*

## Verification Commands

```powershell
.\.venv\Scripts\python.exe -m pytest -v
.\.venv\Scripts\python.exe -m pytest tests/contracts --cov=src/contracts --cov-report=term-missing -v
.\.venv\Scripts\python.exe -m scripts.deploy_contracts --network local-evm
.\.venv\Scripts\python.exe -m scripts.deploy_contracts --network arbitrum-sepolia
.\.venv\Scripts\python.exe -m scripts.verify_contracts --network arbitrum-sepolia --variants D1 D3
.\.venv\Scripts\python.exe -m src.features.pipeline
```
