# Phase 5 Contract Verification & Coverage Report (`reports/contract_coverage.md`)

- **Compiler:** Vyper `0.4.3+commit.bff19ea2` (`# pragma version ^0.4.0`)
- **EVM Test Backend:** `eth-tester 0.14.0b1` / `py-evm 0.12.1b1` (`EthereumTesterProvider`)
- **Test Command:** `.\.venv\Scripts\python.exe -m pytest tests/contracts --cov=src/contracts --cov-report=term-missing -v`

## 1. Test Suite Results (`T1`–`T12`)

- **Total Contract Tests:** `33 passed in 151.62s` (`0` warnings, `0` skipped)
- **Test Modules:**
  - [`tests/contracts/test_registry_d1_d2.py`](../tests/contracts/test_registry_d1_d2.py): `T1`–`T10` parameterized across both `D1` (`RiskAttestationRegistry.vy`) and `D2` (`D2_EventOnly.vy`), including exhaustive $3^3 = 27$ 3-auditor decision permutations for $k = 2, n = 3$ (`T4`).
  - [`tests/contracts/test_fuzz_t11.py`](../tests/contracts/test_fuzz_t11.py): `T11` Hypothesis differential property/fuzz test (`25` random multi-actor operation traces) checking `D1` against [`src/contracts/reference.py`](../src/contracts/reference.py).
  - [`tests/contracts/test_merkle_d3_t12.py`](../tests/contracts/test_merkle_d3_t12.py): `T12` Merkle leaf parity, batch sizes $N \in \{1, 5, 16, 100\}$, tampered/unregistered proofs, and `D3` quorum governance.
  - [`tests/contracts/test_revert_branch_coverage.py`](../tests/contracts/test_revert_branch_coverage.py): Automated AST/source extraction and execution of every `assert` revert guard across `D1`, `D2`, and `D3`, plus non-payable ETH rejection.
  - [`tests/contracts/test_deploy_and_verify_scripts.py`](../tests/contracts/test_deploy_and_verify_scripts.py): `local-evm` deployment manifest validation, raw-signed EIP-1559/private-key tx path, and Etherscan v2 `vyper-json` verification payload/timeout checks.
  - [`tests/contracts/test_contract_utils.py`](../tests/contracts/test_contract_utils.py): Artifact loader, Merkle tree boundary checks, and Python reference boundaries.

## 2. Vyper Revert-Branch Coverage

| Contract | Source File | Explicit `assert` Revert Guards | Exercised & Verified | Non-Payable ETH Rejection |
|---|---|---:|---:|---:|
| **`D1`** | [`contracts/RiskAttestationRegistry.vy`](../contracts/RiskAttestationRegistry.vy) | 16 | **16 / 16 (100%)** | Verified (`T6`) |
| **`D2`** | [`contracts/variants/D2_EventOnly.vy`](../contracts/variants/D2_EventOnly.vy) | 16 | **16 / 16 (100%)** | Verified (`T6`) |
| **`D3`** | [`contracts/variants/D3_MerkleBatch.vy`](../contracts/variants/D3_MerkleBatch.vy) | 14 | **14 / 14 (100%)** | Verified |

## 3. Python Contract Helper Coverage (`src/contracts/`)

| Module | Statements | Missed | Coverage |
|---|---:|---:|---:|
| `src/contracts/__init__.py` | 4 | 0 | 100% |
| `src/contracts/compiler.py` | 76 | 28 | 63% |
| `src/contracts/merkle.py` | 58 | 2 | 97% |
| `src/contracts/reference.py` | 112 | 8 | 93% |
| **Total (`src/contracts/`)** | **250** | **38** | **85%** |

> **Deployment & Environment Note (`5.7`):** [`deployments.json`](../deployments.json) records verified deployments (each configured with 3 auditors and `threshold = 2`) across all four targets:
> - `local-evm` (`PyEVMBackend` deterministic check + `D1` end-to-end smoke check): `D1`, `D2`, `D3`.
> - `anvil` (`chain_id = 31337`, served via a local `PyEVMBackend` JSON-RPC bridge on `http://127.0.0.1:8545` because native `anvil.exe` is blocked by Windows Application Control policy and Docker Desktop daemon is offline): `D1`, `D2`, `D3`.
> - `sepolia` (`chain_id = 11155111`, EOA owner `0x950e0416b13153d542d07Bf7f9AB586B0e903465`, `owner_type = "eoa_demo_limit"`): `D1` (`0x14895F5e1f7F1aC5C58b35dA6d57674Aa5951b77`), `D2` (`0x693632c45108A9ca25a7F9d693c00554EeDD1EB1`), and `D3` (`0xf04fd7BD0Ee4DBf28d19D7D02988ac01fD989eF2`), all `"Pass - Verified"` on Etherscan v2 via [`scripts/verify_contracts.py`](../scripts/verify_contracts.py).
> - `arbitrum-sepolia` (`chain_id = 421614`, EOA owner `0x950e0416b13153d542d07Bf7f9AB586B0e903465`, `owner_type = "eoa_demo_limit"`): `D1` (`0x14895F5e1f7F1aC5C58b35dA6d57674Aa5951b77`) and `D3` (`0x693632c45108A9ca25a7F9d693c00554EeDD1EB1`), both `"Pass - Verified"` on Etherscan v2 (`chainid=421614` / Arbiscan Sepolia) via [`scripts/verify_contracts.py`](../scripts/verify_contracts.py).
