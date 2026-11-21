# Contract Verification & Coverage Report (`reports/contract_coverage.md` — v1.1)

- **Compiler:** Vyper `0.4.3+commit.bff19ea2` (`# pragma version ^0.4.0`)
- **EVM Test Backend:** `eth-tester 0.14.0b1` / `py-evm 0.12.1b1` (`EthereumTesterProvider`, Cancun hardfork rules)
- **Test Command:** `.\.venv\Scripts\python.exe -m pytest -v --cov=src/contracts --cov-report=term-missing tests/contracts/ tests/evidence/ tests/test_phase8_deliverables.py`
- **Verification Date (UTC):** `2026-11-21`

## 1. Test Suite Results (`T1`–`T13`)

- **Total Tests Executed:** `61 passed in 286.28s (0:04:46)` (`46` contract tests in `tests/contracts/`, `9` evidence & E2E tests in `tests/evidence/`, and `6` deliverable/secret-hygiene checks in `tests/test_phase8_deliverables.py`; `0` failed, `0` skipped)
- **Contract Test Modules (`46` tests):**
  - [`tests/contracts/test_registry_d1_d2.py`](../tests/contracts/test_registry_d1_d2.py): `T1`–`T10` parameterized across both `D1` (`RiskAttestationRegistry.vy`) and `D2` (`D2_EventOnly.vy`) (`20` tests), including exhaustive $3^3 = 27$ 3-auditor decision permutations for $k = 2, n = 3$ (`T4`) and finalized-case immutability checks (`T6`).
  - [`tests/contracts/test_fuzz_t11.py`](../tests/contracts/test_fuzz_t11.py): `T11` Hypothesis differential property/fuzz test (`25` random multi-actor operation traces including `revoke_removed_auditor_vote`) + deterministic per-case threshold snapshot isolation regression checking `D1` against [`src/contracts/reference.py`](../src/contracts/reference.py) (`2` tests).
  - [`tests/contracts/test_merkle_d3_t12.py`](../tests/contracts/test_merkle_d3_t12.py): `T12` Merkle leaf parity, batch sizes $N \in \{1, 5, 16, 100\}$, tampered/unregistered proofs, and `D3` quorum governance (`5` tests).
  - [`tests/contracts/test_quorum_isolation_t13.py`](../tests/contracts/test_quorum_isolation_t13.py): `T13` parameterized across `D1`, `D2`, and `D3` (`6` tests), verifying per-case/per-batch `required_threshold` snapshotting, `created_roster_nonce` Sybil roster isolation, symmetric tie-safe `STATUS_DISPUTED`, permissionless `revoke_removed_auditor_vote` across `Approve`/`Reject`/`NeedsReview` branches, and immutability of finalized verdicts.
  - [`tests/contracts/test_revert_branch_coverage.py`](../tests/contracts/test_revert_branch_coverage.py): Automated AST/source extraction and execution of every explicit `assert` revert guard across `D1`, `D2`, and `D3`, plus non-payable ETH rejection (`1` test).
  - [`tests/contracts/test_deploy_and_verify_scripts.py`](../tests/contracts/test_deploy_and_verify_scripts.py): `local-evm` deployment manifest validation, raw-signed EIP-1559/private-key tx path, and Etherscan v2 `vyper-json` verification payload/timeout checks (`3` tests).
  - [`tests/contracts/test_e5_benchmark.py`](../tests/contracts/test_e5_benchmark.py) & [`tests/contracts/test_phase7_outputs.py`](../tests/contracts/test_phase7_outputs.py): E5 PyEVM gas suite (including `remove_auditor` & `revoke_removed_auditor_vote`), latency summary math, live Sepolia/Arbitrum Sepolia `E5_gas.csv`/`E5_latency.csv`/`E5_summary.json` (`T1`, `T6`, `T8`, `T13`), vector PDF figure, and secret hygiene checks (`6` tests).
  - [`tests/contracts/test_contract_utils.py`](../tests/contracts/test_contract_utils.py): Artifact loader, Merkle tree boundary checks, and Python reference boundary tests (`3` tests).

