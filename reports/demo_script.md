# X-SPIDE-G Live Demo Runbook & Recording Script (3–5 Minutes)

**Presenter:** Group 4 – DICTATOR (`IS355.R11.CTTT.2`)  
**Target Time:** `3 min 30 sec` (`210 s`) live or backup recording (`demo/X-SPIDE-G_demo.mp4`)  
**Primary Demo Subject:** Holdout contract `xspide_00439` (`0x2c2e3baa2191cf325a28a01ff42340f2ae677572`)  
**Expected Case ID:** `0x5b7624e00332bf67a30b0f9957113f45481522a21707a396f0d60ace93bb842a`

---

## 0. Pre-Flight Checklist (5 Minutes Before Defense)

1. Confirm clean Python environment (`Python 3.12.13`) and verified artifacts exist:
   ```powershell
   .\.venv\Scripts\python.exe -m scripts.run_phase6_e2e_demo
   ```
   Confirm terminal JSON displays `"sepolia_read_check": {"connected": true}`, `Approved`, `verify_exact: true`, and `verify_tampered_1byte: false`.
2. Start the integrated local DApp + PyEVM Anvil RPC + standalone HTTP MetaMask signer:
   ```powershell
   .\.venv\Scripts\python.exe -m scripts.run_dapp --with-anvil-rpc
   ```
   - Streamlit DApp opens at `http://localhost:8501`
   - Standalone `ethers.js v6` signer serves at `http://127.0.0.1:8502/index.html`
   - Local Anvil PyEVM RPC runs on `http://127.0.0.1:8545` (`chainId = 31337`, `k = 2` of `n = 3` auditors pre-configured)
3. Keep `demo/X-SPIDE-G_demo.mp4` (`214 s`, 1080p) and `demo/screenshots/` (`10` PNGs) ready as immediate fallback if live RPC or browser session slows.

---

## 1. Timed Presentation Script (`210 Seconds` Total)

| Time Window | Component / Screen | Actions & Talking Points | Observed Ground-Truth Output |
|---|---|---|---|
| `0:00 – 0:30` (`30 s`) | **Terminal CLI Check** | Run `run_phase6_e2e_demo` (or show live terminal log). Explain trust split: ML/DApp server holds zero live testnet keys; only Anvil `chainId == 31337` permits dev signers. | `sepolia.connected = true`; D1 quorum `2/2` verified. |
| `0:30 – 1:10` (`40 s`) | **Page 1: Analyze Contract** (`01_page1_input.png` – `03_page1_cfg_detail.png`) | Select test-fold contract `xspide_00439` (`0x2c2e...7572`). Point out frozen `baseline_v1` LightGBM score `0.998390 >= tau* = 0.256746` (`PONZI`), inspect top SHAP contributors (`SLOAD +1.7456`, `CALLDATALOAD +1.0512`, `CALL +0.8412`, `SSTORE +0.8082`), and expand the static Basic-Block CFG showing call-in-loop structure (`16.584 ms` median extraction). | Risk Score `0.998390` (`PONZI`); deterministic `shap_digest = 0xac0b93b5...`. |
| `1:10 – 1:45` (`35 s`) | **Page 2: Canonical Evidence & IPFS** (`04_page2_evidence_cid.png`) | Click canonical packaging. Highlight sorted UTF-8 JSON, fixed `6`-decimal numeric strings (`"0.998390"`), computed `case_id`, `evidence_hash`, raw-block IPFS `CIDv1` (`bafk...`), and automatic Git mirror write to `evidence/<case_id>.json`. | `case_id = 0x5b7624e00332bf67...`; mirror file saved atomically. |
| `1:45 – 2:30` (`45 s`) | **Page 3: Multi-Auditor Quorum & Signer** (`05_page3_sign_tx.png`, `06_page3_quorum_approved.png`, `10_signer_metamask.png`) | (a) As **Auditor #1**, sign `register_case` on Anvil (`tx = 0xac93319f...`, `129,311` gas) — emphasize contract enters `Pending (1/2)`, NOT finalized. (b) Switch to **Auditor #2** and sign `attest(..., Approve)` -> status transitions to `Approved (2/2)`. (c) Open **Client MetaMask Signer** tab (`127.0.0.1:8502`) to show URL pre-fill on Sepolia/Arbitrum without server keys. | `approve_count = 2`, `status = 1 ("Approved")`. |
| `2:30 – 3:15` (`45 s`) | **Page 4: Public Verify & 1-Byte Tamper Test** (`07_page4_quorum_status.png` – `09_page4_tampered_reject.png`) | Query `case_id` as a public verifier: show `Approve 2 / 2` and event log (`CaseRegistered` + `Attested`). Verify unaltered JSON (hash + `subject`, `chain_id`, `model_version_hash`, `case_id` identity match) -> green **`✅ VERIFIED`**. Then click **Simulate 1-Byte Tamper** (flipping 1 digit inside JSON): show recomputed `keccak256` (`0x342fecac...`) fails `verify_evidence(...) == False` -> red **`❌ TAMPERED / MISMATCH`**. | Clean match `True` -> 1-byte mutation `False`. |
| `3:15 – 3:30` (`15 s`) | **Wrap-Up** | Connect live DApp back to `E5` research findings: single-case `D1` uses `427,461` Cancun gas (`FAIL > 250k`), while `D3` Merkle batching drops cost to `3,574.53 gas/case` (`PASS <= 10k`), and `D1.attest` confirms receipts in `1.00 block` (`10.357 s`) on Sepolia and `1.226 s` on Arbitrum Sepolia. | Transition cleanly to Committee Q&A. |

---

## 2. Troubleshooting & Contingency Plan

| Failure Mode During Live Defense | Immediate Fallback Action |
|---|---|
| Local port `8501`/`8502`/`8545` busy | Terminate stale Python process (`Stop-Process`) or launch `run_dapp.py` with custom ports; immediately switch to **pre-rendered screenshots** in `demo/screenshots/` (`01`–`10`). |
| Live Sepolia RPC rate-limit during read check | Toggle DApp network dropdown to **Anvil Local (`31337`)** for live signing + tamper test, then display verified Sepolia tx hashes from `deployments.json` & `results/E5_summary.json`. |
| Screen share lag / audio stutter | Play **`demo/X-SPIDE-G_demo.mp4`** (`214 s` self-contained 1080p MP4 with step badges and narration captions). |
