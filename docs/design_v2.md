# X-SPIDE-G: Unified System & Experimental Design (v2.0)

**Project:** X-SPIDE-G – Graph-Enhanced Explainable Ponzi Detection and On-Chain Risk Attestation for Ethereum Smart Contracts  
**Course:** IS355 – Blockchain Technology · Group 4 – DICTATOR (UIT – VNU-HCM)  
**Version:** v2.0 (Phase 0 Baseline Specification, 2026-11-13)  
**Source Plan:** [KE_HOACH_THUC_HIEN_X-SPIDE-G.md](../KE_HOACH_THUC_HIEN_X-SPIDE-G.md)

> **Core Scientific & Engineering Principles**
> 1. **Empirical integrity:** No experimental result, metric improvement, or on-chain receipt is reported without an executed script, fixed seed, and verifiable commit/transaction hash.
> 2. **Negative results are valid:** If opcode bigrams, transition statistics, or CFG semantic features fail to surpass the pre-registered threshold over the 99-feature baseline, that negative finding is reported transparently alongside clone-leakage and error analyses.
> 3. **Exit-criteria gating:** Dependent phases begin only after upstream exit criteria are verified.

---

## 1. Research Questions & Research Gaps

### 1.1. Research Questions
- **RQ1 (Reproduction & Clone Leakage):** Can the published X-SPIDE LightGBM baseline [1] be reproduced (`E0`), and how much does predictive performance shift when moving from random stratified splitting (`E0`) to CBOR-stripped clone-grouped cross-validation (`E1`, `E1-full`)?
- **RQ2 (Structural Opcode Features):** Compared with the 99-feature X-SPIDE baseline (`E1`), does adding (a) opcode bigrams (`F-BIGRAM` in `E4b`), (b) length-normalized transition-graph statistics (`F-GSTAT` in `E4`), or (c) lightweight basic-block CFG semantic features (`F-GSEM` in `E4c`, `E4d`) achieve a statistically significant improvement of **$\Delta\text{PR-AUC} \ge 0.02$** across $5 \times 5$ repeated clone-grouped CV? What per-contract extraction latency does each feature family incur?
- **RQ3 (On-Chain Multi-Auditor Attestation):** Does the $k$-of-$n$ Vyper `RiskAttestationRegistry` enforce all specified role-separation and append-only immutability invariants (`T1`–`T12`), and among three storage designs (`D1` Full Storage, `D2` Event-Only, `D3` Merkle Batch), which satisfies pre-registered gas and confirmation-latency thresholds on Ethereum Sepolia and an L2 testnet (`E5`)?

### 1.2. Gaps & Targeted Improvements
- **G1 (ML Representation & Leakage):** Prior static ML models (`Chen et al.` [5], `X-SPIDE` [1]) rely on unordered opcode frequencies; opcode $n$-gram detectors (`Fan et al.` [7]) capture local consecutive order without modeling control-flow loops or reachability; dynamic/symbolic detectors (`PonziGuard` [2], [3], `SADPonzi` [8]) capture execution semantics at high computational cost; and cloned Ponzi families (`Bartoletti et al.` [6]) inflate random splits while `SELFDESTRUCT` contracts cause missing-bytecode selection bias.  
  → **I1:** Benchmark lightweight basic-block CFG semantic descriptors (`F-GSEM`) explicitly against both `E1` and an explicit `F-BIGRAM` baseline (`E3b`/`E4b`) under CBOR-stripped MinHash `group_near` $5 \times 5$ grouped CV, paired statistical tests, bytecode recovery, and KS bias auditing.
- **G2 (Decentralized Audit Provenance & Key Safety):** `X-SPIDE` [1] provides no on-chain audit ledger; `ProvAuditChain` [4] targets single-pipeline L2 provenance without Ponzi $k$-of-$n$ multi-auditor quorum consensus or storage-vs-Merkle trade-offs; and centralized admin/single-auditor contracts with server-held signing keys fail to justify blockchain over a signed database.  
  → **I2:** Specify an explicit threat model ([threat_model.md](threat_model.md)), implement a $k$-of-$n$ (default 2-of-3) Vyper `RiskAttestationRegistry` with zero owner override, bind canonical JSON evidence via `evidenceURI` (IPFS + Git mirror), move transaction signing to a static client-side `ethers.js` + MetaMask page, and evaluate `D1`–`D3` across Anvil, Ethereum Sepolia, and an L2 testnet.

