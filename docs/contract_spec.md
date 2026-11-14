# Smart Contract Specification (`RiskAttestationRegistry` & Variants)

**Project:** X-SPIDE-G (`IS355 – Blockchain Technology · Group 4 – DICTATOR`)  
**Phase:** Phase 5 Specification  
**Version:** v1.0 (Aligned with [design_v2.md](design_v2.md) & [threat_model.md](threat_model.md))  
**Compiler & Toolchain:** Vyper `^0.4.0` (verified on `0.4.3+commit.bff19ea2`), `web3.py` + `eth-tester` (`PyEVMBackend`), `ape-config.yaml` (optional Anvil/Foundry RPC target)

---

## 1. Overview & Variant Matrix

X-SPIDE-G separates off-chain probabilistic Ponzi risk scoring (LightGBM + SHAP) from on-chain cryptographic provenance and multi-auditor quorum attestation. Three Vyper `0.4.x` contract variants implement the same `k-of-n` governance and immutability guarantees while varying on-chain storage footprint for Experiment `E5`:

| Variant | Contract File | Purpose | Stored State per Unit | Off-Chain Dependency |
|---|---|---|---|---|
| **`D1` (Primary)** | [`contracts/RiskAttestationRegistry.vy`](../contracts/RiskAttestationRegistry.vy) | Full on-chain storage baseline | Full `Case` struct (10 fields) + `Attestation` (3 fields) | Evidence JSON (`evidenceURI`) |
| **`D2`** | [`contracts/variants/D2_EventOnly.vy`](../contracts/variants/D2_EventOnly.vy) | Minimal storage variant | `CompactCase` (`exists`, `evidence_hash`, tally counters, `status`) + `CompactAttestation` (`decision`, `revision`) | Event indexer + Evidence JSON |
| **`D3`** | [`contracts/variants/D3_MerkleBatch.vy`](../contracts/variants/D3_MerkleBatch.vy) | Merkle-batch amortized variant | `Batch` keyed by `root` + batch-level `Attestation` | Merkle tree leaves/proofs + Batch URI |

---

## 2. Governance, Role Separation & Immutability

1. **Strict Role Disjointness:**
   - `owner` manages the authorized auditor roster (`add_auditor`, `remove_auditor`) and quorum threshold (`set_threshold`).
   - `owner` **cannot** be an auditor (`add_auditor(owner)` reverts with `"Owner cannot be auditor"`), and `owner` has **no** write path to `register_case`, `attest`, `register_batch`, or `attest_batch`.
2. **Zero Admin Override (Append-Only History):**
   - There are **zero functions** allowing `owner` (or any auditor) to edit, overwrite, or delete registered cases, batches, `evidence_hash`, `model_version_hash`, or another auditor's attestation.
   - Removing an auditor (`remove_auditor`) prevents future calls from that wallet while preserving all historical attestations and tally contributions already recorded on-chain.
3. **Deployment Ownership (`initial_owner`):**
   - `__init__(initial_owner: address)` sets `self.owner = initial_owner` (or `msg.sender` if `empty(address)` is supplied), and initializes `self.threshold = 2` (emitting `ThresholdChanged(0, 2)`).
   - On Ethereum Sepolia, `initial_owner` should be a **Safe multisig** address. If an EOA deployer/owner is used under testnet constraints, that residual administrative key risk is explicitly documented in `deployments.json` and reports per [threat_model.md](threat_model.md).
4. **Minimal Attack Surface:**
   - No `@payable` functions and no `__default__` fallback (contract rejects ETH transfers).
   - No `raw_call`, no `delegatecall`, no `selfdestruct`, and `evidence_uri` / `batch_uri` are strictly bounded to `String[128]`.

---

## 3. State Specification (`D1`: `RiskAttestationRegistry`)

### 3.1. State Variables

| Variable | Vyper Type | Visibility | Notes |
|---|---|---|---|
| `owner` | `address` | `public` | Multisig on Sepolia; governance only |
| `is_auditor` | `HashMap[address, bool]` | `public` | Active auditor authorization table |
| `auditor_count` | `uint256` | `public` | Number of currently active auditors |
| `threshold` | `uint256` | `public` | Quorum $k$; invariant $1 \le k \le \text{auditor\_count}$ once configured (default `2`) |
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

struct Attestation:
    decision: uint8
    revision: uint256
    timestamp: uint256
