# Pre-Registered Evaluation Protocol & Acceptance Criteria

**Project:** X-SPIDE-G (`Group 4 – DICTATOR`, IS355)  
**Pre-Registration Date:** 2026-11-13 (Committed in Phase 0 **prior** to any Phase 1–4 execution or `E3`–`E5` runs)  
**Companion Specs:** [design_v2.md](design_v2.md) · [threat_model.md](threat_model.md)

> **Commitment Statement:** All metrics, thresholds, statistical tests, minimum detectable effect sizes, dataset inclusion rules, and on-chain cost/latency targets below are frozen before running structural feature experiments (`E3`–`E4d`), sensitivity checks (`S1`–`S4`), external transfer (`E6`), or on-chain benchmarks (`E5`). Any post-hoc deviation or contingency trigger (e.g., Risk `R1`, `R4`, `R6`, `R7`, `R10`) will be explicitly labeled as a protocol deviation or pre-planned fallback in the final report.

---

## 1. Datasets, Anti-Leakage Splits & Inclusion Rules

### 1.1. Analysis Subsets
- **`S_full`:** All valid audited contracts in the X-SPIDE corpus [1], [9] (used for `E0` paper reproduction and `E1-full` reference).
- **`S_code`:** Subset of `S_full` with valid recovered runtime bytecode from repo, RPC `eth_getCode`, or BigQuery/archive recovery (used for all controlled comparisons `E1`–`E4d` so every feature set is evaluated on identical contracts).
- **Risk Trigger `R1`:** If `|S_code_Ponzi| < 400` after bytecode recovery, log Risk `R1` in `reports/data_audit.md`, optionally expand repeated CV to `10 × 5` (`50` folds) as pre-planned fallback, and mark underpowered borderline results as *inconclusive*.

### 1.2. Clone Grouping & Primary Splits
- **Primary Group Key (`group_near`):** Connected components (union-find) of contracts sharing `code_hash = keccak256(runtime_bytecode_stripped)` (CBOR metadata stripped when valid) or 5-gram normalized opcode MinHash LSH Jaccard similarity $\ge 0.90$ (`datasketch`, `128` permutations).
- **Primary CV Scheme:** `5 × 5` repeated `StratifiedGroupKFold(n_splits=5)` on `S_code` grouped by `group_near`, using fixed deterministic repeat seeds `[42, 43, 44, 45, 46]` (**25 paired folds** total).
- **Leakage Invariant:** Every split JSON in `splits/` must pass automated unit tests confirming `train_groups ∩ test_groups == ∅` for `group_near` (and `group_exact` in `S1`).

### 1.3. External Dataset Decision Rule (`E6`)
- Candidate external corpus: **Dataset 2 (PonziGuard / XBlock)** [2], [10].
- Deduplicate Dataset 2 against X-SPIDE (`S_full`) by: (i) normalized `address`, (ii) CBOR-stripped `code_hash`, and (iii) `group_near` LSH match (Jaccard $\ge 0.90$).
- **Hard Rule:**
  - If **$\ge 30$ non-overlapping Ponzi contracts** remain → run `E6` (code-only LightGBM trained on `S_code`, evaluated on deduped Dataset 2 with `1,000`-resample stratified bootstrap 95% CIs).
  - If **$< 30$ non-overlapping Ponzi contracts** remain → downgrade Dataset 2 to a **qualitative sanity check** (`R6`) and do not report `E6` as a formal generalization benchmark.

---

## 2. Pre-Registered Experiment Matrix

