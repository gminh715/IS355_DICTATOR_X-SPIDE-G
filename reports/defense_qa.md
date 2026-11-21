# X-SPIDE-G Defense Q&A Bank & Critic Protocol

**Course:** IS355 – Blockchain Technology (`IS355.R11.CTTT.2`) · Group 4 – DICTATOR  
**Traceability Link:** All quantitative claims below cite deterministic IDs in [`results/traceability_matrix.csv`](../results/traceability_matrix.csv) and [`reports/traceability_matrix.md`](traceability_matrix.md).

---

## Part 1: Mandatory Defense Questions (`Phụ lục D`, Q1–Q8)

### Q1. How is a control-flow / opcode graph (`F-GSEM`) fundamentally different from counting opcode bigrams (`F-BIGRAM`)?
- **Structural Representation Difference:** `F-BIGRAM` counts consecutive linear opcode pairs (`opcode[i] -> opcode[i+1]`) in the deployed bytecode byte array after normalizing `PUSH1..32 -> PUSH`, `DUP1..16 -> DUP`, `SWAP1..16 -> SWAP`, and `LOG0..4 -> LOG`, vectorized in-fold over top-200 bigrams (`src/features/pipeline.py`). By contrast, `F-GSEM` (`15` scalar descriptors) segments bytecode at `JUMP`/`JUMPI`/`JUMPDEST` boundaries into a basic-block Control-Flow Graph (CFG), resolves local stack-pushed targets, runs Tarjan strongly connected component (SCC) analysis to detect actual cyclic execution paths containing `CALL` (`n_loops_with_call`, `has_loop_with_call`) or `SSTORE` (`n_loops_with_sstore`), checks reachability from `CALLVALUE` to `CALL`, measures unresolved indirect jumps (`unresolved_jump_ratio`), and computes opcode transition PageRank weights (`pagerank_CALL`, `pagerank_SSTORE`).
- **Empirical Outcome & Honest Comparison (`RQ2-E3b`, `RQ2-E4b`, `RQ2-E4c`, `STAT-E4b_vs_E1`):** Even though top `F-GSEM` features rank high in TreeExplainer SHAP (`call_block_ratio = 0.2796`, `n_loops_with_call = 0.2205`, `XAI-01`) and `v1.1` adopts exact multi-component McCabe cyclomatic complexity ($M_C = |E_C|-|V_C|+2P \ge 1$), adding `F-GSEM` onto X-SPIDE's 99 baseline yields `+0.0075` PR-AUC (`0.8842` vs `0.8767`, `95% NB CI [-0.0029, +0.0179]`, `p_Holm,NB = 0.6036`, **No Significant Difference**). Conversely, `F-BIGRAM` improves the baseline by **`+0.0227` PR-AUC** (`0.8995`, `95% NB CI [+0.0096, +0.0358]`, `p_Holm,NB = 9.27e-03`, `p_Holm,W = 4.77e-07`, **Confirmed Improvement**; code-only `E3b = 0.9013`).
- **Why?** First, `F-GSEM` compresses the graph into 15 coarse scalar summaries whereas `F-BIGRAM` preserves 200 fine-grained local transitions (`CALLVALUE -> DUP`, `DUP -> REVERT`, `SLOAD -> LT`). Second, Solidity `0.4–0.5` contracts frequently dispatch functions and loop exits using indirect `JUMP`/`JUMPI` targets loaded from memory/stack, leaving a median `19.18%` (and `526/7,446 = 7.06%` contracts exceeding `50%`) unresolved jumps statically (`XAI-01`), which can fragment static loop back-edges.

