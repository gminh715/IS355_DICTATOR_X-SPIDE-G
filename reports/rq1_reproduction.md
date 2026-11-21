# Phase 2 Report – RQ1 Baseline Reproduction & Clone-Leakage Analysis (`reports/rq1_reproduction.md`)

- **Generated (UTC):** 2026-11-13T07:39:06Z *(updated `2026-11-21` in `v1.1` Phase 3 with controlled `E1_S0_random_5x5` causal decomposition)*
- **Commits:** `1d344d2eb88c` (Phase 2 `E0`–`E2`) · `9f9a032a39f7` (`v1.1` Phase 3 `E1_S0_random_5x5`)
- **Corpus:** `S_full` = `7,446`, `S_code` = `7,446` (`880` Ponzi / `6,566` non-Ponzi; 100% deployed bytecode coverage, so `E1-full == E1`).

## 1. E0 – Reproduction of Published X-SPIDE Paper [1]

| Run ID | Split | Feats | Acc | Precision | Recall | F1 | ROC-AUC | PR-AUC | $\Delta$F1 vs [1] | $\Delta$ROC-AUC vs [1] |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `published_xspide_paper` | `paper_reported` | 47 | 0.9690 | 0.8700 | 0.8640 | 0.8670 | 0.9770 | — | +0.0000 | +0.0000 |
| `E0_1009_47feats_unbal` | `random_85_15_stratified` | 47 | 0.9615 | 0.8504 | 0.8182 | 0.8340 | 0.9772 | 0.9173 | -0.0330 | +0.0002 |
| `E0_1009_47feats_default` | `random_85_15_stratified` | 47 | 0.9687 | 0.9217 | 0.8030 | 0.8583 | 0.9808 | 0.9204 | -0.0087 | +0.0038 |
| `E0_2710_43feats` | `random_85_15_stratified` | 43 | 0.9678 | 0.9286 | 0.7879 | 0.8525 | 0.9806 | 0.9214 | -0.0145 | +0.0036 |
| `E0_gridsearch10cv_99feats` | `random_85_15_stratified` | 99 | 0.9651 | 0.9043 | 0.7879 | 0.8421 | 0.9736 | 0.9224 | -0.0249 | -0.0034 |
| `E0_random5fold_47feats_unbal_mean` | `S_full_E0_random_5fold_mean` | 47 | 0.9655 | 0.8647 | 0.8398 | 0.8519 | 0.9757 | 0.9146 | -0.0151 | -0.0013 |
| `E0_random5fold_99feats_gridbest_mean` | `S_full_E0_random_5fold_mean` | 99 | 0.9686 | 0.9158 | 0.8091 | 0.8589 | 0.9768 | 0.9149 | -0.0081 | -0.0002 |