## 2. Vyper Revert-Branch Coverage (`v1.1`)

| Contract | Source File | Explicit `assert` Revert Guards | Exercised & Verified | Non-Payable ETH Rejection |
|---|---|---:|---:|---:|
| **`D1`** | [`contracts/RiskAttestationRegistry.vy`](../contracts/RiskAttestationRegistry.vy) | 20 | **20 / 20 (100%)** | Verified (`T6`) |
| **`D2`** | [`contracts/variants/D2_EventOnly.vy`](../contracts/variants/D2_EventOnly.vy) | 20 | **20 / 20 (100%)** | Verified (`T6`) |
| **`D3`** | [`contracts/variants/D3_MerkleBatch.vy`](../contracts/variants/D3_MerkleBatch.vy) | 18 | **18 / 18 (100%)** | Verified |

*New `v1.1` revert guards verified at 100% coverage:* `"Auditor added after case creation"` (`D1`/`D2`) / `"Auditor added after batch creation"` (`D3`), `"Case already finalized"` (`D1`/`D2`) / `"Batch already finalized"` (`D3`), `"Auditor is still active"`, and `"No vote to revoke"`.

## 3. Python Contract Helper Coverage (`src/contracts/`)

| Module | Statements | Missed | Coverage |
|---|---:|---:|---:|
| `src/contracts/__init__.py` | 4 | 0 | 100% |
| `src/contracts/compiler.py` | 76 | 28 | 63% |
| `src/contracts/e5_benchmark.py` | 268 | 73 | 73% |
| `src/contracts/merkle.py` | 58 | 2 | 97% |
| `src/contracts/reference.py` | 143 | 20 | 86% |
| **Total (`src/contracts/`)** | **549** | **123** | **78%** |

> **Deployment & Environment Note (`v1.1`, Option 4B Live Redeploy):** [`deployments.json`](../deployments.json) records verified `v1.1` deployments (each configured with 3 auditors and `threshold = 2`) across all four targets:
> - `local-evm` (`PyEVMBackend` deterministic check + `D1` end-to-end smoke check, `total_finalization_gas = 482,652`): `D1`, `D2`, `D3`.
> - `anvil` (`chain_id = 31337`, served via the local `PyEVMBackend` JSON-RPC bridge because native `anvil.exe` is blocked by Windows Application Control policy): `D1` (`0x5FbDB2315678afecb367f032d93F642f64180aa3`), `D2` (`0x5FC8d32690cc91D4c39d9d3abcBD16989F875707`), `D3` (`0x610178dA211FEF7D417bC0e6FeD39F05609AD788`).
> - `sepolia` (`chain_id = 11155111`, EOA owner `0x950e0416b13153d542d07Bf7f9AB586B0e903465`, `owner_type = "eoa_demo_limit"`): `D1` (`0x9E01ed5Aa19f0758d8dEc7C461dc374AcDA52Fad`), `D2` (`0x33f7f3369A7b1fe3326032FeEbbdE873bD1E3f24`), and `D3` (`0xe71C0468c32bC8ae555624b07e4B3CFDE3fb88e0`), all `"Pass - Verified"` on Etherscan v2 via [`scripts/verify_contracts.py`](../scripts/verify_contracts.py).
> - `arbitrum-sepolia` (`chain_id = 421614`, EOA owner `0x950e0416b13153d542d07Bf7f9AB586B0e903465`, `owner_type = "eoa_demo_limit"`): `D1` (`0x8D757ED6419C30117c497a921ee6b685995C96B7`) and `D3` (`0x93C99e7F0fe273fa9d9e45f43D4d24Fc8C6c70Ee`), both `"Pass - Verified"` on Etherscan v2 (`chainid=421614` / Arbiscan Sepolia) via [`scripts/verify_contracts.py`](../scripts/verify_contracts.py).