---

## 2. End-to-End Architecture

Execution proceeds along two parallel tracks after Phase 0:
- **Track A (ML & Data):** Phase 1 → Phase 2 → Phase 3 → Phase 4
- **Track B (Blockchain & DApp):** Phase 5 → Phase 6 → Phase 7
- **Convergence:** Phase 6 integrates the frozen Phase 2/4 model and canonical evidence pipeline with the Phase 5 contract; Phase 8 consolidates final deliverables.

```
[1. Data Audit & Bytecode Recovery] (X-SPIDE [9], BigQuery/RPC/Archive, PonziGuard [10], Unica [11])
         │  CBOR Strip + group_exact / MinHash group_near (5x5 StratifiedGroupKFold)
         ▼
[2. Baseline & Structural Features] (E0–E2 LightGBM; disasm.py + F-BIGRAM + F-GSTAT + F-GSEM CFG)
         │  In-fold pipelines, identical nested-CV tuning budget, per-contract runtime
         ▼
[3. Controlled Eval, Stats & XAI]   (E1–E4d, S1–S4, cond. E6, Nadeau–Bengio/Wilcoxon/Holm, SHAP)
         │  Model artifact + modelVersionHash + validation-tuned threshold
         ▼
[4. Streamlit DApp & Evidence]      (4 pages: Analysis, Evidence JSON + IPFS/Git, Client Signer, Verifier)
         │  Static ethers.js v6 + MetaMask browser signing (NO server private keys)
         ▼
[5. Vyper k-of-n Registry & E5]     (D1 Full Storage / D2 Event-Only / D3 Merkle Batch on Anvil, Sepolia, L2)
```

---

## 3. Data & Anti-Leakage Design (Phase 1)

### 3.1. Datasets
1. **Dataset 1 – X-SPIDE [1], [9]:** Official release containing 7,446 labeled contracts (`880` Ponzi / `6,566` non-Ponzi, 99 features; paper deployed-opcode subset `6,621`: `669` / `5,952`).
2. **Dataset 2 – PonziGuard / XBlock [2], [10]:** `Ponzi.zip` and `non-Ponzi.zip` (published `6,498` contracts: `314` Ponzi / `6,184` non-Ponzi, blocks `0–7,500,000`). Used for external code-only transfer (`E6`) **only if** $\ge 30$ non-overlapping Ponzi contracts remain after deduplication against X-SPIDE by `address`, `code_hash`, and `group_near`; otherwise downgraded to a qualitative sanity check.
3. **Auxiliary Positive Reference – Blockchain@Unica [6], [11]:** `ponzi-addresses.csv` (positive-only historical inventory); used exclusively for overlap verification and positive sanity checks, never binary PR-AUC/F1 benchmarking.

Raw datasets with unclear redistribution licenses are **not committed to Git**; only `data/manifest.json` (URLs, commit hashes, SHA-256 digests, acquisition dates, license notes) and download/audit scripts are versioned.

### 3.2. Bytecode Recovery & Bias Audit
Missing deployed bytecode is resolved strictly in priority order and tagged in `bytecode_source`:
1. `xspide_repo`: Bytecode present in official X-SPIDE CSV/archives [9].
2. `rpc_latest`: `eth_getCode(address, "latest")` via public RPC (`0x` indicates likely `SELFDESTRUCT`).
3. `bigquery_or_archive`: Google BigQuery `bigquery-public-data.crypto_ethereum.contracts` (`bytecode`, `block_number`, `block_timestamp`) or archive-node `eth_getCode` at pre-destruction block.
4. `missing`: Unrecoverable; **never** imputed or synthesized.

Outputs in `reports/data_audit.md` must report per-class coverage (`recovered / total` for Ponzi and non-Ponzi across sources), 3–5 real contract rows per class, and Kolmogorov–Smirnov (KS) / median comparisons of transaction attributes between `S_code` and `missing` rows to expose selection bias.

