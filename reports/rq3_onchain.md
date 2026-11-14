# RQ3 Report: On-Chain Evaluation & Architectural Trade-Offs (Phase 7 / Experiment E5)

**Project:** X-SPIDE-G — Blockchain-Backed Auditable Explainable AI Governance for Financial Fraud & Default Risk  
**Experiment ID:** E5 (`scripts/run_phase7_e5.py`, `src/contracts/e5_benchmark.py`)  
**Evaluation Timestamp (UTC):** `2026-11-14T09:48:30Z`  
**Git Commit at Benchmark Execution:** `71436e075f040a670c5d0b02fe71c926bcd80aea`  
**Artifact Links:**  
- Gas & Cost Dataset: [`results/E5_gas.csv`](../results/E5_gas.csv)  
- Latency Dataset: [`results/E5_latency.csv`](../results/E5_latency.csv)  
- Execution Manifest & Proof Index: [`results/E5_summary.json`](../results/E5_summary.json)  
- Gas Scaling Curve: [`figures/gas_vs_batch.png`](../figures/gas_vs_batch.png)

---

## 1. Executive Verdict Against Pre-Registered E5 Thresholds

Every pre-registered acceptance threshold defined in [`docs/preregistration.md`](../docs/preregistration.md) (§5) is evaluated honestly below using deterministic Cancun-equivalent `Anvil` (`PyEVMBackend`), live Ethereum Sepolia (`11155111`), and live Arbitrum Sepolia (`421614`) measurements.

| Pre-Registered Criterion | Target | Measured Result | Verdict |
| --- | --- | --- | --- |
| **D1 Finalized Case Gas** (`register_case + 2 attest`, $k=2$) | $\le 250{,}000$ gas/case | **Anvil (Cancun):** `427,461` gas (`+70.98%` over ceiling)<br>**Arbitrum Sepolia (live):** `427,473` gas<br>**Sepolia (live EIP-8037):** `1,648,029` gas | **FAIL** |
| **D3 Amortized Case Gas** ($N \ge 100$, Merkle batch finalized) | $\le 10{,}000$ gas/case | **Anvil $N=100$:** `3,574.53` gas/case (`-64.25%` below ceiling)<br>**Anvil $N=1000$:** `357.46` gas/case (`-96.43%`)<br>**Arbitrum Sepolia $N=100$:** `3,574.53` gas/case<br>**Sepolia (live EIP-8037) $N=100$:** `13,142.73` gas/case *(passes ceiling at $N \ge 132$, e.g., $N=1000 \approx 1{,}314$)* | **PASS** *(Cancun / Arbitrum Sepolia)*;<br>**Conditional** *(Sepolia EIP-8037 requires $N \ge 132$)* |
| **Sepolia Confirmation Latency** (`attest`, $n=30$ sequential txs) | Median $\le 2$ blocks | **Sepolia ($n=30$):** Median `1.00` block (`p95 = 1.00`, `min = 1`, `max = 1`); Median `10.357 s` (`p95 = 11.217 s`) | **PASS** |
| **Mainnet Baseline USD Reference Anchoring** | Logged fixed-date calculation | `0.084427 gwei` median gas price (Mainnet blocks `26412234..26412333`), `ETH = $1,900.68` (`2026-11-14T09:30:11Z`) | **PASS** *(Logged & Verified)* |

**Core RQ3 Finding:** Single-case full-storage governance (`D1`) inherently cannot meet a `250,000` gas/case ceiling under 2-of-3 quorum because three cold `SSTORE`-heavy state transitions (`register_case` + 2 `attest` calls) consume `427,461` gas on standard Cancun EVM (and `1,648,029` gas on state-repriced Sepolia EIP-8037). Switching to event-only storage (`D2`) trims Cancun finalized case gas by **31.06%** (`294,706` gas) and EIP-8037 gas by **40.08%** (`987,566` gas), still above `250,000`. Only Merkle batch anchoring (`D3`) satisfies the $\le 10{,}000$ gas/case budget on Cancun/Arbitrum (`3,574.53` gas/case at $N=100$, a **119.59×** / **99.16%** reduction vs `D1`; `357.46` gas/case at $N=1000$, a **1,195.83×** / **99.92%** reduction) while keeping Sepolia confirmation latency at a deterministic `1.00` block (`10.357 s` median) and Arbitrum Sepolia latency at `1.226 s` median.

