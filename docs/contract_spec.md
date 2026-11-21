# Smart Contract Specification (`RiskAttestationRegistry` & Variants)

**Project:** X-SPIDE-G (`IS355 – Blockchain Technology · Group 4 – DICTATOR`)  
**Phase:** Phase 5 Specification (`v1.1` Hardening Update)  
**Version:** v1.1 (Aligned with [design_v2.md](design_v2.md), [threat_model.md](threat_model.md) & [implementation_plan_v1.1.md](implementation_plan_v1.1.md))  
**Compiler & Toolchain:** Vyper `^0.4.0` (verified on `0.4.3+commit.bff19ea2`), `web3.py` + `eth-tester` (`PyEVMBackend`), `ape-config.yaml` (optional Anvil/Foundry RPC target)

---

## 1. Overview & Variant Matrix

X-SPIDE-G separates off-chain probabilistic Ponzi risk scoring (LightGBM + SHAP) from on-chain cryptographic provenance and multi-auditor quorum attestation. Three Vyper `0.4.x` contract variants implement the same `k-of-n` governance, quorum-snapshot isolation (`T13`), and immutability guarantees while varying on-chain storage footprint for Experiment `E5`:

| Variant | Contract File | Purpose | Stored State per Unit | Off-Chain Dependency |
|---|---|---|---|---|
| **`D1` (Primary)** | [`contracts/RiskAttestationRegistry.vy`](../contracts/RiskAttestationRegistry.vy) | Full on-chain storage baseline | Full `Case` struct (12 fields, incl. `required_threshold` & `created_roster_nonce`) + `Attestation` (3 fields) | Evidence JSON (`evidenceURI`) |
| **`D2`** | [`contracts/variants/D2_EventOnly.vy`](../contracts/variants/D2_EventOnly.vy) | Minimal storage variant | `CompactCase` (`exists`, `evidence_hash`, tally counters, `status`, `required_threshold`, `created_roster_nonce`) + `CompactAttestation` (`decision`, `revision`) | Event indexer + Evidence JSON |
| **`D3`** | [`contracts/variants/D3_MerkleBatch.vy`](../contracts/variants/D3_MerkleBatch.vy) | Merkle-batch amortized variant | `Batch` keyed by `root` (incl. `required_threshold`, `created_roster_nonce`) + batch-level `Attestation` | Merkle tree leaves/proofs + Batch URI |

---

## 2. Governance, Role Separation & Immutability

1. **Strict Role Disjointness:**
   - `owner` manages the authorized auditor roster (`add_auditor`, `remove_auditor`) and global quorum threshold (`set_threshold`) for **future** cases/batches.
   - `owner` **cannot** be an auditor (`add_auditor(owner)` reverts with `"Owner cannot be auditor"`), and `owner` has **no** write path to `register_case`, `attest`, `register_batch`, or `attest_batch`.
2. **Zero Admin Override (Append-Only History) & Enforced `v1.1` Quorum Isolation (`T13`):**
   - There are **zero functions** allowing `owner` (or any auditor) to edit, overwrite, or delete registered cases, batches, `evidence_hash`, `model_version_hash`, or finalized verdicts (`STATUS_APPROVED` / `STATUS_REJECTED`).
   - **Per-Case / Per-Batch Threshold Snapshotting:** `register_case` / `register_batch` freezes `required_threshold = self.threshold`, so subsequent `set_threshold(k)` calls affect only newly registered cases/batches and cannot retroactively lower quorum on already-open cases.
   - **Sybil Roster-Nonce Isolation:** Every `add_auditor` call monotonically increments `roster_nonce` and stamps `auditor_added_at[a] = roster_nonce`. Cases/batches snapshot `created_roster_nonce = self.roster_nonce`, and `attest` / `attest_batch` enforces `auditor_added_at[msg.sender] <= created_roster_nonce`, blocking auditors added after case creation from voting on pre-existing cases.
   - **Tie-Safe Consensus & Permissionless Non-Finalized Vote Revocation:** `_compute_status` explicitly maps any simultaneous tie (`approve_count >= required_threshold and reject_count >= required_threshold`) to `STATUS_DISPUTED` (`3`). Removing an auditor (`remove_auditor`) prevents future attestations while keeping their historical vote intact by default; for **non-finalized** cases/batches (`STATUS_OPEN` or `STATUS_DISPUTED`), any caller may invoke `revoke_removed_auditor_vote` to zero out a removed auditor's tally and recompute status (while finalized `Approved`/`Rejected` records revert with `"Case already finalized"` / `"Batch already finalized"`).