### 3.3. CBOR Metadata Stripping & Two-Level Clone Grouping
1. **CBOR Metadata Stripping [13]:** Inspect the final 2 bytes as big-endian payload length $L$; attempt strict CBOR decoding of the trailing $L$ bytes (preceding the 2-byte length marker). Strip only when valid Solidity/Vyper CBOR metadata decodes cleanly; handle pre-Solidity `0.4.7` contracts lacking metadata safely. Record `metadata_stripped` $\in \{\text{true}, \text{false}, \text{none}\}$.
2. **Exact Clone ID (`group_exact`):** `code_hash = keccak256(runtime_bytecode_stripped)`.
3. **Near-Duplicate Family (`group_near`):** Disassemble and normalize opcodes, extract 5-gram opcode shingles, compute MinHash signatures via `datasketch` (`128` permutations), query LSH for pairs with Jaccard $\ge 0.90$, and merge connected components via union-find. Report cluster sizes, mixed-label clusters (label conflict audit), and fraction of Ponzi rows inside clusters of size $> 1$.

### 3.4. Frozen Splits
- **`S_full`:** All audited X-SPIDE contracts (`E0`, `E1-full`).
- **`S_code`:** Subset with valid recovered runtime bytecode (`E1`–`E4d`, primary comparison set).
- **Primary CV Splits:** `StratifiedGroupKFold(n_splits=5)` [12] with `groups = group_near`, repeated across 5 fixed seeds (`[42, 43, 44, 45, 46]`) yielding **25 paired folds**, frozen under `splits/S_code_group_near_seed{s}_fold{k}.json`. Unit tests verify zero `group_near` overlap between train and test in every fold.
- **Sensitivity Splits:** `group_exact` splits (`S1`) and chronological deployment holdout (`20%` latest `block_number` as test, `S3`) when `block_number` coverage is reliable.

---

## 4. Disassembler & Structural Feature Specifications (Phase 3)

### 4.1. Verified EVM Disassembler (`src/features/disasm.py`)
- Complete EVM opcode table including **`PUSH0` (`0x5F`)** (EIP-3855).
- `PUSH1`–`PUSH32` (`0x60`–`0x7F`): advance instruction pointer over `1..32` immediate bytes; log truncated immediates at EOF rather than silently misaligning opcodes.
- Unrecognized bytes: emit `INVALID_xx` and increment invalid-opcode counter.
- Unit tests cover 5 hand-crafted bytecodes, 3 real mainnet contracts verified against Etherscan disassembly, CBOR vs non-CBOR bytecodes, and truncated `PUSH32`.

### 4.2. Mnemonic Normalization
Default normalized alphabet (configurable raw flag for sensitivity analysis `S4`):
- `PUSH1`..`PUSH32` → `PUSH` (keep `PUSH0` distinct)
- `DUP1`..`DUP16` → `DUP`
- `SWAP1`..`SWAP16` → `SWAP`
- `LOG0`..`LOG4` → `LOG`

### 4.3. Feature Groups
1. **`F-BIGRAM` (Mandatory Sequence Baseline):** Relative frequencies of consecutive normalized opcode pairs `(op_i, op_{i+1})` divided by total transitions. Select top-$k = 200$ bigrams by document frequency **strictly inside each training fold** via an `sklearn`-compatible transformer to prevent test leakage.
2. **`F-GSTAT` (Transition-Graph Statistics):** Directed weighted graph $G_{\text{trans}} = (V, E, w)$ on normalized mnemonics (`networkx.DiGraph`). Extract `|V|`, `|E|`, self-loop-aware density $|E| / |V|^2$, mean/max weighted in-degree and out-degree, total transition count, Shannon entropy of transition weights, self-loop weight ratio, and length-normalized variants (`|V|/L`, `|E|/L`, degree stats `/L`).
3. **`F-GSEM` (Basic-Block CFG Semantic Descriptors — Primary Novelty):**
   - **Basic-block segmentation:** Start a new block at every `JUMPDEST` (and entry offset `0`); terminate blocks immediately after `JUMP`, `JUMPI`, `STOP`, `RETURN`, `REVERT`, `INVALID`, `SELFDESTRUCT`.
   - **CFG edge construction:** Add fall-through edges (after `JUMPI` and between adjacent non-terminating blocks) plus static jump edges wherever pattern `PUSHn <dest>; JUMP/JUMPI` targets a valid `JUMPDEST` offset. Record `unresolved_jump_ratio` (dynamic jumps, typically Solidity internal return addresses) explicitly as a static-analysis limitation metric.
   - **Features:** `n_blocks`, `n_cfg_edges`, `cyclomatic` ($E - N + 2$, which becomes negative when unresolved indirect jumps leave $P > 1$ disconnected components), `n_scc_cycles` (SCCs with size $> 1$ or self-loop), `n_loops_with_call`, `has_loop_with_call`, `n_loops_with_sstore`, `path_callvalue_to_call` (CFG reachability from any block containing `CALLVALUE` to any block containing `CALL`), `n_blocks_with_call`, `call_block_ratio`, `pagerank_CALL`, `pagerank_SSTORE` (computed on the transition graph), `has_selfdestruct`, `selfdestruct_reachable`, and `unresolved_jump_ratio`.
   - **Extraction cost:** Record median and p95 per-contract extraction time (ms) per module (`disasm`, `bigram`, `gstat`, `gsem`) alongside hardware CPU/RAM specs in `results/feature_extraction_cost.csv`.