---

## 2. Deterministic Gas & Batch Scaling Analysis (`Anvil / PyEVMBackend`)

Local Windows App Control restricts native `anvil.exe`, so deterministic EVM execution used `eth-tester` `PyEVMBackend` (Cancun hardfork rules) seeded identically across `D1` (`RiskAttestationRegistry.vy`), `D2` (`D2_EventOnly.vy`), and `D3` (`D3_MerkleBatch.vy`). Cold first-write calls and warm replacement updates are strictly separated.

### 2.1 Deployment & Governance Setup Gas (Cancun vs. Sepolia EIP-8037 vs. Arbitrum Sepolia)

| Operation | Storage Mode | Anvil (Cancun) | Arbitrum Sepolia | Sepolia (EIP-8037) |
| --- | --- | ---: | ---: | ---: |
| `D1 deploy` | Contract creation | `1,068,183` | `1,068,183` | `7,365,849` |
| `D2 deploy` | Contract creation | `1,057,392` | — | `7,288,546` |
| `D3 deploy` | Contract creation | `1,139,153` | `1,139,153` | `7,871,789` |
| `add_auditor` #1 | `cold_first_write` | `69,429` | `69,429` | `239,469` |
| `add_auditor` #2 / #3 | `cold_mapping_warm_count` | `52,317` / `52,329` | `52,329` / `52,329` | `141,549` / `141,549` |
| `set_threshold(2)` | `warm_update` | `29,165` | `29,165` | `23,165` |
| `remove_auditor` (a3 removal) | `warm_update` | `32,542` (`D1/D2/D3`) | — | — |

> [!NOTE]
> **Glamsterdam / EIP-8037 State-Creation Repricing on Sepolia:** Ethereum Sepolia activated the Glamsterdam upgrade (including EIP-8037 state-creation gas repricing) on October 6, 2026. Creating new contract bytecode or allocating zero-to-non-zero storage slots incurs **~3.35×–6.90×** higher gas on Sepolia than on Cancun (`PyEVMBackend`) or Arbitrum Sepolia Nitro, whereas warm non-zero storage overwrites such as `set_threshold(2)` are slightly cheaper (`23,165` vs `29,165`). This strengthens the architectural motivation for `D2` and `D3` under future L1 state-gas repricing.

### 2.2 Per-Case Lifecycle Gas Breakdown (`D1` vs. `D2` vs. `D3`, $k = 2$ of $3$)

| Variant | Operation | Mode | Anvil (Cancun) | Arbitrum Sepolia | Sepolia (EIP-8037) |
| --- | --- | --- | ---: | ---: | ---: |
| **D1** | `register_case` | `cold_first_write` | `172,554` | `172,566` | `693,762` |
| **D1** | `attest` #1 (`Open -> Open`) | `cold_first_write` | `125,212` | `125,212` | `471,292` |
| **D1** | `attest` #2 (`Open -> Approved`) | `cold_first_write` | `129,695` | `129,695` | `482,975` |
| **D1** | **`finalized_case_total`** | **`aggregate` ($k=2$)** | **`427,461`** | **`427,473`** | **`1,648,029`** |
| **D1** | `attest` #3 (extra vote) | `cold_first_write` | `125,087` | — | — |
| **D1** | `attest_warm_replace` | `warm_update` | `64,559` | `81,719` | `199,739` |
| **D2** | `register_case` | `cold_first_write` | `84,085` | — | `253,625` |
| **D2** | `attest` #1 (`Open -> Open`) | `cold_first_write` | `103,069` | — | `361,129` |
| **D2** | `attest` #2 (`Open -> Approved`) | `cold_first_write` | `107,552` | — | `372,812` |
| **D2** | **`finalized_case_total`** | **`aggregate` ($k=2$)** | **`294,706`** | — | **`987,566`** |
| **D2** | `attest_warm_replace` | `warm_update` | `59,516` | — | `187,496` |
| **D3 ($N=100$)** | `register_batch` | `cold_first_write` | `104,106` (`1,041.06`/case) | `104,106` (`1,041.06`/case) | `361,566` (`3,615.66`/case) |
| **D3 ($N=100$)** | `attest_batch` #1 | `cold_first_write` | `124,432` (`1,244.32`/case) | `124,432` (`1,244.32`/case) | `470,512` (`4,705.12`/case) |
| **D3 ($N=100$)** | `attest_batch` #2 | `cold_first_write` | `128,915` (`1,289.15`/case) | `128,915` (`1,289.15`/case) | `482,195` (`4,821.95`/case) |
| **D3 ($N=100$)** | **`batch_finalized_total`** | **`aggregate` ($k=2$)** | **`357,453` (`3,574.53`/case)** | **`357,453` (`3,574.53`/case)** | **`1,314,273` (`13,142.73`/case)** |