3. **Deployment Ownership (`initial_owner`):**
   - `__init__(initial_owner: address)` sets `self.owner = initial_owner` (or `msg.sender` if `empty(address)` is supplied), and initializes `self.threshold = 2` (emitting `ThresholdChanged(0, 2)`).
   - On Ethereum Sepolia and Arbitrum Sepolia, production deployments should use a **Safe multisig + timelock** as `initial_owner` to govern future auditor additions and thresholds. Under testnet demo constraints, an EOA deployer/owner is explicitly documented as `owner_type = "eoa_demo_limit"` in `deployments.json` and reports per [threat_model.md](threat_model.md).
4. **Minimal Attack Surface:**
   - No `@payable` functions and no `__default__` fallback (contract rejects ETH transfers).
   - No `raw_call`, no `delegatecall`, no `selfdestruct`, and `evidence_uri` / `batch_uri` are strictly bounded to `String[128]`.

---

## 3. State Specification (`D1`: `RiskAttestationRegistry`)

### 3.1. State Variables

| Variable | Vyper Type | Visibility | Notes |
|---|---|---|---|
| `owner` | `address` | `public` | Multisig on production; governance only |
| `is_auditor` | `HashMap[address, bool]` | `public` | Active auditor authorization table |
| `auditor_count` | `uint256` | `public` | Number of currently active auditors |
| `threshold` | `uint256` | `public` | Global quorum $k$ for new cases; invariant $1 \le k \le \text{auditor\_count}$ once configured (default `2`) |
| `roster_nonce` | `uint256` | `public` | Monotonic counter incremented on every `add_auditor` call (`v1.1`) |
| `auditor_added_at` | `HashMap[address, uint256]` | `public` | Roster nonce at which an active auditor was added (`0` when inactive; `v1.1`) |
| `cases` | `HashMap[bytes32, Case]` | `public` | Case records keyed by deterministic `case_id` |
| `attestations` | `HashMap[bytes32, HashMap[address, Attestation]]` | `public` | Per-case, per-auditor latest attestation |

### 3.2. Structs

```vyper
struct Case:
    subject: address
    subject_chain_id: uint256
    evidence_hash: bytes32
    model_version_hash: bytes32
    registrant: address
    created_at: uint256
    approve_count: uint256
    reject_count: uint256
    review_count: uint256
    status: uint8
    required_threshold: uint256
    created_roster_nonce: uint256

struct Attestation:
    decision: uint8
    revision: uint256
    timestamp: uint256
```

### 3.3. Decision & Status State Machine

- **Decision codes (`uint8`):**
  - `0` (`DECISION_UNSET`): Auditor has not attested to this case (or vote was revoked after removal on a non-finalized case).
  - `1` (`DECISION_APPROVE`): Auditor concurs with the ML risk assessment.
  - `2` (`DECISION_REJECT`): Auditor rejects the ML risk assessment.
  - `3` (`DECISION_NEEDS_REVIEW`): Auditor flags the case for deeper review.

- **Case status recomputation (`_compute_status(approve_count, reject_count, required_threshold)`):** Recomputed deterministically on every `attest` / `attest_batch` and `revoke_removed_auditor_vote` using the case/batch's **snapshotted `required_threshold`**:
  1. If `approve_count >= required_threshold and reject_count >= required_threshold` → `3` (`STATUS_DISPUTED`) *(symmetric tie-safe rule)*
  2. Else if `approve_count >= required_threshold` → `1` (`STATUS_APPROVED`)
  3. Else if `reject_count >= required_threshold` → `2` (`STATUS_REJECTED`)
  4. Else if `approve_count >= 1 and reject_count >= 1` → `3` (`STATUS_DISPUTED`)
  5. Else → `0` (`STATUS_OPEN`)