```

### 3.3. Decision & Status State Machine

- **Decision codes (`uint8`):**
  - `0` (`DECISION_UNSET`): Auditor has not attested to this case.
  - `1` (`DECISION_APPROVE`): Auditor concurs with the ML risk assessment.
  - `2` (`DECISION_REJECT`): Auditor rejects the ML risk assessment.
  - `3` (`DECISION_NEEDS_REVIEW`): Auditor flags the case for deeper review.

- **Case status recomputation (`_compute_status`):** Recomputed deterministically on every `attest` (and `attest_batch` in `D3`):
  1. If `approve_count >= threshold` → `1` (`STATUS_APPROVED`)
  2. Else if `reject_count >= threshold` → `2` (`STATUS_REJECTED`)
  3. Else if `approve_count >= 1 and reject_count >= 1` → `3` (`STATUS_DISPUTED`)
  4. Else → `0` (`STATUS_OPEN`)

> Under standard majority quorums ($k > n / 2$, such as default $k = 2$ of $n = 3$), `approve_count >= threshold` and `reject_count >= threshold` are mutually exclusive. If an owner lowers `threshold` to $k = 1$ with $n \ge 2$, the precedence order above ensures deterministic evaluation matching the Python reference verifier.

---

## 4. Function Specifications (`D1` & `D2`)

| Function | Access | Behavior | Revert Conditions |
|---|---|---|---|
| `add_auditor(a: address)` | `owner` | Sets `is_auditor[a] = True`, increments `auditor_count`, emits `AuditorAdded` | Non-owner; `a == 0x0`; `a == owner`; already an auditor |
| `remove_auditor(a: address)` | `owner` | Sets `is_auditor[a] = False`, decrements `auditor_count`, preserves prior attestations, emits `AuditorRemoved` | Non-owner; `a` not an auditor; `auditor_count - 1 < threshold` |
| `set_threshold(k: uint256)` | `owner` | Updates `threshold = k`, emits `ThresholdChanged(old, k)` | Non-owner; `k == 0`; `k > auditor_count` |
| `register_case(case_id, subject, subject_chain_id, evidence_hash, model_version_hash, evidence_uri)` | `auditor` | Stores new `Case` (`status = Open`), emits `CaseRegistered` (`evidence_uri` emitted only in event) | Non-auditor; `case_id == 0`; `subject == 0x0`; `evidence_hash == 0`; `model_version_hash == 0`; `case_id` already registered |
| `attest(case_id, decision, reason_hash)` | `auditor` | Creates or replaces **caller's own** attestation; adjusts old/new tally counters; increments `revision`; updates `timestamp`; emits `Attested`; recomputes `status` and emits `StatusChanged` if changed | Non-auditor; case does not exist; `decision ∉ {1, 2, 3}`; `decision == current_decision` |
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

### 5.2. `D3` (`D3_MerkleBatch.vy`) Additions
- **Leaf construction:**
  $$\text{leaf} = \text{keccak256}\big(\text{abi.encode}(\text{case\_id},\, \text{evidence\_hash},\, \text{model\_version\_hash})\big)$$
  Exposed via `@pure def compute_leaf(case_id, evidence_hash, model_version_hash) -> bytes32`.
- **Merkle tree rule:** Balanced binary Merkle tree with **sorted-pair `keccak256`** internal hashing (`if uint256(a) <= uint256(b): keccak256(a || b) else keccak256(b || a)`) and odd-node promotion (no duplicate-leaf padding), compatible with OpenZeppelin `MerkleProof`.
- **Batch endpoints:**
  - `register_batch(root: bytes32, n_leaves: uint256, batch_uri: String[128])` (`n_leaves > 0`, `root != 0`, non-duplicate) → emits `BatchRegistered`
  - `attest_batch(root: bytes32, decision: uint8)` → emits `BatchAttested`, `BatchStatusChanged`
  - `verify_inclusion(leaf: bytes32, proof: DynArray[bytes32, 32], root: bytes32) -> bool` (`@view`) → returns `True` iff `root` is registered on-chain and `proof` reconstructs `root` from `leaf`.

---

## 6. Verification Suite (`T1`–`T12`)

All invariants are tested under `tests/contracts/` against local EVM (`PyEVMBackend` via `eth-tester`, using `vyper 0.4.3` compiled artifacts):

| ID | Test Target | Expected Outcome |
|---|---|---|
| `T1` | Non-auditor calls `register_case` / `attest` | Reverts (`"Only auditor"`) |
| `T2` | Duplicate `case_id` in `register_case` | Reverts (`"Case already exists"`) |
| `T3` | Invalid `decision` (`0`, `4`, `255`) in `attest` | Reverts (`"Invalid decision"`) |
| `T4` | Exhaustive quorum sequences (`k = 2, n = 3`) | `Open`, `Approved`, `Rejected`, `Disputed` match spec |
| `T5` | Attestation replacement by same auditor | `revision` increments; old/new counters & `status` update |
| `T6` | Owner attempts every case/attestation/admin misuse | Owner cannot alter/delete cases or attestations |
| `T7` | Removed auditor calls `attest` | Reverts; prior attestation & counters stay intact |
| `T8` | `verify_evidence` on exact vs 1-byte tampered JSON | Exact → `True`; 1-byte tampered → `False` |
| `T9` | Event emission & parameter decoding | All 6 event types emit exact arguments |
| `T10` | Invalid `set_threshold` (`0`, `> n`) and `remove_auditor` `< k` | All invalid transitions revert |
| `T11` | Hypothesis property/fuzz test over random operations | `approve + reject + review == non-zero attestations` and `status == py_compute_status(...)` |
| `T12` | `D3` Merkle leaf, valid/tampered/unregistered proofs | Valid → `True`; tampered leaf/proof/root → `False` |
