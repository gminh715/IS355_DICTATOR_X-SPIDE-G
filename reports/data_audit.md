# Phase 1 Data Audit Report (`reports/data_audit.md`)

- **Generated (UTC):** 2026-11-13T06:36:23Z
- **Primary Corpus:** X-SPIDE (`DS_deployed_bytecode.csv`, commit `dcf6027c2bd15cb1833cca3fc86265df4394b05a`)
- **Risk Status:** `R1 (<400 Ponzi in S_code)`: **NOT TRIGGERED** (`880` Ponzi in `S_code`); `R6 (Dataset 2 overlap/coverage)`: **SANITY_CHECK_ONLY (Risk R6 triggered)**

## 1. Schema & Label Verification (Phase 1.2)

| File | Rows | Cols | Ponzi (`1`) | non-Ponzi (`0`) | Unique Valid Addrs | Conflicting Labels |
|---|---:|---:|---:|---:|---:|---:|
| `DS_deployed_bytecode.csv` | 7,446 | 101 | 880 | 6,566 | 7,446 | 0 |
| `DS_full_bytecode.csv` | 7,446 | 101 | 880 | 6,566 | 7,446 | 0 |
| `bytecode_opcode_8k.csv` | 7,962 | 102 | 934 | 7,028 | 7,962 | 0 |
| `address_without_byt.csv` | 209 | 2 | 0 | 0 | 209 | 0 |

> **Comparison with X-SPIDE paper [1]:** `DS_deployed_bytecode.csv` and `DS_full_bytecode.csv` both contain exactly **7,446** contracts (**880** Ponzi / **6,566** non-Ponzi) with **99** features (`23` account/transaction + `76` opcode-frequency columns), zero missing CSV cells, and zero duplicate or malformed addresses. The raw pre-cleaning `bytecode_opcode_8k.csv` inventory contains **7,962** contracts (**934** Ponzi / **7,028** non-Ponzi), from which **516** rows (**54** Ponzi / **462** non-Ponzi) were excluded when forming the 7,446-contract benchmark.

## 2. Bytecode Coverage & Self-Destruct / Selection Bias Audit (Phase 1.3)

### 2.1. `S_full` vs `S_code` Coverage (`DS_deployed_bytecode.csv`)

| Class | `S_full` | `S_code` (Recovered) | Coverage | `bytecode_source = xspide_repo` | `rpc_latest` | `missing` |
|---|---:|---:|---:|---:|---:|---:|
| Ponzi (`1`) | 880 | 880 | 100.00% | 880 | 0 | 0 |
| non-Ponzi (`0`) | 6,566 | 6,566 | 100.00% | 6,566 | 0 | 0 |

### 2.2. Live Ethereum Mainnet `eth_getCode('latest')` Verification & 8k Selection Bias

- **Live RPC check on `DS_deployed_bytecode.csv`:** `880/880` Ponzi contracts and `880/880` sampled non-Ponzi contracts still have deployed bytecode on mainnet (`0x` rate = `0.0%` vs `0.0%`).
- **Raw 8k missing-deployed-bytecode (`308` rows: `42` Ponzi, `266` non-Ponzi):** `0` recovered via live `eth_getCode('latest')` (`308` remain `0x`, confirming they were EOAs or already self-destructed before X-SPIDE archived the 7,446-contract dataset).

### 2.3. KS Distribution & Median Test: `7,446` Retained vs `516` Excluded Rows from `bytecode_opcode_8k.csv`

| Feature | `n` (Kept) | `n` (Excluded) | Median (Kept) | Median (Excluded) | KS Statistic | $p$-value |
|---|---:|---:|---:|---:|---:|---:|
| `balance` | 7,446 | 516 | 0 | 0 | 0.1086 | 2.046e-05 |
| `lifetime` | 7,446 | 516 | 15 | 2 | 0.1384 | 1.583e-08 |
| `tx_in` | 7,446 | 516 | 11 | 6 | 0.1983 | 4.276e-17 |
| `tx_out` | 7,446 | 516 | 0 | 1 | 0.2467 | 2.497e-26 |
| `investment_in` | 7,446 | 516 | 0 | 1 | 0.0917 | 5.525e-04 |
| `payment_out` | 7,446 | 516 | 0 | 1 | 0.1212 | 1.242e-06 |
| `paid_rate` | 7,446 | 516 | 0 | 0.25 | 0.1412 | 7.426e-09 |

