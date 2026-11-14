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
- Phase 6 Canonical Evidence & DApp Spec: [docs/evidence_schema_v1.md](docs/evidence_schema_v1.md) · [app/streamlit_app.py](app/streamlit_app.py) · [signer/index.html](signer/index.html) · [tests/evidence/vectors.json](tests/evidence/vectors.json)
- Phase 7 On-Chain Evaluation (`E5`) Report & Data: [reports/rq3_onchain.md](reports/rq3_onchain.md) · [results/E5_gas.csv](results/E5_gas.csv) · [results/E5_latency.csv](results/E5_latency.csv) · [results/E5_summary.json](results/E5_summary.json) · [figures/gas_vs_batch.png](figures/gas_vs_batch.png)
- Phase 8 Final Synthesis, Reproducibility & Defense Package:
  - Final Report: [4_DICTATOR_IS355_Final_Report.pdf](4_DICTATOR_IS355_Final_Report.pdf) · [4_DICTATOR_IS355_Final_Report.docx](4_DICTATOR_IS355_Final_Report.docx) · [reports/final_report.md](reports/final_report.md)
  - Presentation & Live Demo: [4_DICTATOR_IS355_Final_Presentation.pdf](4_DICTATOR_IS355_Final_Presentation.pdf) · [4_DICTATOR_IS355_Final_Presentation.pptx](4_DICTATOR_IS355_Final_Presentation.pptx) · [demo/X-SPIDE-G_demo.mp4](demo/X-SPIDE-G_demo.mp4) · [reports/demo_script.md](reports/demo_script.md) · [demo/screenshots/](demo/screenshots)
  - Traceability & Defense Q&A: [results/traceability_matrix.csv](results/traceability_matrix.csv) · [reports/traceability_matrix.md](reports/traceability_matrix.md) · [reports/defense_qa.md](reports/defense_qa.md)
- Frozen Baseline Model Card: [models/baseline_v1/model_card.json](models/baseline_v1/model_card.json)

## Repository Status