*Minor `12–24` gas variations across identical Cancun calls (e.g., `172,554` vs. `172,566` on `register_case`) reflect zero vs. non-zero bytes in random `bytes32` digests (`4` vs. `16` calldata gas per byte). On Sepolia and Arbitrum Sepolia spot-checks, `attest_warm_replace` wrote `disputed_at` for the first time (`Approved -> Disputed`), incurring one additional slot write compared to the Anvil sequence where the 3rd cold auditor had already finalized or changed state before replacement.*

### 2.3 Merkle Batch Scaling Curve (`D3` across $N \in \{1, 10, 100, 1000\}$)

![E5 Gas Scaling Curve](../figures/gas_vs_batch.png)

| Batch Size $N$ | `register_batch` | `attest_batch` #1 | `attest_batch` #2 | Total Batch Gas | Amortized Gas / Case | `attest_warm_replace` | `verify_inclusion` `estGas` (Proof Len) | `verify_case_inclusion` `estGas` |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **1** | `104,106` | `124,432` | `128,915` | `357,453` | `357,453.00` | `80,939` | `36,993` (`len=0`) | `38,004` |
| **10** | `104,094` | `124,420` | `128,903` | `357,417` | `35,741.70` | `80,927` | `39,040` (`len=4`) | `40,051` |
| **100** | `104,106` | `124,432` | `128,915` | `357,453` | **`3,574.53`** | `80,939` | `40,551` (`len=7`) | `41,563` |
| **1000** | `104,118` | `124,432` | `128,915` | `357,465` | **`357.46`** | `80,939` | `42,110` (`len=10`) | `43,134` |

On-chain write gas stays completely flat at **`~357,453` gas per batch** ($O(1)$) regardless of batch size $N$, while off-chain read verification via `verify_inclusion` scales logarithmically ($O(\log_2 N)$) from `36,993` to `42,110` estimated gas (`0` RPC transaction fee as a pure `eth_call`).

---

## 3. Fixed-Date Ethereum Mainnet USD Cost & Arbitrum Sepolia Fee Receipts

### 3.1 Mainnet Reference Anchor (Logged `2026-11-14T09:30:11Z`)

- **Mainnet Block Window:** `26412234..26412333` (100 blocks via `https://ethereum-rpc.publicnode.com` `eth_feeHistory`, p50 priority)
- **Median Base Fee:** `0.071787 gwei` | **Median Priority Fee:** `0.010000 gwei`
- **Median Total Gas Price:** **`0.084427 gwei`** *(cross-check: Etherscan v2 GasOracle `ProposeGasPrice` = `0.077298 gwei`)*
- **ETH / USD Spot Rate:** **`$1,900.68`** *(Source: Etherscan v2 `stats.ethprice`)*
- **Formula:** $\text{USD}_{\text{ref}} = \text{gas\_used} \times 0.084427 \times 10^{-9} \times 1{,}900.68$