> **Enforced On-Chain Invariant (`v1.1`, `T13`):** Unlike `v1.0` (which relied on governance discipline to avoid mid-case threshold changes, auditor rotation, or $k \le n/2$ tie precedence), `v1.1` enforces all four protections directly in Vyper bytecode: (1) `required_threshold` is snapshotted at creation, (2) `created_roster_nonce` prevents newly added auditors from voting on pre-existing cases, (3) ties where both `approve_count` and `reject_count` reach `required_threshold` always resolve symmetrically to `STATUS_DISPUTED`, and (4) `revoke_removed_auditor_vote` cleans up stale votes from removed auditors strictly on non-finalized (`Open`/`Disputed`) records.

---

## 4. Function Specifications (`D1` & `D2`)

| Function | Access | Behavior | Revert Conditions |
|---|---|---|---|
| `add_auditor(a: address)` | `owner` | Sets `is_auditor[a] = True`, increments `auditor_count` and `roster_nonce`, records `auditor_added_at[a] = roster_nonce`, emits `AuditorAdded` | Non-owner; `a == 0x0`; `a == owner`; already an auditor |
| `remove_auditor(a: address)` | `owner` | Sets `is_auditor[a] = False`, clears `auditor_added_at[a] = 0`, decrements `auditor_count`, preserves prior attestations, emits `AuditorRemoved` | Non-owner; `a` not an auditor; `auditor_count - 1 < threshold` |
| `set_threshold(k: uint256)` | `owner` | Updates global `threshold = k` (for **future** cases only), emits `ThresholdChanged(old, k)` | Non-owner; `k == 0`; `k > auditor_count` |
| `register_case(case_id, subject, subject_chain_id, evidence_hash, model_version_hash, evidence_uri)` | `auditor` | Stores new `Case` (`status = Open`, `required_threshold = self.threshold`, `created_roster_nonce = self.roster_nonce`), emits `CaseRegistered` (`evidence_uri` emitted only in event) | Non-auditor; `case_id == 0`; `subject == 0x0`; `evidence_hash == 0`; `model_version_hash == 0`; `case_id` already registered |
| `attest(case_id, decision, reason_hash)` | `auditor` | Checks `auditor_added_at[msg.sender] <= c.created_roster_nonce`; creates or replaces **caller's own** attestation; adjusts old/new tally counters; increments `revision`; updates `timestamp`; emits `Attested`; recomputes `status` against `c.required_threshold` and emits `StatusChanged` if changed | Non-auditor; case does not exist; auditor added after case creation; `decision ∉ {1, 2, 3}`; `decision == current_decision` |
| `revoke_removed_auditor_vote(case_id, auditor)` | public (permissionless) | Clears a removed auditor's vote on a **non-finalized** (`Open`/`Disputed`) case: decrements previous tally bucket, resets `decision = 0`, increments `revision`, updates `timestamp` (`D1`), emits `RemovedAuditorVoteRevoked`, recomputes `status`, emits `StatusChanged` if changed | Case does not exist; case already finalized (`Approved`/`Rejected`); auditor is still active; auditor has no vote (`decision == 0`) |
| `verify_evidence(case_id, h) -> bool` | `view` (public) | Returns `True` iff case exists and `evidence_hash == h` (returns `False` for unregistered cases even if `h == 0`) | Never reverts |
| `get_case(case_id)` | `view` (public) | Returns `Case` (`D1`) or `CompactCase` (`D2`) | Never reverts |
| `get_attestation(case_id, auditor)` | `view` (public) | Returns `Attestation` (`D1`) or `CompactAttestation` (`D2`) | Never reverts |

---

## 5. Event Specifications (Append-Only Ledger)

### 5.1. `D1` & `D2` Events
- `AuditorAdded(auditor: indexed(address))`
- `AuditorRemoved(auditor: indexed(address))`
- `ThresholdChanged(old_threshold: uint256, new_threshold: uint256)`
- `CaseRegistered(case_id: indexed(bytes32), subject: indexed(address), evidence_hash: bytes32, model_version_hash: bytes32, evidence_uri: String[128], registrant: address)`
- `Attested(case_id: indexed(bytes32), auditor: indexed(address), decision: uint8, revision: uint256, reason_hash: bytes32)`
- `StatusChanged(case_id: indexed(bytes32), old_status: uint8, new_status: uint8)`
- `RemovedAuditorVoteRevoked(case_id: indexed(bytes32), auditor: indexed(address), previous_decision: uint8, revision: uint256, caller: address)` *(added in `v1.1`)*