### Q2. If the smart contract has an `owner` with administrative privileges, what trust problem does the blockchain actually solve?
- **Separation of Governance vs. Direct Verdict Power (`docs/threat_model.md`, `CON-01`):** In all three Vyper `0.4.3` `v1.1` contracts (`D1`, `D2`, `D3`), the `owner` curates the authorized auditor set and quorum threshold $k$ for *future* cases, and is **explicitly prohibited at EVM bytecode level** from calling `register_case`, `attest`, `register_batch`, or modifying/deleting historical verdicts from the `owner` address.
- **On-Chain Proof (`RQ3-05`, `CON-02`):** Attempting `attest` or `register_case` from the `owner` account reverts immediately (`T6`), verified both locally (`46` contract tests, `100%` revert-branch coverage across `D1 20/20`, `D2 20/20`, `D3 18/18`) and on live **Ethereum Sepolia** (all `5/5` `T1`/`T6` exploit transactions returned `status=0`, e.g., owner attest `0x686750805433...`, leaving main `D1` state untouched).
- **Enforced `v1.1` Quorum Isolation (`T13`) + Remaining Operational Scope:** Any off-chain JSON alteration is caught by `verify_evidence(case_id, recomputed_keccak256)` (`T8`), and single-auditor compromise fails $k=2$-of-$3$ approval (`T3`/`T5`). Furthermore, `v1.1` hardens open cases directly in bytecode (`T13`, verified locally and live on Sepolia): (1) every case/batch snapshots `required_threshold` so later `set_threshold(1)` calls cannot weaken open cases; (2) `created_roster_nonce` blocks newly added Sybil auditors (`"Auditor added after case creation"`, live Sepolia tx `0x56d73080cfed...`); (3) simultaneous ties resolve symmetrically to `STATUS_DISPUTED`; and (4) permissionless `revoke_removed_auditor_vote` cleans up stale votes on non-finalized cases (`63,402` gas, live Sepolia tx `0xcdf735c325aa...`) while reverting on finalized verdicts. The remaining residual scope is that testnet deployments use an EOA owner (`owner_type='eoa_demo_limit'`) for *future* cases; production deployments must therefore migrate `owner` to a `2`-of-`3` Gnosis Safe multisig + timelock.

### Q3. If F1 only increases by 0.01, how should we conclude scientifically?
- **Pre-Registered Decision Rule (`docs/preregistration.md`):** Prior to Phase 4 execution, our primary evaluation endpoint was frozen as **PR-AUC** under 5×5 clone-grouped cross-validation, requiring ALL three conditions for **`Confirmed Improvement`**:
  1. Mean paired gain passes Minimum Detectable Effect: $\Delta\text{PR-AUC} \ge +0.020$,
  2. Two-sided `95%` Nadeau–Bengio corrected CI ($df = 24$) excludes zero cleanly on the positive side, and
  3. Multiplicity-adjusted Holm–Bonferroni $p_\text{Holm,NB} < 0.05$ across the `8`-test family.
- **Concrete Conclusion:** A tiny `~0.01` gain on F1 (which is threshold-dependent on $\tau^*$) or $\Delta\text{PR-AUC} < 0.02$ **cannot** be claimed as a confirmed practical improvement. In fact, our own results follow this strict rule verbatim: `E4 vs E1` (`+0.0037` PR-AUC, `+0.0022` F1) and `E4c vs E1` (`+0.0075` PR-AUC, `+0.0026` F1) are reported as **No Significant Difference** (`STAT-E4_vs_E1`, `STAT-E4c_vs_E1`)—no post-hoc threshold moving was permitted.

### Q4. Where is bytecode obtained for self-destructed contracts, and does missing/dropped data create selection bias?
- **Source & Complete Coverage (`DATA-01`):** For X-SPIDE `[1, 9]`, all `7,446` unique contracts (`880` Ponzi, `6,566` non-Ponzi) already contain runtime deployed bytecode hex inside `DS_deployed_bytecode.csv` and `DS_full_bytecode.csv` captured at X-SPIDE's snapshot time—yielding `100.0%` non-empty bytecode coverage (`|S_code| = |S_full| = 7,446`, zero `0x` or missing rows). Thus we do **not** drop historical `SELFDESTRUCT` contracts from the `7,446`-contract X-SPIDE benchmark.
- **Measured Selection Bias (`Risk R2`, `reports/data_audit_summary.json`):** Comparing our `7,446` kept contracts against the `516` rows excluded from X-SPIDE's wider `bytecode_opcode_8k.csv` (`7,962` rows) reveals statistically significant distribution shifts: e.g., `tx_out` median `0.0` (kept) vs `1.0` (excluded, `KS = 0.2467`, `p = 2.50e-26`), `lifetime` median `15.0` vs `2.0` days (`KS = 0.1384`, `p = 1.58e-08`), and `total_tx` median `5.0` vs `3.0` (`KS = 0.2072`, `p = 1.71e-18`). We explicitly report this selection boundary in Section 4 and Section 7.2 rather than assuming the `7,446`-contract corpus represents all historical Ethereum deployments.

### Q5. How do auditors sign on-chain transactions, and where are private keys stored?
- **Zero Server-Side Live Keys (`app/streamlit_app.py`, `signer/index.html`):** On Ethereum Sepolia (`11155111`) and Arbitrum Sepolia (`421614`), the Streamlit DApp acts purely as an untrusted UI/RPC reader with **zero private keys stored on the server, in session memory, or in code**.
- **Client-Side MetaMask Flow:** Page 3 passes unsigned calldata parameters (`contract`, `chain_id`, `case_id`, `evidence_hash`, `ipfs_uri`, `verdict`) via URL query parameters to the standalone static `signer/index.html` running `ethers.js v6` (`BrowserProvider`). The auditor reviews the exact `case_id` and `evidence_hash` in their own **MetaMask** browser wallet extension and signs the transaction directly on the client device.
- **Local Dev Key Gate:** Pre-funded test accounts exist exclusively for offline/local E2E verification (`scripts/run_phase6_e2e_demo.py`, `scripts/run_dapp.py --with-anvil-rpc`) and are strictly gated behind `eth_chainId == 31337` (Anvil PyEVM).