### 3.2 Mainnet Reference Cost & Gas-Price Sensitivity (Cancun Baseline)

Using deterministic Cancun `PyEVMBackend` gas counts per finalized case ($k=2$), per-case costs across calm (`0.0844 gwei`) to congested (`30 gwei`) L1 conditions are:

| Variant | Gas / Finalized Case | `@ 0.084427 gwei` (Observed Anchor) | `@ 1.0 gwei` | `@ 5.0 gwei` | `@ 15.0 gwei` | `@ 30.0 gwei` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **D1 (Full Storage)** | `427,461` | **$0.068594** | `$0.812467` | `$4.062333` | `$12.186999` | `$24.373997` |
| **D2 (Event-Only)** | `294,706` | **$0.047291** | `$0.560142` | `$2.800709` | `$8.402127` | `$16.804254` |
| **D3 ($N=100$)** | `3,574.53` | **$0.000574** | `$0.006794` | `$0.033970` | `$0.101911` | `$0.203821` |
| **D3 ($N=1000$)** | `357.46` | **$0.000057** | `$0.000679` | `$0.003397` | `$0.010191` | `$0.020383` |

*(If EIP-8037 state-gas repricing applies equally on L1 in the future, Sepolia spot-check ratios imply L1 USD figures would scale by **3.86×** for `D1`, **3.35×** for `D2`, and **3.68×** for `D3`, making `D1` at `30 gwei` cost ~`$93.98`/case vs. `D3 (N=1000)` at ~`$0.075`/case.)*

### 3.3 Actual Arbitrum Sepolia Fee Receipts (Testnet Reference-Only)

| Variant | Scope | Total L2 Gas | Effective L2 Gas Price | Actual ETH Fee | Actual Testnet Fee (USD `@ $1,900.68`) | Per-Case USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| **D1** | Finalized case (`reg + 2 att`) | `427,473` | `0.020000–0.020114 gwei` | `0.000008564245 ETH` | `$0.016278` | **`$0.016278`** |
| **D3 ($N=100$)** | Finalized batch (`reg + 2 att`) | `357,453` | `0.020000–0.020142 gwei` | `0.000007181118 ETH` | `$0.013649` | **`$0.000136`** |

> [!WARNING]
> **Testnet Fee Caveat:** Arbitrum Sepolia receipt inspection (`gasUsedForL1 = 0x0`, `effectiveGasPrice ≈ 0.020 gwei`) confirms that testnet Nitro receipts currently charge negligible L1 data-posting fees due to minimal Sepolia blob/basefee pricing and subsidized testnet conditions. These USD numbers are **strictly reference-only** and must not be extrapolated directly to Arbitrum One mainnet under active L1 blob contention.

---

## 4. Sequential `attest` Confirmation Latency ($n = 30$ per Chain)

Thirty sequential `D1.attest(...)` transactions (`15` `cold_first_write` calls across 5 fresh cases, followed by `15` `warm_update` overrides toggling decision `1 -> 3`) were submitted on both live testnets from in-memory ephemeral benchmark auditor keys and confirmed to 1 inclusion block.

### 4.1 Overall Latency & Gas Distribution ($n = 30$ per Network)

| Network | $n$ | Median Latency (s) | p95 Latency (s) | Min / Max (s) | Median Blocks | p95 Blocks | Min / Max Blocks | Total Fee (ETH / USD) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| **Sepolia (`11155111`)** | `30` | **`10.357`** | **`11.217`** | `8.884 / 11.743` | **`1.00`** | **`1.00`** | `1 / 1` | `0.00422413 ETH` / `$8.0287` *(priority tip `0.50 gwei`)* |
| **Arbitrum Sepolia (`421614`)** | `30` | **`1.226`** | **`1.675`** | `1.022 / 1.699` | **`4.00`** | **`5.55`** | `3 / 6` | `0.00005618 ETH` / `$0.1068` |

*Target Check:* Sepolia achieved **`1.00` block** median (`100%` of transactions confirmed in the very next block, beating the pre-registered $\le 2$ blocks threshold). Arbitrum Sepolia confirms in **`1.226 s` median** (`3–6` fast ~250 ms L2 blocks including JSON-RPC polling RTT).