---

## 5. Unified Experiment Matrix (Phases 2, 4, 7)

All documents use the following canonical definitions (detailed acceptance & statistical rules in [preregistration.md](preregistration.md)):

| ID | Purpose | Dataset | Features | Split / Setup | Primary Metric | RQ |
|---|---|---|---|---|---|---|
| `E0` | Paper reproduction | `S_full` | 47 (paper set) | Paper random split & grid | P/R/F1/ROC-AUC vs [1] | RQ1 |
| `E1-full` | Reference grouped baseline | `S_full` | 99 | `group_near` 5×5 CV | PR-AUC | RQ1 |
| **`E1`** | **Primary baseline** | `S_code` | 99 | `group_near` 5×5 CV | PR-AUC | RQ1/2 |
| `E2` | In-fold feature selection | `S_code` | RFE inside train fold | `group_near` 5×5 CV | $\Delta\text{PR-AUC}$ vs `E1` | RQ1 |
| `E3` | Transition stats only | `S_code` | `F-GSTAT` | `group_near` 5×5 CV | PR-AUC | RQ2 |
| `E3b` | Bigram baseline only | `S_code` | `F-BIGRAM` | `group_near` 5×5 CV | PR-AUC | RQ2 |
| `E3c` | CFG semantic only | `S_code` | `F-GSEM` | `group_near` 5×5 CV | PR-AUC | RQ2 |
| `E4` | Baseline + `F-GSTAT` | `S_code` | `99 + F-GSTAT` | `group_near` 5×5 CV | $\Delta\text{PR-AUC}$ vs `E1` | RQ2 |
| `E4b` | Baseline + `F-BIGRAM` | `S_code` | `99 + F-BIGRAM` | `group_near` 5×5 CV | $\Delta\text{PR-AUC}$ vs `E1` | RQ2 |
| `E4c` | Baseline + `F-GSEM` | `S_code` | `99 + F-GSEM` | `group_near` 5×5 CV | $\Delta\text{PR-AUC}$ vs `E1` & `E4b` | RQ2 |
| `E4d` | Combined structural test | `S_code` | `99 + F-BIGRAM + F-GSEM` | `group_near` 5×5 CV | $\Delta\text{PR-AUC}$ vs `E4b` | RQ2 |
| `S1`–`S4` | Sensitivity analyses | `S_code` | `E1`, `E4c` | `group_exact`, ±CBOR, time holdout, ±norm | $\Delta\text{PR-AUC}$, $\Delta\text{F1}$ | RQ2 |
| `E5` | On-chain evaluation | — | — | `D1`/`D2`/`D3` × Anvil/Sepolia/L2 | Gas, USD, latency, T1–T12 | RQ3 |
| `E6` | External transfer (cond.) | Dataset 2 deduped | Code-only (`op_freq + BIGRAM + GSEM`) | Train `S_code`, test Dataset 2 | PR-AUC + 1,000-bootstrap CI | RQ2 |

---

## 6. Smart Contract Specification Overview (Phase 0.6 / Phase 5)

Full ABI/deployment specification will live in `docs/contract_spec.md` (Phase 5). The frozen architectural contract specification agreed in Phase 0 is:

### 6.1. Governance & Access Separation
- **Language & Toolchain:** Vyper `0.4.x`, Ape Framework (`ape-foundry` / Anvil), `pytest`.
- **Quorum Model:** Multi-auditor **$k$-of-$n$** attestation, default **$k = 2$** on **$n = 3$** auditors, invariant $1 \le k \le \text{auditor\_count}$.
- **Strict Role Separation:** `owner != auditor` enforced on `add_auditor`. On Ethereum Sepolia, `owner` should be a Safe multisig (if an EOA is used during demo constraints, this residual key limitation must be explicitly documented).
- **Zero Owner Override:** The contract exposes **no function** for `owner` (or anyone else) to edit, delete, or revoke registered cases, `evidence_hash`, `model_version_hash`, or existing attestations.