### Q6. If the off-chain JSON evidence file is lost, what value does an on-chain hash still provide?
- **Dual Content-Addressed Persistence:** Storing a `32`-byte `keccak256` hash on-chain guarantees **integrity, non-repudiation, and tamper detection**, NOT raw storage availability on EVM itself. To prevent loss, X-SPIDE-G emits `evidence_uri` (`ipfs://<cidv1>`) inside the immutable `CaseRegistered` event AND mirrors every generated evidence file canonically inside `evidence/<case_id>.json` under Git version control (`EVD-01`).
- **Even Under Temporary Off-Chain Loss:**
  1. Anyone recovering a copy from IPFS pinning nodes, archival nodes, or Git mirrors can recompute `keccak256(canonical_bytes)` and prove byte-for-byte authenticity via `verify_evidence(case_id, digest) == True` (`T8`).
  2. The $k$-of-$n$ quorum outcome (`Approved`/`Rejected`), timestamps, contract `code_hash` provenance, and participating auditor addresses remain permanently auditable on-chain (`CON-01`, `RQ3-05`).
  3. No party can retroactively fabricate or substitute an alternative JSON report without triggering a hash mismatch (`False`).

### Q7. Could the ML metrics still be inflated by smart-contract clones?
- **Direct Measurement & Removal (`DATA-03`, `DATA-04`, `RQ1-S0`, `RQ1-03`, `SENS-S1`):** Yes—random splits severely overstate performance because `25.57%` (`225/880`) of X-SPIDE Ponzi contracts share **exact** CBOR-stripped bytecodes and **`59.09%` (`520/880`)** fall into MinHash near-clone clusters ($t=0.90$, 5-gram normalized opcodes).
- **Controlled 3-Step Causal Decomposition That Eliminated Leakage:**
  1. Holding the 5×5 nested Optuna + $\tau^*$ protocol 100% constant (`RQ1-S0`), moving from random splits (`E1_S0_random_5x5 = 0.9251 ± 0.0110`) to exact-clone grouping (`E1_S1_group_exact = 0.9051`) removes **`-0.0201` PR-AUC** (`-0.0300` F1) of pure exact-clone leakage, and moving further to MinHash near-clone grouping (`E1 = 0.8767`) removes another **`-0.0283` PR-AUC** (`-0.0261` F1; `E4c_S1`: `0.9104` vs `0.8842`, `+0.0261`, `SENS-S1`)—totaling **`-0.0484` PR-AUC / `-0.0561` F1** of pure clone leakage.
  2. Upgrading from paper-style random 5-fold (`E0 = 0.9149`) to `E1_S0` adds `+0.0102` PR-AUC, explaining why the combined `E0` → `E1` drop is `-0.0382` (`RQ1-03`).
  3. All feature selections (`RFECV`, `BigramTopKVectorizer`) and Optuna hyperparameter searches run **strictly nested inside each training fold**, while `E6` on `107` zero-overlap PonziGuard bytecodes (`PR-AUC = 0.6169` with `0` account features and `n=10` positives) tests out-of-corpus generalization transparently.

### Q8. Why didn't you deploy and measure gas directly on Ethereum Mainnet?
- **Cost, Ethics & Equivalent EVM Determinism (`RQ3-01`..`RQ3-03`):**
  1. **Governance Ethics:** Publishing unvetted "Ponzi" labels against live Ethereum mainnet addresses without formal legal/security sign-off creates defamation and market manipulation liability.
  2. **Budget & Identical Opcode Semantics:** EVM execution gas depends deterministically on opcode/storage rules for a target fork, not network identity. Using **PyEVM Cancun** gives exact, noise-free `v1.1` gas accounting (`D1 = 484,818`, `D2 = 352,063`, `D3 N=100 = 4,148.10/case`, `D3 N=1000 = 414.82/case`), which we convert to USD using a real frozen mainnet snapshot (`0.971057 gwei`, `ETH = $1,704.05` -> `D1 = $0.802242`, `D3 N=100 = $0.006864`) plus a `30 gwei` congestion stress scenario (`$24.78` vs `$0.2121`).
  3. **Live Testnet Validation:** We verified actual network propagation, `etherscan.io` v2 source verification (`5/5` `v1.1` contracts), `n=30` confirmation latency (`Sepolia = 10.560 s / 1.00 block`; `Arbitrum Sepolia = 1.212 s`), and `5/5` `T1`/`T6` reverts + `T8` + `T13` Sybil/revocation proofs on public testnets (`Sepolia` & `Arbitrum Sepolia`), while explicitly flagging Sepolia's Glamsterdam/EIP-8037 state-creation repricing and Arbitrum Sepolia's `gasUsedForL1 = 0x0`.