- **Phase 0 (Design Freeze & Pre-Registration):** Completed — unified design, threat model, pre-registration criteria, and aligned Week 3 report (`4_DICTATOR_IS355_Week3.docx`).
- **Phase 1 (Data Audit, Clone Clustering & Splits):** Completed — verified `data/manifest.json`, `data/processed/contracts.parquet` (`|S_full| = |S_code| = 7,446`: 880 Ponzi / 6,566 non-Ponzi), CBOR metadata stripping, `group_exact` & MinHash `group_near` clustering, Dataset 2 overlap decision (`SANITY_CHECK_ONLY`, Risk R6), and 55 frozen split JSONs (`splits/`). Note: `S_code_temporal_holdout.json` (`S3`) was not generated due to missing `block_number` and BigQuery credentials.
- **Phase 2 (X-SPIDE Baseline Reproduction `E0`–`E2`):** Completed — `results/E0_reproduction.csv`, `results/E1_folds.csv`, `results/E1_full_folds.csv`, `results/E2_folds.csv`, frozen `models/baseline_v1/` artifact (`modelVersionHash` recorded in `model_card.json`), and `reports/rq1_reproduction.md`.
- **Phase 3 (Opcode Feature Extraction: `F-BIGRAM`, `F-GSTAT`, `F-GSEM`):** Completed — `src/features/{disasm,bigram,gstat,gsem,pipeline}.py` generated `data/processed/features_{bigram,gstat,gsem}.parquet` (`7,446` contracts, `0` extraction errors, median `16.58 ms`/contract end-to-end) and `results/feature_extraction_cost.csv`, with leak-free in-fold `BigramTopKVectorizer` (`top_k=200`).
- **Phase 4 (Feature Engineering Ablations `E3`–`E4d`, Sensitivity `S1`–`S4`, Conditional `E6`, Stats & XAI):** Completed — 25-fold `5 × 5` grouped CV across `E3`–`E4d` and `S1`/`S2`/`S4` (`S3` `N/A`), Holm-adjusted Nadeau–Bengio & Wilcoxon tests (`E4b vs E1`: `ΔPR-AUC = +0.0227`, 95% CI `[+0.0096, +0.0358]`, `p_Holm = 4.77e-7` Confirmed Improvement; `E4c vs E1`: `95% CI [-0.0037, +0.0152]`), PonziGuard `E6` sanity check (`SANITY_CHECK_ONLY`, Risk R6, `PR-AUC = 0.6535`, `n_test = 107`), global/local SHAP + CFG visualizations (`figures/`, `11` PNGs), `12 FP + 12 FN` error analysis (`results/error_analysis_cases.csv`), and `reports/rq2_results.md`.
- **Phase 5 (Vyper Smart Contracts, Security Review & Deployments):** Completed — compiled Vyper `0.4.3` contracts (`D1`: `contracts/RiskAttestationRegistry.vy`, `D2`: `contracts/variants/D2_EventOnly.vy`, `D3`: `contracts/variants/D3_MerkleBatch.vy`) + artifacts (`contracts/artifacts/`), `docs/contract_spec.md`, `docs/security_review.md`, `reports/contract_coverage.md`, `ape-config.yaml`, `.env.example`, and `scripts/{deploy_contracts,verify_contracts}.py`. All `34` contract tests (`T1`–`T12`, `100%` revert-branch coverage across `D1` 16/16, `D2` 16/16, `D3` 14/14, Hypothesis fuzzing + `set_threshold` deferral regression, and deploy/verify script checks) pass on `PyEVMBackend`. Recorded `3`-auditor / `threshold = 2` deployments in [deployments.json](deployments.json) across `local-evm`, `anvil` (`chain_id = 31337` via local `PyEVMBackend` JSON-RPC bridge because native `anvil.exe` is blocked by Windows Application Control and Docker Desktop is offline), live `sepolia` (`D1`, `D2`, `D3` `"Pass - Verified"` on Etherscan v2, `owner_type = "eoa_demo_limit"`), and live `arbitrum-sepolia` (`D1`, `D3` `"Pass - Verified"` on Etherscan v2 / Arbiscan Sepolia, `owner_type = "eoa_demo_limit"`).
- **Phase 6 (Canonical Evidence Bundle & Streamlit DApp + MetaMask Signer):** Completed — `docs/evidence_schema_v1.md`, `src/evidence/{canonical,storage,inference,chain_client}.py`, deterministic CIDv1 + Git mirror persistence (`evidence/<case_id>.json`, `evidence/cid_index.json`; offline Kubo falls back to `local_content_addressed_unpinned`), 4-page Streamlit DApp (`app/streamlit_app.py`), static `ethers.js v6` + MetaMask signer (`signer/index.html`, `signer/vendor/ethers.umd.min.js`), local PyEVM JSON-RPC bridge (`scripts/local_rpc_server.py`), launcher (`scripts/run_dapp.py`), E2E demo (`scripts/run_phase6_e2e_demo.py`), and `tests/evidence/` (`7` tests covering 3 canonical test vectors, tamper sensitivity, security boundaries, and full Anvil E2E flow). Note: live `sepolia` auditor addresses currently hold `0 ETH`, so live `sepolia` write signing uses the browser MetaMask signer once funded via faucet; read-only verification on `sepolia` is live.
- **Phase 7 (On-Chain Evaluation `E5`, Gas/Latency/Security & Trade-Offs):** Completed — `src/contracts/e5_benchmark.py`, `scripts/run_phase7_e5.py`, `results/E5_gas.csv`, `results/E5_latency.csv`, `results/E5_summary.json`, `figures/gas_vs_batch.png`, `reports/rq3_onchain.md`, and `tests/contracts/test_{e5_benchmark,phase7_outputs}.py`. Measured deterministic Cancun `PyEVMBackend` gas (`D1` finalized case `427,461` **FAIL** vs `250,000` ceiling; `D2` `294,706`, `-31.06%`; `D3` amortized `3,574.53` at $N=100$ and `357.46` at $N=1000$ **PASS** vs `10,000` ceiling), live `sepolia` EIP-8037 & `arbitrum-sepolia` spot-checks, fixed-date Ethereum Mainnet USD cost anchoring (`0.084427 gwei`, `ETH = $1,900.68`, `2026-11-14`), `30` sequential `attest` latency transactions per live testnet (`sepolia` median `1.00` block / `10.357 s` **PASS**; `arbitrum-sepolia` median `1.226 s`), live Sepolia `T1`/`T6`/`T8` revert/verification proofs without mutating main `D1`, and qualitative non-head-to-head comparison against `ProvAuditChain`.
- **Phase 8 (Final Synthesis, Reproducibility & Defense):** Completed (`v1.0-final`) — generated [4_DICTATOR_IS355_Final_Report.docx](4_DICTATOR_IS355_Final_Report.docx)/`.pdf` (18 pages) + [reports/final_report.md](reports/final_report.md), [4_DICTATOR_IS355_Final_Presentation.pptx](4_DICTATOR_IS355_Final_Presentation.pptx)/`.pdf` (14 slides), `1080p` walkthrough video [demo/X-SPIDE-G_demo.mp4](demo/X-SPIDE-G_demo.mp4) (`03:34`), `10` verified DApp screenshots (`demo/screenshots/`), [reports/demo_script.md](reports/demo_script.md), `39`-row traceability matrix ([results/traceability_matrix.csv](results/traceability_matrix.csv) / [reports/traceability_matrix.md](reports/traceability_matrix.md)), all `8` `Phụ lục D` Q&As ([reports/defense_qa.md](reports/defense_qa.md)), pinned [requirements.txt](requirements.txt) + [pyproject.toml](pyproject.toml) + [Makefile](Makefile) + [scripts/run_all.py](scripts/run_all.py), clean-clone `E1` + contract test verification, and Phase 8 deliverable tests.

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

## Reproducibility & Clean-Clone Verification

```powershell
# 1. Install pinned dependencies into a fresh Python 3.12 environment
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e . --no-deps

# 2. Clean-clone bootstrap: download public X-SPIDE datasets, verify manifest, rebuild processed parquet, reproduce E1, and run contract/evidence tests
.\.venv\Scripts\python.exe -m scripts.run_all --mode clean-clone

# 3. Full artifact & offline suite verification (non-destructive: preserves live Sepolia/Arbitrum E5 metrics)
.\.venv\Scripts\python.exe -m scripts.run_all --mode verify

# 4. Run full automated test suite
.\.venv\Scripts\python.exe -m pytest -v

# Individual phase & DApp commands
.\.venv\Scripts\python.exe -m pytest tests/evidence -v
.\.venv\Scripts\python.exe -m pytest tests/contracts --cov=src/contracts --cov-report=term-missing -v
.\.venv\Scripts\python.exe -m scripts.run_phase7_e5 --skip-live
.\.venv\Scripts\python.exe -m scripts.run_phase6_e2e_demo
.\.venv\Scripts\python.exe -m scripts.run_dapp --with-anvil-rpc
.\.venv\Scripts\python.exe -m scripts.deploy_contracts --network local-evm
.\.venv\Scripts\python.exe -m scripts.deploy_contracts --network arbitrum-sepolia
.\.venv\Scripts\python.exe -m scripts.verify_contracts --network arbitrum-sepolia --variants D1 D3
.\.venv\Scripts\python.exe -m src.features.pipeline
```