**Reproduction gap analysis ($|\Delta| > 0.02$ check):**
- **`E0_1009_47feats_unbal`** (exact `code/1009_best_features_SHAP.ipynb` 47-feature list + `is_unbalance=True` on 85/15 stratified split): `ROC-AUC = 0.9772` matches published `0.977` ($\Delta = +0.0002$), while `Recall = 0.8182` ($\Delta = -0.0458$) and `F1 = 0.8340` ($\Delta = -0.0330$) deviate by more than `0.02`.
- **`E0_2710_43feats`** (exact `code/2710_best_features_SHAP.ipynb` saved in the authors' repo): `ROC-AUC = 0.9806`, `Accuracy = 0.9678`, `F1 = 0.8525` ($\Delta = -0.0145$), with higher Precision (`0.9286`) and lower Recall (`0.7879`, $\Delta = -0.0761$) at the default `0.5` cutoff.
- **Root causes of observed deviations:** (1) LightGBM library evolution (`4.7.0` vs the authors' 2024/2025 notebook environment) changes exact tree split tie-breaking and `is_unbalance` calibration at fixed `threshold=0.5`; (2) the official GitHub repository stores two slightly different post-RFE feature subsets (`47` features in `1009_best_features_SHAP.ipynb` with cleared outputs vs `43` features in `2710_best_features_SHAP.ipynb`), and the paper table likely reflects either a different random seed / RFE run or threshold/post-processing not preserved verbatim in the committed notebooks.

## 2. RQ1 – Controlled Causal Decomposition: Random Split (`E0` / `E1_S0`) to Clone-Grouped 5×5 CV (`E1_S1` / `E1`)

| Config | Split Scheme & Protocol | Folds | PR-AUC | ROC-AUC | F1 | Precision | Recall | Recall@P≥0.90 | Avg Feats |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `E0` (47 feats, unbal) | Random 5-fold (`S_full`, fixed `0.5`) | 5 | 0.9146 | 0.9757 | 0.8519 | 0.8647 | 0.8398 | 0.7898 | 47.0 |
| `E0` (99 feats, grid best) | Random 5-fold (`S_full`, GridSearch + `0.5`) | 5 | 0.9149 | 0.9768 | 0.8589 | 0.9158 | 0.8091 | 0.8273 | 99.0 |
| **`E1_S0_random_5x5`** *(v1.1 control)* | **Random 5×5 CV (`S_code_random`, Nested Optuna + $\tau^*$)** | **25** | **0.9251 ± 0.0110** | **0.9785 ± 0.0062** | **0.8679 ± 0.0149** | **0.8858 ± 0.0274** | **0.8518 ± 0.0280** | **0.8393 ± 0.0274** | 99.0 |
| `E1_S1_group_exact` | `group_exact` 5×5 CV (`S_code`, Nested Optuna + $\tau^*$) | 25 | 0.9051 ± 0.0197 | 0.9730 ± 0.0072 | 0.8379 ± 0.0243 | 0.8777 ± 0.0315 | 0.8045 ± 0.0533 | 0.7895 ± 0.0484 | 99.0 |
| **`E1` (99 feats, nested Optuna)** | **`group_near` 5×5 CV (`S_code`, Nested Optuna + $\tau^*$)** | **25** | **0.8767 ± 0.0254** | **0.9631 ± 0.0116** | **0.8118 ± 0.0275** | **0.8374 ± 0.0397** | **0.7909 ± 0.0506** | **0.7141 ± 0.0991** | 99.0 |
| `E2` (in-fold RFE Pipeline) | `group_near` 5×5 CV (`S_code`, Nested Optuna + $\tau^*$) | 25 | 0.8768 ± 0.0237 | 0.9638 ± 0.0115 | 0.8095 ± 0.0264 | 0.8392 ± 0.0451 | 0.7848 ± 0.0445 | 0.7148 ± 0.0815 | 71.4 ± 16.7 |

### Controlled 3-Step Causal Decomposition (`v1.1`)

Adding `E1_S0_random_5x5` (`results/E1_S0_random_5x5_folds.csv`) holds the 99-feature space, 30-trial inner Optuna TPE budget, and inner OOF F1 threshold $\tau^*$ strictly fixed across random, exact-clone, and near-clone splits, disentangling evaluation-protocol effects from pure clone leakage:

| Transition | Single Factor Varied | $\Delta$PR-AUC | $\Delta$F1 | $\Delta$Recall@P≥0.90 | Causal Interpretation |
|---|---|---:|---:|---:|---|
| `E0 (99 random 5-fold)` → `E1_S0_random_5x5` | Tuning & cutoff (`GridSearch + 0.5` → `5×5 Nested Optuna + τ*`) | **`+0.0102`** | **`+0.0090`** | `+0.0120` | Pure evaluation-protocol uplift |
| `E1_S0_random_5x5` → `E1_S1_group_exact` | Exact-clone quarantine (`random` → `group_exact`) | **`-0.0201`** | **`-0.0300`** | `-0.0498` | Pure exact-clone leakage |
| `E1_S1_group_exact` → `E1 (group_near)` | Near-clone quarantine (`group_exact` → MinHash $J \ge 0.90$) | **`-0.0283`** | **`-0.0261`** | `-0.0755` | Pure near-clone leakage |
| **`E1_S0_random_5x5` → `E1 (group_near)`** | **Full clone quarantine under identical 5×5 nested protocol** | **`-0.0484`** | **`-0.0561`** | **`-0.1252`** | **Total pure clone leakage** |
| `E0 (99 random 5-fold)` → `E1 (group_near)` | Combined transition (protocol `+0.0102` + clone `-0.0484`) | `-0.0382` | `-0.0471` | `-0.1132` | Net paper-to-leak-free shift |

**Key RQ1 findings:**
- **Pure clone leakage (`E1_S0_random_5x5` → `E1`):** Under an identical 5×5 nested Optuna + $\tau^*$ protocol, blocking exact and near-clones lowers `PR-AUC` by **`-0.0484`** (`0.9251` → `0.8767`, decomposed cleanly into **`-0.0201`** exact-clone + **`-0.0283`** near-clone leakage), `F1` by **`-0.0561`** (`0.8679` → `0.8118`), and `Recall@P>=0.90` by **`-0.1252`** (`0.8393` → `0.7141`). Notably, the net paper-style `E0` → `E1` drop (`-0.0382` PR-AUC, `-0.0471` F1) actually *underestimated* pure clone leakage by `0.0102` PR-AUC because moving from `GridSearch + 0.5` to `5×5 Nested Optuna + τ*` improved random-split performance (`+0.0102` PR-AUC).
- **In-fold RFE (`E2`) vs Full 99 (`E1`):** Across the 25 paired `group_near` folds, `E2` selects `71.4 ± 16.7` features inside each fold with paired difference `ΔPR-AUC = +0.0000 ± 0.0064` and `ΔF1 = -0.0023 ± 0.0146` relative to `E1` (formal Nadeau–Bengio & Holm tests across all models are executed in Phase 4).
- **`Recall@P>=0.90` fallback count:** `E1_S0`, `E1_S1`, `E1`, and `E2` all triggered `0/25` fallback folds.

## 3. Frozen Demo Baseline Artifact (`models/baseline_v1/`)

- **Demo split:** `S_code_group_near_seed42_fold0.json` (`n_train=5957`, `n_test=1489`)
- **Validation-tuned threshold $\tau^*$:** `0.256746`
- **`feature_schema_hash`:** `0xac12b3e03d1418790a091bd61a5ed919344863ff97ce781b874ebc463f843c01`
- **`modelVersionHash`:** `0x5d00194582127b30dabce1702fb84502d52eef96c5045ea090a738b6fe5796b5`
- **Demo test-fold metrics:** `PR-AUC=0.8956`, `ROC-AUC=0.9641`, `F1=0.8222`, `P=0.8443`, `R=0.8011`, `Recall@P>=0.9=0.7500`
