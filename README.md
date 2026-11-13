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
- Frozen Baseline Model Card: [models/baseline_v1/model_card.json](models/baseline_v1/model_card.json)

## Repository Status

- **Phase 0 (Design Freeze & Pre-Registration):** Completed — unified design, threat model, pre-registration criteria, and aligned Week 3 report (`4_DICTATOR_IS355_Week3.docx`).
- **Phase 1 (Data Audit, Clone Clustering & Splits):** Completed — verified `data/manifest.json`, `data/processed/contracts.parquet` (`|S_full| = |S_code| = 7,446`: 880 Ponzi / 6,566 non-Ponzi), CBOR metadata stripping, `group_exact` & MinHash `group_near` clustering, Dataset 2 overlap decision (`SANITY_CHECK_ONLY`, Risk R6), and 55 frozen split JSONs (`splits/`). Note: `S_code_temporal_holdout.json` (`S3`) was not generated due to missing `block_number` and BigQuery credentials.
- **Phase 2 (X-SPIDE Baseline Reproduction `E0`–`E2`):** Completed — `results/E0_reproduction.csv`, `results/E1_folds.csv`, `results/E1_full_folds.csv`, `results/E2_folds.csv`, frozen `models/baseline_v1/` artifact (`modelVersionHash` recorded in `model_card.json`), and `reports/rq1_reproduction.md`.
- **Phases 3–8:** Pending execution following exit-criteria gates.

## Verification Commands

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```