### 4.2 Cold vs. Warm Separation Within the Latency Sweep ($n=15$ each)

| Network | Write Mode | $n$ | Gas Range (`min..max`, `median`) | Median Latency (s) | Median Blocks |
| --- | --- | ---: | --- | ---: | ---: |
| **Sepolia (`11155111`)** | `cold_first_write` | `15` | `373,195 .. 482,975` *(med `471,292`)* | `10.379` | `1.0` |
| **Sepolia (`11155111`)** | `warm_update` | `15` | `80,321 .. 189,683` *(med `92,184`)* | `10.354` | `1.0` |
| **Arbitrum Sepolia (`421614`)** | `cold_first_write` | `15` | `107,923 .. 129,695` *(med `125,212`)* | `1.170` | `4.0` |
| **Arbitrum Sepolia (`421614`)** | `warm_update` | `15` | `57,125 .. 78,863` *(med `61,800`)* | `1.570` | `5.0` |

*Gas pattern note:* On `warm_update`, the first auditor replacing `Approve -> Reject` flips the case status `Approved -> Disputed` and writes `disputed_at` from `0 -> timestamp`, creating a higher gas tier (`189,683` on Sepolia EIP-8037; `78,851–78,863` on Arbitrum Sepolia) than the 2nd (`92,184` / `61,788–61,800`) and 3rd (`80,321` / `57,125–57,137`) warm overrides.

---

## 5. Live Security & Integrity Verification on Sepolia (`T1`, `T6`, `T8`)

In addition to the offline automated contract suite (`T1–T12`, 100% revert branch coverage), core role-isolation (`T1`, `T6`) and canonical payload integrity (`T8`) assertions were executed directly on live Sepolia:

