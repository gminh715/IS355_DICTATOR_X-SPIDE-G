# Smart Contract Security Review (`RiskAttestationRegistry` & Variants)

**Project:** X-SPIDE-G (`IS355 – Blockchain Technology · Group 4 – DICTATOR`)  
**Phase:** Phase 5 Security Audit (`5.6`)  
**Scope:** `contracts/RiskAttestationRegistry.vy` (`D1`), `contracts/variants/D2_EventOnly.vy` (`D2`), `contracts/variants/D3_MerkleBatch.vy` (`D3`)  
**Compiler:** Vyper `0.4.3+commit.bff19ea2` (`# pragma version ^0.4.0`)

---

## 1. Security Checklist Verification

| Control Category | Implementation Detail | Status | Verification |
|---|---|---|---|
| **Access Control & Role Disjointness** | `_only_owner()` guards `add_auditor`, `remove_auditor`, `set_threshold`; `_only_auditor()` guards `register_case`, `attest`, `register_batch`, `attest_batch`. `add_auditor` enforces `a != self.owner`. | Pass | `T1`, `T6`, `T10` |
| **Zero Admin Override / Append-Only** | No function exists to edit, overwrite, or delete registered cases, batches, `evidence_hash`, `model_version_hash`, or past attestations. `remove_auditor` leaves historical attestations and tally counters untouched. | Pass | `T6`, `T7` |
| **Input Validation** | Rejects `empty(address)`, zero `case_id`, zero `evidence_hash`, zero `model_version_hash`, zero `root`, `n_leaves == 0`, duplicate `case_id`/`root`, invalid `decision ∉ {1,2,3}`, unchanged `decision`, `k == 0`, `k > auditor_count`, and `auditor_count - 1 < threshold`. | Pass | `T2`, `T3`, `T5`, `T10`, `T12` |
| **Arithmetic Safety** | Vyper `0.4.3` enforces checked unsigned arithmetic by default; `remove_auditor` checks `self.is_auditor[a]` before `self.auditor_count - 1`; counter decrements occur only when `prev.decision` matched the corresponding bucket. | Pass | `T5`, `T11` (Hypothesis fuzz) |
| **ETH / Reentrancy Safety** | Zero `@payable` endpoints and no `__default__` payable fallback; direct ETH transfers revert. Zero external `raw_call`, `delegatecall`, or ETH sends (no reentrancy surface). | Pass | `T6`, ABI inspection |
| **Dangerous Opcodes & Unbounded Loops** | Zero `selfdestruct`, zero `raw_call`. `evidence_uri` and `batch_uri` bounded to `String[128]`. Merkle proof array bounded to `DynArray[bytes32, 32]` (max depth 32, up to $2^{32}$ leaves). | Pass | Source audit + `T12` |
| **Unregistered Case Zero-Hash Guard** | `verify_evidence(case_id, h)` requires `registrant != empty(address)` (`D1`) or `exists == True` (`D2`), preventing false `True` when querying unknown cases with `h = 0x00..00`. `D3.verify_inclusion` rejects zero leaves and unregistered roots. | Pass | `T8`, `T12` |
| **Merkle Preimage Separation (`D3`)** | Leaf hashes encode 96 bytes (`abi_encode(case_id, evidence_hash, model_version_hash)`) while internal nodes hash 64 bytes (`concat(left, right)`), and `verify_case_inclusion` enforces leaf recomputation on-chain. | Pass | `T12` |

---

## 2. Static Analysis Tooling Note

- Vyper `0.4.3` compiled `D1`, `D2`, and `D3` cleanly with zero compiler warnings.
- Third-party Vyper `0.4.x` static analyzers (e.g., `slither` Vyper plugin) were not executed in this environment (`slither` is not installed and focuses primarily on Solidity ASTs / older Vyper IR); therefore, verification combines **manual line-by-line audit**, **ABI mutability inspection**, **exhaustive `k=2, n=3` sequence verification (`T4`)**, **all-revert-branch unit tests (`T1`–`T10`, `T12`)**, and **Hypothesis differential property fuzzing against the Python reference state machine (`T11`)**.

---

## 3. Residual Risks & Operational Mitigations

1. **Sepolia Owner Governance & Sybil/Rotation Scope (`owner_type`):** If deployed with an EOA `owner` under demo constraints (`eoa_demo_limit`), a compromised or malicious owner key cannot edit or delete historical cases/attestations or call `attest` directly from the `owner` address, but *could* add a Sybil wallet it controls (`add_auditor`) and/or lower `threshold` (`set_threshold(1)`), which affects any open or existing case when a subsequent `attest` call triggers `_compute_status`. In addition, because `remove_auditor` retains prior tally counts in `approve_count`/`reject_count` while `add_auditor` permits newly added auditors to vote on pre-existing cases, rotating auditors mid-case can allow total votes on a case to exceed the current `auditor_count`. Mitigation: deploy with a **Safe multisig + timelock** as `initial_owner`, enforce strict majority quorums ($k > n / 2$), and prohibit roster rotation while cases are open.
2. **Threshold & Tie Precedence Semantics:** Calling `set_threshold(k)` updates the global `self.threshold` used by future `attest` / `attest_batch` status recomputations (`O(1)` gas). Because `_compute_status` checks `if approve_count >= self.threshold` before `elif reject_count >= self.threshold`, setting $k \le n/2$ (or rotating auditors) could allow both counts to reach $k$ simultaneously and resolve to `STATUS_APPROVED` rather than `STATUS_DISPUTED`.
3. **Off-Chain Availability:** On-chain contracts store only cryptographic commitments (`evidence_hash`, `root`) and bounded URIs (`evidence_uri`, `batch_uri`). Verifiability depends on Phase 6 dual persistence (IPFS pin + Git `evidence/` mirror).
