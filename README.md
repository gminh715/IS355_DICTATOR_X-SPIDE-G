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

## Repository Status

- **Phase 0 (Design Freeze & Pre-Registration):** Completed — unified design, threat model, pre-registration criteria, and aligned Week 3 report (`4_DICTATOR_IS355_Week3.docx`).
- **Phases 1–8:** Pending execution following exit-criteria gates.