1. **`T1` Non-Auditor Access Rejection (on main verified Sepolia `D1` `0x14895F5e1f7F1aC5C58b35dA6d57674Aa5951b77`):**
   - Sender: Ephemeral non-auditor `0xACbbF512AFEb817634178Ec4293518d108a6FF9b`
   - `register_case(...)`: On-chain revert `status = 0`, block `12132229`, gas `31,640`, revert message `"Only auditor"`, tx [`0x0ff94b4e0f5076059937b331ba6fba7ed8301a034fa78c05d6f32abcb945bb19`](https://sepolia.etherscan.io/tx/0x0ff94b4e0f5076059937b331ba6fba7ed8301a034fa78c05d6f32abcb945bb19)
   - `attest(...)`: On-chain revert `status = 0`, block `12132230`, gas `21,400`, revert message `"Only auditor"`, tx [`0x6c5b7e5e36187ffc7438839143248b3b67327e5338dece3a7df951abebfee4dc`](https://sepolia.etherscan.io/tx/0x6c5b7e5e36187ffc7438839143248b3b67327e5338dece3a7df951abebfee4dc)
2. **`T6` Owner Separation-of-Duties Enforcement (on main verified Sepolia `D1` `0x14895F5e1f7F1aC5C58b35dA6d57674Aa5951b77`):**
   - Sender: Deployed contract owner `0x950e0416b13153d542d07Bf7f9AB586B0e903465`
   - `register_case(...)`: On-chain revert `status = 0`, block `12132227`, gas `31,640`, revert message `"Only auditor"`, tx [`0xddd44781373cadd0568a4bdd5067a8a877a2bee3b4175b150b463e85a96c8bea`](https://sepolia.etherscan.io/tx/0xddd44781373cadd0568a4bdd5067a8a877a2bee3b4175b150b463e85a96c8bea)
   - `attest(...)`: On-chain revert `status = 0`, block `12132406`, gas `21,400`, revert message `"Only auditor"`, tx [`0x56764e897eec218d260f2208723495421b1313de1ea858913f8e057c8c3e89bc`](https://sepolia.etherscan.io/tx/0x56764e897eec218d260f2208723495421b1313de1ea858913f8e057c8c3e89bc)
   - `add_auditor(owner)`: On-chain revert `status = 0`, block `12132228`, gas `18,090`, revert message `"Owner cannot be auditor"`, tx [`0xced0e6e75fa8d5f4330773e2129cc0024b21e111cd572c95b35ca4007d78a6ce`](https://sepolia.etherscan.io/tx/0xced0e6e75fa8d5f4330773e2129cc0024b21e111cd572c95b35ca4007d78a6ce)
   - **Main `D1` Non-Pollution Verification:** `state_unchanged_verified = true` (`auditor_count = 3`, `threshold = 2`, `CaseRegistered = 0` after all security checks).
3. **`T8` Canonical Evidence Integrity & 1-Byte Tamper Rejection (on Sepolia benchmark `D1` `0x277cFb96F25150a3506D1bC9C8E503D89Ab3d25f`):**
   - Registered case ID: `0x4f059ee606addf455d91f363dd2d2017e92b7bdcde58a7ca30730b3d8e053311`, register tx `0x9b1eb9e73eebf0dabed6ed48484927a5edc15ee138f2332c247d05fd73591191`
   - Exact canonical JSON `keccak256`: `0x8d13b1201fa73ff33261d0beebb571e2f2e3cef1a59f076504e8bc14952653f9` -> local canonical check `True`, on-chain `verify_evidence == True`.
   - 1-byte perturbed `score` JSON `keccak256`: `0xc82b12805f4ee81c7379915ee746d21c977b42b34ae2b607c959ce21427b9607` -> local canonical check `False`, on-chain `verify_evidence == False`.
4. **`D3` Live Merkle Inclusion Proof Check:** Both Sepolia (`D3` `0x02e5AC648C34A3890687160E923A94A58Ee7e025`) and Arbitrum Sepolia (`D3` `0x5452460fC11fDD9Ca4E36513f0465B5eE969c96d`) verified `verify_inclusion(leaves[0], proof0, root) == True` on finalized `N = 100` batches.

---

## 6. Architectural Trade-Off Matrix (`D1` vs. `D2` vs. `D3`)

| Dimension | `D1` (`RiskAttestationRegistry.vy`) | `D2` (`D2_EventOnly.vy`) | `D3` (`D3_MerkleBatch.vy`) |
| --- | --- | --- | --- |
| **Storage Strategy** | Full per-case & per-auditor structs in contract storage (`cases`, `attestations`) | Compact counter/status struct in storage; `evidenceHash`, `modelHash`, `uri`, vote notes in events only | Batch root + compact consensus struct (`batches`, `batch_attestations`) |
| **Gas / Finalized Case (Cancun / L2)** | `427,461` (`deploy: 1,068,183`) | `294,706` (`-31.06%`, `deploy: 1,057,392`) | `357,453 / N` -> **`3,574.53`** at `N=100`, **`357.46`** at `N=1000` |
| **Gas / Finalized Case (Sepolia EIP-8037)** | `1,648,029` (`deploy: 7,365,849`) | `987,566` (`-40.08%`, `deploy: 7,288,546`) | `1,314,273 / N` -> **`13,142.73`** at `N=100`, `~1,314` at `N=1000` |
| **Direct On-Chain Queryability** | **Complete** (`get_case`, `get_attestation`, `verify_evidence`) | **Partial** (`get_case_state`, `verify_evidence` via hash match; history requires event log indexer) | **Batch + Proof-Based** (`verify_inclusion`, `verify_case_inclusion` require off-chain Merkle tree proofs) |
| **Latency / Finality** | Immediate per-case finality (`1.226 s` L2 / `10.357 s` L1 per tx) | Immediate per-case finality | Delayed by batch collection window + batch-level `k`-of-`m` sign-off |
| **Best Deployment Fit** | High-value / disputed Tier-1 credit or fraud escalations needing direct on-chain state | Moderate-volume deployments with dedicated Subgraph / log indexer | High-throughput daily institutional batch auditing (`10^2–10^3+` cases/day) |

**Recommended Hybrid Production Pattern:** Anchor routine scored transactions nightly/hourly in **`D3` Merkle batches** (`$0.000574`/case on L1 `@ 0.0844 gwei`, `$0.000136`/case on L2 testnet), while escalating contested or regulator-flagged cases directly into **`D1`** for granular per-case smart-contract inspection.

---

## 7. Qualitative Positioning vs. `ProvAuditChain` [4] *(Non-Head-to-Head)*

In published prior art, **`ProvAuditChain` [4]** reports **`~173,000` gas per audit cycle**, **`~$0.05` USD per cycle**, and **`~6 audits/min`** on Arbitrum Sepolia. Because the open-source contract bytecode, exact transaction sequence, and historical L1/L2 gas-price regime of [4] differ from X-SPIDE-G's `k`-of-`m` governance protocol, the comparison below is strictly **qualitative and non-head-to-head**:

- **Operation Granularity:** `ProvAuditChain`'s `~173,000` gas/cycle sits almost identically alongside a single X-SPIDE-G `D1.register_case` call (`172,554` gas Cancun / `172,566` Arbitrum Sepolia). However, X-SPIDE-G `D1` deliberately enforces cryptographic multi-party quorum ($k=2$ independent auditor signatures + owner/auditor separation), bringing total 3-transaction case finalization to `427,461` Cancun gas (`D2`: `294,706` gas).
- **Throughput & Cost Scaling:** Where single-record logging yields `~6 audits/min` (`~$0.05`/cycle in [4]), X-SPIDE-G sequential `attest` transactions average `1.226 s` on Arbitrum Sepolia (ceiling `~49 txs/min` sequentially, or `~16 finalized D1 cases/min` across 3 txs), while **`D3` Merkle batching amortizes cost by >119×** (`3,574.53` gas/case at $N=100$; `357.46` gas/case at $N=1000$, `$0.000136` actual Arbitrum Sepolia testnet fee/case at $N=100$).

---

## 8. Benchmark Traceability, Wallet Hygiene & Limitations

1. **Main Verified Phase 5 Contracts (`deployments.json`, untouched state):**
   - Sepolia `D1`: `0x14895F5e1f7F1aC5C58b35dA6d57674Aa5951b77` (`CaseRegistered = 0`, `auditors = 3`, `threshold = 2`, `owner_type = eoa_demo_limit`)
   - Arbitrum Sepolia `D1`: `0x14895F5e1f7F1aC5C58b35dA6d57674Aa5951b77`
2. **Dedicated E5 Live Benchmark Contracts (`results/E5_summary.json`):**
   - Sepolia: `D1 = 0x277cFb96F25150a3506D1bC9C8E503D89Ab3d25f`, `D2 = 0x8b25987043d4D6Dcb6BBd8BEC786Ae2c1aF3a7C0`, `D3 = 0x02e5AC648C34A3890687160E923A94A58Ee7e025`
   - Arbitrum Sepolia: `D1 = 0xf04fd7BD0Ee4DBf28d19D7D02988ac01fD989eF2`, `D3 = 0x5452460fC11fDD9Ca4E36513f0465B5eE969c96d`
3. **Ephemeral Auditor Keys & Sweep:** All benchmark auditors and non-auditor test keys were generated strictly in RAM, never saved to disk or logs, and remaining testnet balances were swept back to `0x950e0416b13153d542d07Bf7f9AB586B0e903465` (`0.01898826 ETH` remaining on Sepolia; `0.01980177 ETH` remaining on Arbitrum Sepolia).
4. **Governance & Environment Limitations:**
   - **EOA Owner (`eoa_demo_limit`):** The current owner is a single deployer EOA for testnet reproducibility; production rollout must transfer ownership to a multisig + timelock governance contract.
   - **Testnet Divergence:** Sepolia runs EIP-8037 state-gas repricing ahead of Mainnet/Arbitrum, and Arbitrum Sepolia charges near-zero `gasUsedForL1`. On-chain USD feasibility should therefore be judged from the anchored L1 sensitivity matrix (§3.2) rather than raw testnet ETH expenditure alone.
