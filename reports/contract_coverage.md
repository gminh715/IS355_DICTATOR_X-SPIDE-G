# Phase 5 Contract Verification & Coverage Report (`reports/contract_coverage.md`)

- **Compiler:** Vyper `0.4.3+commit.bff19ea2` (`# pragma version ^0.4.0`)
- **EVM Test Backend:** `eth-tester 0.14.0b1` / `py-evm 0.12.1b1` (`EthereumTesterProvider`)
- **Test Command:** `.\.venv\Scripts\python.exe -m pytest tests/contracts --cov=src/contracts --cov-report=term-missing -v`

## 1. Test Suite Results (`T1`–`T12`)

- **Total Contract Tests:** `33 passed in 117.07s` (`0` warnings, `0` skipped)
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
| `src/contracts/reference.py` | 112 | 7 | 94% |
| **Total (`src/contracts/`)** | **250** | **37** | **85%** |

> **Deployment & Environment Note (`5.7`):** Local `local-evm` (`PyEVMBackend`) deployment of `D1`/`D2`/`D3` with 3 auditors and `threshold = 2` is recorded in [`deployments.json`](../deployments.json). On this Windows host, native Foundry `anvil.exe` was blocked by Windows Application Control policy and Docker Desktop daemon is offline; live `Anvil`, `Sepolia`, and `L2 testnet` (`Arbitrum Sepolia` / `Base Sepolia`) deployments and Etherscan source verification remain pending user-supplied `.env` RPC URLs, funded testnet keys, and `ETHERSCAN_API_KEY` via [`scripts/deploy_contracts.py`](../scripts/deploy_contracts.py) and [`scripts/verify_contracts.py`](../scripts/verify_contracts.py).