## 3. CBOR Metadata Stripping & Clone Clustering (Phase 1.4 – 1.5)

### 3.1. CBOR Metadata Status

| `metadata_stripped` | Total | Ponzi (`1`) | non-Ponzi (`0`) | Interpretation |
|---|---:|---:|---:|---|
| `true` | 6,417 | 595 | 5,822 | Valid Solidity/Vyper CBOR footer decoded & stripped |
| `false` | 1,029 | 285 | 744 | Pre-0.4.7 Solidity or custom bytecode without CBOR footer |
| `none` | 0 | 0 | 0 | Missing bytecode |

### 3.2. Clone Cluster Summary (`group_exact` vs `group_near`)

| Grouping | Total Groups | Singletons | Size 2–5 | Size 6+ | Max Size | Mixed-Label Groups | Ponzi in Multi-Clone Groups | non-Ponzi in Multi-Clone Groups |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `group_exact` | 6,145 | 5,696 | 393 | 56 | 91 | 10 | 225/880 (25.6%) | 1,525/6,566 (23.2%) |
| `group_near` | 4,711 | 3,825 | 762 | 124 | 99 | 24 | 520/880 (59.1%) | 3,101/6,566 (47.2%) |

**Mixed-label clusters detected in `group_near` (label-noise / template-reuse warning):**

| `group_near` | Total | Ponzi | non-Ponzi |
|---|---:|---:|---:|
| `near_00093` | 14 | 6 | 8 |
| `near_00126` | 4 | 3 | 1 |
| `near_00144` | 15 | 14 | 1 |
| `near_00207` | 2 | 1 | 1 |
| `near_00260` | 7 | 6 | 1 |
| `near_00297` | 9 | 1 | 8 |
| `near_00641` | 12 | 9 | 3 |
| `near_01003` | 5 | 1 | 4 |
| `near_01094` | 2 | 1 | 1 |
| `near_01229` | 7 | 6 | 1 |
| `near_01289` | 9 | 8 | 1 |
| `near_01380` | 3 | 1 | 2 |
| `near_01393` | 7 | 6 | 1 |
| `near_01488` | 5 | 1 | 4 |
| `near_01523` | 2 | 1 | 1 |

## 4. Cross-Dataset Overlap & Dataset 2 Decision (Phase 1.6)

- **Blockchain@Unica [6], [11]:** `184` rows (`182` unique addresses). **`161` / `182`** addresses already appear in X-SPIDE (all labeled `1` Ponzi: `{1: 161}`). Among the `21` address-disjoint entries, `13` had live RPC code, of which `3` matched X-SPIDE by `code_hash` and `4` by `group_near`.
- **PonziGuard / XBlock (`Ponzi.zip` + `non-Ponzi.zip`) [2], [10]:**
  - `Ponzi/Ponzi contracts/*.sol`: `139` address-named Solidity files → **`122` / `139`** (`87.8%`) are already present in X-SPIDE, leaving only **`17`** non-overlapping addresses.
  - `Ponzi/verified_contract_bins/*.bin` (creation initcode without addresses): `89/95` yielded extractable deployed runtime bytecode; **`78`** matched X-SPIDE by exact `code_hash` and **`78`** matched by `group_near`, leaving **`11`** runtime samples (**`10`** unique `code_hash`).
  - `non-Ponzi/verified_contract_bins/*.bin` (creation initcode without addresses): `1291/1312` yielded extractable deployed runtime bytecode; `1174` matched X-SPIDE by `code_hash` and `1194` matched by `group_near`, leaving `97` samples (`97` unique `code_hash`).
  - `Result/verified/*.sol` (mainnet verified subset): `43/50` already present in X-SPIDE.
- **Pre-Registered Decision for Dataset 2 (`E6`):** **SANITY_CHECK_ONLY (Risk R6 triggered)** — Because the released `PonziGuard` GitHub archive lacks contract addresses on `non-Ponzi.zip` and `verified_contract_bins`, lacks the full `6,498`-contract `314`-Ponzi XBlock split described in TOSEM [2], and yields `< 30` non-overlapping address-verified Ponzi contracts (`17` in `Ponzi/*.sol`, `11` total runtime `.bin` rows / `10` unique hashes), Dataset 2 is **downgraded to a qualitative/code-only sanity check** rather than a formal `E6` external generalization benchmark.