| ID | Purpose | Dataset | Feature Set | Split / Setup | Primary Metric |
|---|---|---|---|---|---|
| `E0` | Paper reproduction | `S_full` | 47 (paper set) | Paper random split & grid | P, R, F1, ROC-AUC vs [1] |
| `E1-full` | Grouped ref. on full set | `S_full` | 99 | `group_near` 5×5 CV | PR-AUC |
| **`E1`** | **Primary ML baseline** | `S_code` | 99 | `group_near` 5×5 CV | PR-AUC |
| `E2` | In-fold feature selection | `S_code` | RFE fit inside train fold | `group_near` 5×5 CV | $\Delta\text{PR-AUC}$ vs `E1` |
| `E3` | Transition stats only | `S_code` | `F-GSTAT` | `group_near` 5×5 CV | PR-AUC |
| `E3b` | Bigram baseline only | `S_code` | `F-BIGRAM` (top-200 in-fold) | `group_near` 5×5 CV | PR-AUC |
| `E3c` | CFG semantic only | `S_code` | `F-GSEM` | `group_near` 5×5 CV | PR-AUC |
| `E4` | Baseline + `F-GSTAT` | `S_code` | `99 + F-GSTAT` | `group_near` 5×5 CV | $\Delta\text{PR-AUC}$ vs `E1` |
| `E4b` | Baseline + `F-BIGRAM` | `S_code` | `99 + F-BIGRAM` | `group_near` 5×5 CV | $\Delta\text{PR-AUC}$ vs `E1` |
| `E4c` | Baseline + `F-GSEM` | `S_code` | `99 + F-GSEM` | `group_near` 5×5 CV | $\Delta\text{PR-AUC}$ vs `E1` & `E4b` |
| `E4d` | Incremental CFG beyond bigram | `S_code` | `99 + F-BIGRAM + F-GSEM` | `group_near` 5×5 CV | $\Delta\text{PR-AUC}$ vs `E4b` |
| `S1` | Clone granularity sensitivity | `S_code` | `E1`, `E4c` | `group_exact` vs `group_near` | $\Delta\text{PR-AUC}$, $\Delta\text{F1}$ |
| `S2` | Metadata stripping sensitivity | `S_code` | `E1`, `E4c` | Raw vs CBOR-stripped | $\Delta\text{PR-AUC}$, $\Delta\text{F1}$ |
| `S3` | Temporal drift (if `block_number` avail.) | `S_code` | `E1`, `E4c` | Latest 20% deployment blocks | PR-AUC, F1 |
| `S4` | Mnemonic norm sensitivity | `S_code` | `E4b`, `E4c` | Normalized vs raw opcodes | $\Delta\text{PR-AUC}$, $\Delta\text{F1}$ |
| `E5` | On-chain benchmark | — | — | `D1` / `D2` / `D3` on Anvil, Sepolia, L2 | Gas, USD, latency, `T1`–`T12` |
| `E6` | Conditional external transfer | Dataset 2 deduped | Code-only (`op_freq + BIGRAM + GSEM`) | Train `S_code`, test Dataset 2 | PR-AUC + bootstrap CI |

---

## 3. Metrics, Thresholding & Anti-Leakage Training Parity

### 3.1. Evaluation Metrics
- **Primary Metric:** **PR-AUC** (`sklearn.metrics.average_precision_score` on positive class `Ponzi = 1`), chosen because Ponzi contracts are a minority class (~10–12%) where ROC-AUC can remain optimistically high despite high false-positive rates.
- **Secondary Metrics:** `F1`, `Precision`, `Recall`, `ROC-AUC`, and `Recall@Precision≥0.90` (defined as the maximum recall achievable on the precision–recall curve where `precision >= 0.90`; if `0.90` precision is never attained on a fold, record `0.0` and log the fallback count).

### 3.2. Classification Threshold Rule (Strict No-Test-Tuning)
- For binary metrics (`F1`, `Precision`, `Recall`, confusion matrix), the probability threshold $\tau^*$ is chosen per outer fold to maximize `F1` on **out-of-fold validation predictions strictly inside the training split** (inner CV).
- **Prohibition:** The outer test fold must **never** be inspected to tune hyperparameters, feature selection (`F-BIGRAM` top-k, `E2` RFE), class weighting, or $\tau^*$.

### 3.3. Hyperparameter Budget Parity
Every configuration in `E1`–`E4d` uses the exact same tuning pipeline:
- Inner loop: `StratifiedGroupKFold(n_splits=3)` on the outer training fold (`groups = group_near`).
- Fixed budget: **30 Optuna trials** (TPE sampler, fixed seed per fold) optimizing inner-CV mean `PR-AUC`, searching over LightGBM capacity/regularization (`num_leaves`, `max_depth`, `learning_rate`, `n_estimators`, `min_child_samples`, `subsample`, `colsample_bytree`, `reg_alpha`, `reg_lambda`) and class-imbalance handling (`scale_pos_weight` vs `is_unbalance`).
- Top-$k = 200$ document-frequency selection for `F-BIGRAM` and RFE for `E2` are wrapped inside `sklearn.pipeline.Pipeline` so every fold fits strictly on its training slice.

---

## 4. Statistical Hypothesis Tests & Decision Criteria (RQ2)

### 4.1. Pre-Registered Pairwise Comparisons
Across the **25 paired folds** ($r = 5$ repeats $\times k = 5$ folds, $N_{\text{folds}} = 25$), compute fold-level differences $\Delta_i = \text{PR-AUC}_{A, i} - \text{PR-AUC}_{B, i}$ for the registered family:
1. **Vs. `E1` (Baseline 99 features):** `E4 vs E1`, `E4b vs E1`, `E4c vs E1`, `E2 vs E1`
2. **Novelty Critical (CFG vs. Bigram):** `E4c vs E4b` (`99 + GSEM` vs `99 + BIGRAM`) and `E4d vs E4b` (`99 + BIGRAM + GSEM` vs `99 + BIGRAM`)
3. **Code-Only Structural Comparison:** `E3c vs E3b` (`GSEM` vs `BIGRAM`) and `E3c vs E3` (`GSEM` vs `GSTAT`)

