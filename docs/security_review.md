# Smart Contract Security Review (`RiskAttestationRegistry` & Variants)

**Project:** X-SPIDE-G (`IS355 – Blockchain Technology · Group 4 – DICTATOR`)  
**Phase:** Phase 5 Security Audit (`5.6`, updated `v1.1` on `2026-11-21`)  
**Scope:** `contracts/RiskAttestationRegistry.vy` (`D1`), `contracts/variants/D2_EventOnly.vy` (`D2`), `contracts/variants/D3_MerkleBatch.vy` (`D3`)  
**Compiler:** Vyper `0.4.3+commit.bff19ea2` (`# pragma version ^0.4.0`)

---

## 1. Security Checklist Verification

| Control Category | Implementation Detail | Status | Verification |
|---|---|---|---|
| **Access Control & Role Disjointness** | `_only_owner()` guards `add_auditor`, `remove_auditor`, `set_threshold`; `_only_auditor()` guards `register_case`, `attest`, `register_batch`, `attest_batch`. `add_auditor` enforces `a != self.owner`. | Pass | `T1`, `T6`, `T10` |
| **Zero Admin Override / Append-Only** | No function exists to edit, overwrite, or delete registered cases, batches, `evidence_hash`, `model_version_hash`, or finalized verdicts. `remove_auditor` leaves historical attestations intact; `revoke_removed_auditor_vote` is strictly restricted to non-finalized (`Open`/`Disputed`) records for already-removed auditors. | Pass | `T6`, `T7`, `T13` |
| **Quorum Snapshot, Sybil Isolation & Tie-Safety (`v1.1`)** | `register_case`/`register_batch` snapshot `required_threshold` and `created_roster_nonce`. `attest`/`attest_batch` enforce `auditor_added_at[msg.sender] <= created_roster_nonce`, evaluate consensus against `required_threshold`, and map simultaneous ties (`approve >= k and reject >= k`) symmetrically to `STATUS_DISPUTED`. | Pass | `T11`, `T13` (+ live Sepolia `T13`) |
| **Input Validation** | Rejects `empty(address)`, zero `case_id`, zero `evidence_hash`, zero `model_version_hash`, zero `root`, `n_leaves == 0`, duplicate `case_id`/`root`, invalid `decision ∉ {1,2,3}`, unchanged `decision`, `k == 0`, `k > auditor_count`, `auditor_count - 1 < threshold`, post-creation Sybil votes (`"Auditor added after case/batch creation"`), and invalid revocations (`"Case/Batch already finalized"`, `"Auditor is still active"`, `"No vote to revoke"`). | Pass | `T2`, `T3`, `T5`, `T10`, `T12`, `T13` |
| **Arithmetic Safety** | Vyper `0.4.3` enforces checked unsigned arithmetic by default; `remove_auditor` checks `self.is_auditor[a]` before `self.auditor_count - 1`; counter decrements occur only when `prev.decision` matched the corresponding bucket. | Pass | `T5`, `T11` (Hypothesis fuzz) |
| **ETH / Reentrancy Safety** | Zero `@payable` endpoints and no `__default__` payable fallback; direct ETH transfers revert. Zero external `raw_call`, `delegatecall`, or ETH sends (no reentrancy surface). | Pass | `T6`, ABI inspection |
| **Dangerous Opcodes & Unbounded Loops** | Zero `selfdestruct`, zero `raw_call`. `evidence_uri` and `batch_uri` bounded to `String[128]`. Merkle proof array bounded to `DynArray[bytes32, 32]` (max depth 32, up to $2^{32}$ leaves). | Pass | Source audit + `T12` |
| **Unregistered Case Zero-Hash Guard** | `verify_evidence(case_id, h)` requires `registrant != empty(address)` (`D1`) or `exists == True` (`D2`), preventing false `True` when querying unknown cases with `h = 0x00..00`. `D3.verify_inclusion` rejects zero leaves and unregistered roots. | Pass | `T8`, `T12` |
| **Merkle Preimage Separation (`D3`)** | Leaf hashes encode 96 bytes (`abi_encode(case_id, evidence_hash, model_version_hash)`) while internal nodes hash 64 bytes (`concat(left, right)`), and `verify_case_inclusion` enforces leaf recomputation on-chain. | Pass | `T12` |

---

## 2. Static Analysis Tooling Note

- Vyper `0.4.3` compiled `D1`, `D2`, and `D3` cleanly with zero compiler warnings.
- Third-party Vyper `0.4.x` static analyzers (e.g., `slither` Vyper plugin) were not executed in this environment (`slither` is not installed and focuses primarily on Solidity ASTs / older Vyper IR); therefore, verification combines **manual line-by-line audit**, **ABI mutability inspection**, **exhaustive `k=2, n=3` sequence verification (`T4`)**, **100% explicit `assert` revert-branch coverage (`D1` `20/20`, `D2` `20/20`, `D3` `18/18`) across `T1`–`T13` (`46` contract tests)**, **Hypothesis differential property fuzzing against the Python reference state machine (`T11`)**, and **live Sepolia `T1`/`T6`/`T8`/`T13` proofs**.

---

## 3. Enforced On-Chain Invariants Resolved in `v1.1` (`T13`)

Previously listed as `v1.0` residual governance risks, the following three classes of quorum attacks are now **enforced directly at the EVM bytecode level** across `D1`, `D2`, and `D3`:

1. **Mid-Case Threshold Manipulation (Resolved → Enforced On-Chain):** Each `Case`/`Batch` freezes `required_threshold = self.threshold` at registration. Calling `set_threshold(1)` cannot lower quorum on any already-open or finalized case/batch.
2. **Sybil Auditor Injection & Stale-Vote Accumulation on Open Cases (Resolved → Enforced On-Chain):** `add_auditor` increments `roster_nonce` and stamps `auditor_added_at[a]`; `attest`/`attest_batch` reject any auditor added after `created_roster_nonce` (`"Auditor added after case/batch creation"`, verified locally in `T13` and live on Sepolia tx `0x56d73080cfed7bb1...`). For non-finalized cases/batches (`Open`/`Disputed`), permissionless `revoke_removed_auditor_vote` cleans up stale votes from removed auditors (verified live on Sepolia tx `0xcdf735c325aa0ef7...`), while finalized `Approved`/`Rejected` verdicts remain permanently immutable.
3. **Asymmetric Tie Precedence (`k <= n/2`, Resolved → Enforced On-Chain):** `_compute_status` explicitly evaluates `approve_count >= required_threshold and reject_count >= required_threshold` first and returns `STATUS_DISPUTED` (`3`), eliminating approval bias on ties.

---

## 4. Remaining Residual Risks & Operational Mitigations

1. **EOA Owner Governance Scope for *Future* Cases (`owner_type = "eoa_demo_limit"`):** While `v1.1` (`T13`) isolates all existing and open cases from post-creation threshold drops and Sybil auditor injections, testnet deployments still use an EOA `owner` under demo constraints (`eoa_demo_limit`). A compromised EOA owner key could still modify the auditor roster or lower `threshold` for *future* newly created cases. Mitigation: migrate `initial_owner` to a **Safe multisig + timelock** in production.
2. **Off-Chain Data Availability:** On-chain contracts store only cryptographic commitments (`evidence_hash`, `root`) and bounded URIs (`evidence_uri`, `batch_uri`). Verifiability depends on Phase 6 dual persistence (IPFS pin + Git `evidence/` mirror).