## 5. Frozen Splits Summary (Phase 1.7 + v1.1 Phase 3 `S0` Control = `80` Files)

- `S_code_group_near_seed{42..46}_fold{0..4}.json`: **25** files (`StratifiedGroupKFold(5)` × 5 repeats on `group_near`, `|S_code|=7446`).
- `S_code_group_exact_seed{42..46}_fold{0..4}.json`: **25** files (for sensitivity analysis `S1`).
- `S_code_random_seed{42..46}_fold{0..4}.json`: **25** files (added in `v1.1` Phase 3 using `StratifiedKFold(5)` across seeds `42..46` for the controlled `E1_S0_random_5x5` protocol-vs-clone decomposition).
- `S_full_E0_random_seed42_fold{0..4}.json`: **5** files (for `E0` paper-style random baseline reference only, `|S_full|=7446`).
- `S_code_temporal_holdout.json` (`S3`): **not generated** — `block_number` is absent in X-SPIDE CSV/archives and Google BigQuery credentials (`bq_available=False`) are not configured locally.

## 6. Real Contract Samples (5 Ponzi + 5 non-Ponzi, Phase 1.2)

| `sample_id` | `address` | `label` | `tx_in` | `tx_out` | `lifetime` | `bytecode_source` | `metadata_stripped` | `code_hash` (prefix) | `group_exact` | `group_near` |
|---|---|---:|---:|---:|---:|---|---|---|---|---|
| `xspide_00439` | `0x2c2e3baa2191cf325a28a01ff42340f2ae677572` | 1 | 417 | 155 | 169.0 | `xspide_repo` | `false` | `0x7c3b756e6191...` | `exact_00405` | `near_00260` |
| `xspide_00468` | `0x2df0e612dad9ffe8141b3987f60608742db2feca` | 1 | 34 | 3 | 31.0 | `xspide_repo` | `true` | `0xea11b86cab2a...` | `exact_00428` | `near_02774` |
| `xspide_00476` | `0x2ef76694fbfd691141d83f921a5ba710525de9b0` | 1 | 753 | 13 | 11.0 | `xspide_repo` | `false` | `0x041d77b57944...` | `exact_00434` | `near_00099` |
| `xspide_00508` | `0x31e13882c45c1023d9b16c3794c1a780bb6cb88d` | 1 | 251 | 36 | 169.0 | `xspide_repo` | `false` | `0x7c3b756e6191...` | `exact_00405` | `near_00260` |
| `xspide_00531` | `0x33a683a7af55942220e4efec514da11b5dc47996` | 1 | 102 | 83 | 84.0 | `xspide_repo` | `false` | `0x8c638826bd18...` | `exact_00479` | `near_01289` |
| `xspide_00000` | `0x0006157838d5a6b33ab66588a6a693a57c869999` | 0 | 2 | 0 | 117.0 | `xspide_repo` | `true` | `0x5e2dc4ab48dd...` | `exact_00000` | `near_02005` |
| `xspide_00001` | `0x001a589dda0d6be37632925eaf1256986b2c6ad0` | 0 | 11346 | 4 | 318.0 | `xspide_repo` | `false` | `0x044469e1a012...` | `exact_00001` | `near_00105` |
| `xspide_00002` | `0x00674045bb7c17f0aa1cde34780d6c51af548728` | 0 | 29 | 12 | 1366.0 | `xspide_repo` | `true` | `0xd6c5146743c6...` | `exact_00002` | `near_03145` |
| `xspide_00003` | `0x006bea43baa3f7a6f765f14f10a1a1b08334ef45` | 0 | 9708 | 0 | 21.0 | `xspide_repo` | `true` | `0x9da69608ed19...` | `exact_00003` | `near_00109` |
| `xspide_00004` | `0x00a9f7d093c46d95f0318e4a6ffc6ed68f73044c` | 0 | 78 | 1 | 0.0 | `xspide_repo` | `true` | `0xd745eec5f10f...` | `exact_00004` | `near_04073` |