### 4.2. Statistical Estimators
- **Nadeau–Bengio Corrected Resampled $t$-Test:** Accounts for overlapping training sets across repeated CV folds:
  $$\bar{\Delta} = \frac{1}{J} \sum_{i=1}^{J} \Delta_i, \quad \hat{\sigma}_{\text{NB}}^2 = \left(\frac{1}{J} + \frac{n_{\text{test}}}{n_{\text{train}}}\right) s_\Delta^2, \quad \text{CI}_{95\%} = \bar{\Delta} \pm t_{0.975,\, J-1} \cdot \hat{\sigma}_{\text{NB}}$$
  where $J = 25$, $s_\Delta^2$ is the sample variance across the 25 fold deltas, and $\frac{n_{\text{test}}}{n_{\text{train}}}$ is computed per fold (approx. $1/4$ for 5-fold CV).
- **Wilcoxon Signed-Rank Test + Holm–Bonferroni Adjustment:** Paired non-parametric Wilcoxon signed-rank test across the 25 fold pairs, applying **Holm step-down adjustment** ($p_{\text{Holm}}$) across the 8 pre-registered family comparisons above.

### 4.3. Three-Way Conclusion Decision Rule (MDE = $\Delta\text{PR-AUC} \ge 0.02$)
For every comparison $(A \text{ vs } B)$, the outcome **must** be classified strictly by these rules:

1. **Confirmed Improvement:**
   $$\bar{\Delta} \ge 0.02 \quad \text{AND} \quad \text{CI}_{95\%, \text{lower}} > 0 \quad \text{AND} \quad p_{\text{Holm}} < 0.05$$
2. **No Significant Difference:**
   $$\text{CI}_{95\%, \text{lower}} \le 0 \le \text{CI}_{95\%, \text{upper}} \quad (\text{95\% CI contains } 0)$$
3. **Inconclusive:** All remaining outcomes (e.g., $\text{CI}_{95\%} > 0$ and $p_{\text{Holm}} < 0.05$ but $0 < \bar{\Delta} < 0.02$; or `R1` sample-size fallback triggered without meeting confirmed bounds).

### 4.4. CFG Quality Guard (`R4`)
If `unresolved_jump_ratio > 50%` across `S_code`, report that limit prominently and run an auxiliary ablation restricted to jump-independent `F-GSEM` descriptors (`n_blocks`, `n_blocks_with_call`, `call_block_ratio`, `has_selfdestruct`, `pagerank_CALL`, `pagerank_SSTORE`).

---

## 5. On-Chain Acceptance Criteria (Phase 7 – `E5`)

| Design / Metric | Pre-Registered Target | Measurement Protocol |
|---|---|---|
| **`D1` (Full Storage) Gas Cost** | $\le \mathbf{250,000}$ gas per finalized case (`register_case` + $k=2$ `attest`) | Deterministic `gasUsed` on Anvil (cold first write vs warm update), spot-checked on Sepolia. |
| **`D3` (Merkle Batch) Amortized Gas** | $\le \mathbf{10,000}$ gas per case when batch size $N \ge 100$ | Measure `register_batch` + $k=2$ `attest_batch` for $N \in \{1, 10, 100, 1000\}$; plot `gas_vs_batch.png`. |
| **Sepolia Confirmation Latency** | Median $\le \mathbf{2\text{ blocks}}$ to 1 confirmation | Send $30$ `attest` txs on Sepolia & L2 testnet (fallback min $15$ if faucet limits trigger `R7`); report median & p95 in seconds and blocks. |
| **Security Invariants (`T1`–`T12`)** | $100\%$ pass on Anvil + verified revert txs on Sepolia | Full unit/property/fuzz suite on Anvil (`T1`–`T12`) + saved revert tx hashes for `T1`, `T6`, `T8` on Sepolia. |
| **Mainnet Cost Reference** | Transparent formula, fixed-date anchor | $\text{Cost} = \text{gasUsed} \times \text{median mainnet gas price} \times \text{ETH/USD}$ on a fixed logged date & source. |

---

## 6. Contingency & Scope Protection (`R10`)

If end-of-term schedule pressure triggers Risk `R10` (> 3 days behind phase exit criteria), optional extensions may be trimmed **only** in the following order: `S4` → `E6` → `D2` → `L2 testnet`. **Never cut:** `E1`, `E4b`, `E4c`, statistical tests (`Nadeau–Bengio / Wilcoxon / Holm`), and contract security tests `T1`–`T8`.