### 5.2. `D3` (`D3_MerkleBatch.vy`) Additions
- **Leaf construction:**
  $$\text{leaf} = \text{keccak256}\big(\text{abi.encode}(\text{case\_id},\, \text{evidence\_hash},\, \text{model\_version\_hash})\big)$$
  Exposed via `@pure def compute_leaf(case_id, evidence_hash, model_version_hash) -> bytes32`.
- **Merkle tree rule:** Balanced binary Merkle tree with **sorted-pair `keccak256`** internal hashing (`if uint256(a) <= uint256(b): keccak256(a || b) else keccak256(b || a)`) and odd-node promotion (no duplicate-leaf padding), compatible with OpenZeppelin `MerkleProof`.
- **Batch endpoints (`v1.1`):**
  - `register_batch(root: bytes32, n_leaves: uint256, batch_uri: String[128])` (`n_leaves > 0`, `root != 0`, non-duplicate; snapshots `required_threshold` and `created_roster_nonce`) → emits `BatchRegistered`
  - `attest_batch(root: bytes32, decision: uint8)` (enforces `"Auditor added after batch creation"` and tie-safe `_compute_status`) → emits `BatchAttested`, `BatchStatusChanged`
  - `revoke_removed_auditor_vote(root: bytes32, auditor: address)` (permissionless on non-finalized batches; reverts with `"Batch already finalized"`, `"Auditor is still active"`, or `"No vote to revoke"`) → emits `RemovedAuditorBatchVoteRevoked`, `BatchStatusChanged`
  - `verify_inclusion(leaf: bytes32, proof: DynArray[bytes32, 32], root: bytes32) -> bool` (`@view`) → returns `True` iff `root` is registered on-chain and `proof` reconstructs `root` from `leaf`.

---

## 6. Verification Suite (`T1`–`T13`)

All invariants are tested under `tests/contracts/` (`46` contract tests, `100%` explicit `assert` revert-branch coverage: `D1` `20/20`, `D2` `20/20`, `D3` `18/18`) against local EVM (`PyEVMBackend` via `eth-tester`, using `vyper 0.4.3` compiled artifacts) plus live Sepolia `T1`/`T6`/`T8`/`T13` proofs:

| ID | Test Target | Expected Outcome |
|---|---|---|
| `T1` | Non-auditor calls `register_case` / `attest` | Reverts (`"Only auditor"`) |
| `T2` | Duplicate `case_id` in `register_case` | Reverts (`"Case already exists"`) |
| `T3` | Invalid `decision` (`0`, `4`, `255`) in `attest` | Reverts (`"Invalid decision"`) |
| `T4` | Exhaustive quorum sequences (`k = 2, n = 3`) | `Open`, `Approved`, `Rejected`, `Disputed` match spec |
| `T5` | Attestation replacement by same auditor | `revision` increments; old/new counters & `status` update |
| `T6` | Owner attempts every case/attestation/admin misuse | Owner cannot alter/delete cases or attestations |
| `T7` | Removed auditor calls `attest` | Reverts; prior attestation & counters stay intact unless revoked on a non-finalized case |
| `T8` | `verify_evidence` on exact vs 1-byte tampered JSON | Exact → `True`; 1-byte tampered → `False` |
| `T9` | Event emission & parameter decoding | All event types emit exact arguments |
| `T10` | Invalid `set_threshold` (`0`, `> n`) and `remove_auditor` `< k` | All invalid transitions revert |
| `T11` | Hypothesis property/fuzz test over random operations (incl. `revoke_removed_auditor_vote`) | `approve + reject + review == non-zero attestations` and `status == py_compute_status(..., required_threshold)` |
| `T12` | `D3` Merkle leaf, valid/tampered/unregistered proofs | Valid → `True`; tampered leaf/proof/root → `False` |
| `T13` | `v1.1` Quorum isolation across `D1`, `D2`, `D3` (local + live Sepolia) | Snapshotted `required_threshold` ignores later `set_threshold`; post-creation Sybil auditor reverts (`"Auditor added after case/batch creation"`); tie yields `STATUS_DISPUTED`; `revoke_removed_auditor_vote` cleans non-finalized votes and reverts on finalized records |
