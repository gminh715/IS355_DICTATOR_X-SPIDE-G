# Phase 2 Report – RQ1 Baseline Reproduction & Clone-Leakage Analysis (`reports/rq1_reproduction.md`)

- **Generated (UTC):** 2026-11-13T07:39:06Z
- **Commit:** `1d344d2eb88c3303f9d127b6767cb5bf596af417`
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

## 2. RQ1 – Impact of Moving from Random Split (`E0`) to Clone-Grouped 5×5 CV (`E1`)

| Config | Split Scheme | Folds | PR-AUC | ROC-AUC | F1 | Precision | Recall | Recall@P≥0.90 | Avg Feats |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `E0` (47 feats, unbal) | Random 5-fold (`S_full`) | 5 | 0.9146 | 0.9757 | 0.8519 | 0.8647 | 0.8398 | 0.7898 | 47.0 |
| `E0` (99 feats, grid best) | Random 5-fold (`S_full`) | 5 | 0.9149 | 0.9768 | 0.8589 | 0.9158 | 0.8091 | 0.8273 | 99.0 |
| **`E1` (99 feats, nested Optuna)** | **`group_near` 5×5 CV (`S_code`)** | **25** | **0.8767 ± 0.0254** | **0.9631 ± 0.0116** | **0.8118 ± 0.0275** | **0.8374 ± 0.0397** | **0.7909 ± 0.0506** | **0.7141 ± 0.0991** | 99.0 |
| `E2` (in-fold RFE Pipeline) | `group_near` 5×5 CV (`S_code`) | 25 | 0.8768 ± 0.0237 | 0.9638 ± 0.0115 | 0.8095 ± 0.0264 | 0.8392 ± 0.0451 | 0.7848 ± 0.0445 | 0.7148 ± 0.0815 | 71.4 ± 16.7 |

**Key RQ1 findings:**
- **Combined protocol & clone-grouping shift (`E0` → `E1`):** Moving from the paper-style 5-fold random evaluation (`E0` 99 features, fixed `0.5` cutoff and `tr_85` GridSearchCV) to leakage-controlled `group_near` 5×5 nested Optuna CV (`E1`, inner OOF F1 threshold) changes `PR-AUC` by **-0.0382** (`0.9149` → `0.8767`), `ROC-AUC` by **-0.0138** (`0.9768` → `0.9631`), and `F1` by **-0.0471** (`0.8589` → `0.8118`). Because `E0` and `E1` differ in tuning protocol, fold count (5 vs 25), and thresholding alongside split grouping, this `-0.0382` shift reflects the combined transition to strict nested grouped evaluation; Phase 4 sensitivity `S1` (`E1_S1_group_exact` vs `E1`) isolates the pure near-clone vs exact-clone grouping effect (`-0.0283` PR-AUC, `-0.0261` F1) under identical 5×5 nested tuning.
- **In-fold RFE (`E2`) vs Full 99 (`E1`):** Across the 25 paired `group_near` folds, `E2` selects `71.4 ± 16.7` features inside each fold with paired difference `ΔPR-AUC = +0.0000 ± 0.0064` and `ΔF1 = -0.0023 ± 0.0146` relative to `E1` (formal Nadeau–Bengio & Holm tests across all models are executed in Phase 4).
- **`Recall@P>=0.90` fallback count:** `E1` fell back to `0.0` on `0/25` folds; `E2` on `0/25` folds.

## 3. Frozen Demo Baseline Artifact (`models/baseline_v1/`)

- **Demo split:** `S_code_group_near_seed42_fold0.json` (`n_train=5957`, `n_test=1489`)
- **Validation-tuned threshold $\tau^*$:** `0.256746`
- **`feature_schema_hash`:** `0xac12b3e03d1418790a091bd61a5ed919344863ff97ce781b874ebc463f843c01`
- **`modelVersionHash`:** `0x5d00194582127b30dabce1702fb84502d52eef96c5045ea090a738b6fe5796b5`
- **Demo test-fold metrics:** `PR-AUC=0.8956`, `ROC-AUC=0.9641`, `F1=0.8222`, `P=0.8443`, `R=0.8011`, `Recall@P>=0.9=0.7500`