---

## Part 2: Extended Committee Probes (Pre-Empting Hard Follow-Ups)

- **Probe A — Why is `D1` flagged `FAIL (> 250,000)`? Didn't the project fail RQ3?**  
  No—pre-registering pass/fail criteria meant testing storage designs honestly. `D1` fails the `250k` per-case storage budget at `484,818` Cancun gas (`v1.1`, including `+57,357` gas for `T13` threshold/roster-nonce hardening) because a 12-field `Case` struct plus two cold `Attestation` writes trigger three separate `SSTORE` allocations (`RQ3-01`). `D2` (`EventOnly`) saves `27.38%` (`352,063` gas, `RQ3-02`), and **`D3_MerkleBatch` achieves `PASS`** (`4,148.10` gas/case at `N=100` and `414.82` at `N=1,000`, `RQ3-03`) alongside `1.00`-block live Sepolia receipt confirmation on `D1.attest` (`PASS <= 2` blocks, `RQ3-04`).
- **Probe B — Why do `E4 vs E1` and `E4c vs E1` show `p_Holm,W < 0.05` on Wilcoxon yet say `No Significant Difference`?**  
  Naive Wilcoxon treats the 25 repeated 5×5 CV folds as independent (`p_Holm,W = 0.0138` and `0.0025`), whereas our primary inference applies Holm–Bonferroni to the **Nadeau–Bengio corrected paired $t$-tests** ($df=24$) accounting for training-fold overlap (`NB p = 0.246`, `p_Holm,NB = 0.737` for `E4`; `NB p = 0.151`, `p_Holm,NB = 0.604` for `E4c`, both with 95% CIs crossing zero) AND requires $\Delta\text{PR-AUC} \ge 0.02$. Both criteria block false discovery cleanly.
- **Probe C — Why can't we run `S3` temporal holdout?**  
  `block_number` is `100% <NA>` across X-SPIDE CSVs, and BigQuery RPC backfill was unavailable offline (`SENS-S2-S4`). Rather than inventing synthetic timestamps, `S3` is transparently logged as unfeasible and scheduled for future work.
- **Probe D — Why does `E3b` (`F-BIGRAM` code-only = `0.9013`) match or edge `E4b` (`99 + F-BIGRAM` = `0.8995`)?**  
  In `E3b` vs `E4b` (`0.9013` vs `0.8995`, $\Delta = -0.0018$), the `23` account statistics + `76` unigram opcodes partially overlap with normalized bigrams while increasing Optuna feature dimensionality from `200` to `299`; importantly, code-only `F-BIGRAM` remains deployable on **zero-tx day-0 newly deployed contracts** where transaction features are zero!

---

## Part 3: Mock-Defense Interrogation & Readiness Checklist

*(Status disclosure: Technical verification items marked `[Automated Pass]` were executed programmatically in our workspace; presenter timing and oral Q&A rehearsal should be practiced live by the 5 team members prior to the defense slot.)*

- [x] **[Verified]** Traceability check: all numbers cited in report, slides, and Q&A match [`results/traceability_matrix.csv`](../results/traceability_matrix.csv) (`40` IDs).
- [x] **[Verified]** Pre-registered null results (`F-GSEM E4c/E4d`, `S3 N/A`, `E6 Risk R6`, `D1 > 250k`, `eoa_demo_limit`, `gasUsedForL1=0x0`, Sepolia `EIP-8037`) presented openly with zero threshold tampering.
- [x] **[Verified]** Live DApp walkthrough (`xspide_00439`), `10` screenshots, and `demo/X-SPIDE-G_demo.mp4` (`3–5 min` backup recording) verified ready.
- [x] **[Verified]** Offline/clean-clone verification (`scripts/run_all.py`) + contract & Phase 8 automated test suite verified passing.
- [ ] **[Team Live Action]** Run a 15-minute live dry-run with all 5 DICTATOR members assigning slide ranges (`Minh`: Intro/Contracts/E5, `Vinh`: RQ1 `E0–E2`, `Sơn`: Feature Engineering `F-BIGRAM/GSEM`, `Nhân`: Stats/S1–S4/SHAP, `Quân`: Live DApp + Tamper Demo + Q&A).