### 6.2. State & Encodings (`D1` Full Storage Baseline)
- `owner: address`
- `is_auditor: HashMap[address, bool]`
- `auditor_count: uint256`
- `threshold: uint256`
- `cases: HashMap[bytes32, Case]` where `Case` holds `{subject: address, subject_chain_id: uint256, evidence_hash: bytes32, model_version_hash: bytes32, registrant: address, created_at: uint256, approve_count: uint256, reject_count: uint256, review_count: uint256, status: uint8}`
- `attestations: HashMap[bytes32, HashMap[address, Attestation]]` where `Attestation` holds `{decision: uint8, revision: uint256, timestamp: uint256}`
- **Decision Enum (`uint8`):** `0 = Unset`, `1 = Approve`, `2 = Reject`, `3 = NeedsReview`.
- **Status Enum (`uint8`, recomputed on every attestation):**
  - `1 = Approved` if `approve_count >= threshold`
  - `2 = Rejected` if `reject_count >= threshold`
  - `3 = Disputed` if `approve_count >= 1` and `reject_count >= 1` and neither reaches `threshold`
  - `0 = Open` otherwise

### 6.3. Functions & Append-Only Events
- **Admin (owner only):** `add_auditor(a)` (reverts if `a == empty(address)`, already auditor, or `a == self.owner`), `remove_auditor(a)` (**retains past attestations**, reverts if not auditor or `auditor_count - 1 < threshold`), `set_threshold(k)` (reverts if `k == 0` or `k > auditor_count`).
- **Auditor only:**
  - `register_case(case_id, subject, subject_chain_id, evidence_hash, model_version_hash, evidence_uri)` (`evidence_uri: String[128]` emitted in event only; reverts on duplicate `case_id` or zero hashes/subject).
  - `attest(case_id, decision, reason_hash)` (creates/replaces **caller's own** attestation, increments `revision`, updates counters and `status`; reverts if case missing, `decision not in {1, 2, 3}`, or `decision == current_decision`).
- **Public View:** `verify_evidence(case_id, h) -> bool`, `get_case(case_id)`, `get_attestation(case_id, auditor)`.
- **Events (Append-Only Ledger):** `AuditorAdded`, `AuditorRemoved`, `ThresholdChanged`, `CaseRegistered`, `Attested`, `StatusChanged`.
- **Non-Payable & Safe-by-Design:** No payable functions / `__default__`, no `raw_call`, no `selfdestruct`, bounded `String[128]`.

### 6.4. Storage Variants for `E5`
- **`D1` – Full Storage:** Full struct state as specified above.
- **`D2` – Event-Only:** Minimal storage (`case_exists`, `evidence_hash`, tally counters/status); metadata fields emitted solely in `CaseRegistered` events.
- **`D3` – Merkle Batch:** `register_batch(root, n_leaves, batch_uri)` with leaf `keccak256(abi.encode(case_id, evidence_hash, model_version_hash))`, `attest_batch(root, decision)`, and view verifier `verify_inclusion(leaf, proof: DynArray[bytes32, 32], root)`.

---

## 7. Canonical Evidence & DApp Architecture (Phase 6)

- **Model Versioning:** `modelVersionHash = keccak256(model_file_bytes || feature_schema_json)` captured in `models/baseline_v1/model_card.json`.
- **Canonical JSON (`docs/evidence_schema_v1.md` in Phase 6):** UTF-8, `sort_keys=True`, `separators=(",", ":")`, `allow_nan=False`, floating-point numbers formatted as fixed 6-decimal strings (e.g., `"0.873421"`), lowercase `0x` addresses, UTC ISO-8601 timestamps ending in `Z`.
- **Cryptographic Identifiers:**
  - `evidence_hash = keccak256(canonical_bytes(evidence))`
  - `case_id = keccak256(abi.encode(uint256 chain_id, address subject, bytes32 model_version_hash, bytes32 run_id))` (`abi.encode`, never `encode_packed`, to eliminate concatenation collisions).
- **Persistence:** `evidenceURI = ipfs://<CID>` (pinned) + Git mirror commit under `evidence/`.
- **UI & Signing Separation:**
  - 4-page Streamlit UI: (1) Risk Analysis (with explicit *"prediction, not legal fraud verdict"* notice), (2) Evidence Packaging, (3) Sign & Submit, (4) Public Verifier (`✅` / `❌` hash match + event history).
  - Browser signing via static `signer/index.html` (`ethers.js v6` + MetaMask); local Anvil test keys allowed only under explicit `"TEST KEY – ANVIL ONLY"` banner/env guard; Sepolia/production keys never touch the server.

---

## 8. Unified References

The reference numbering below (`[1]`–`[14]`) is shared across the Proposal, Week 3 Report, and all Phase 0–8 documents:

- `[1]` L. Pennella, F. Pinelli, and L. Galletta, "X-SPIDE: An eXplainable Machine Learning Pipeline for Detecting Smart Ponzi Contracts in Ethereum," *IEEE Access*, vol. 13, pp. 85037–85055, 2025, doi: `10.1109/ACCESS.2025.3569565`.
- `[2]` R. Liang et al., "Towards Effective Detection of Ponzi Schemes on Ethereum with Contract Runtime Behavior Graph," *ACM Trans. Softw. Eng. Methodol.*, vol. 34, no. 4, Art. 106, 2025, doi: `10.1145/3707458`.
- `[3]` R. Liang et al., "PonziGuard: Detecting Ponzi Schemes on Ethereum with Contract Runtime Behavior Graph (CRBG)," in *Proc. IEEE/ACM ICSE*, 2024, Art. 64, pp. 1–12, doi: `10.1145/3597503.3623318`.
- `[4]` G. C. Akor, L. A. C. Ahakonye, J. M. Lee, and D.-S. Kim, "ProvAuditChain: A Gas-Efficient On-Chain Provenance Framework for AI-Driven Smart Contract Audits," in *Proc. ICTC*, 2025, pp. 1155–1157. *(Only abstract-level metrics `~173,000` gas/cycle, `~$0.05 USD`, `~6` audits/min, `600` cycles on Arbitrum Sepolia are cited until full-text sub-operation breakdown is verified.)*
- `[5]` W. Chen et al., "Detecting Ponzi Schemes on Ethereum: Towards Healthier Blockchain Technology," in *Proc. WWW*, 2018, pp. 1409–1418, doi: `10.1145/3178876.3186046`.
- `[6]` M. Bartoletti, S. M. Carta, T. Cimoli, and R. Saia, "Dissecting Ponzi schemes on Ethereum: Identification, analysis, and impact," *Future Gener. Comput. Syst.*, vol. 102, pp. 259–277, 2020, doi: `10.1016/j.future.2019.08.014`.
- `[7]` S. Fan, S. Fu, H. Xu, and C. Zhu, "Expose Your Mask: Smart Ponzi Schemes Detection on Blockchain," in *Proc. IJCNN*, 2020, pp. 1–7, doi: `10.1109/IJCNN48605.2020.9207143`.
- `[8]` W. Chen, X. Li, Y. Sui, N. He, H. Wang, L. Wu, and X. Luo, "SADPonzi: Detecting and Characterizing Ponzi Schemes in Ethereum Smart Contracts," *Proc. ACM Meas. Anal. Comput. Syst.*, vol. 5, no. 2, Art. 26, pp. 26:1–26:30, Jun. 2021, doi: `10.1145/3460093`.
- `[9]` L. Pennella, "X-SPIDE: Official Source Code and Dataset," GitHub, 2025. https://github.com/LucaPennella/x-spide-smart-ponzi-detection
- `[10]` R. Liang et al., "PonziGuard Dataset and Tools," GitHub. https://github.com/PonziDetection/PonziGuard/tree/main/dataset
- `[11]` Blockchain@Unica, "Ethereum Ponzi Address List," GitHub. https://github.com/blockchain-unica/ethereum-ponzi/blob/master/ponzi-addresses.csv
- `[12]` scikit-learn developers, "StratifiedGroupKFold." https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.StratifiedGroupKFold.html
- `[13]` Solidity developers, "Contract Metadata." https://docs.soliditylang.org/en/latest/metadata.html
- `[14]` Faculty of Information Systems, UIT – VNU-HCM, "IS355 – Blockchain Technology: Project Lab Guidelines." https://itlearninghub.io.vn/en/courses/is355/project-lab.html
