# Threat Model & "Why Blockchain?" Justification

**Project:** X-SPIDE-G (`RiskAttestationRegistry` + Off-Chain ML/Evidence Pipeline)  
**Version:** v2.0 (Phase 0 Freeze, 2026-11-13)  
**Companion Specs:** [design_v2.md](design_v2.md) · [preregistration.md](preregistration.md)

---

## 1. Scope & Trust Boundary

X-SPIDE-G separates **probabilistic ML risk scoring** (off-chain) from **cryptographic risk attestation governance** (on-chain).

- **Risk scores are indicators, not legal verdicts.** Neither LightGBM predictions nor on-chain auditor attestations prove mathematical or legal fraud.
- **Trust Boundary:** The Streamlit application and ML pipeline run off-chain under the **Model Operator**'s infrastructure and are **not trusted** as the final source of audit history or wallet signatures. Signing occurs client-side in the **Auditor**'s browser wallet (`ethers.js v6` + MetaMask), and final commitment state lives in the immutable EVM registry `RiskAttestationRegistry`.

---

## 2. System Actors & Adversarial Capabilities

| Actor | Legitimate Role | Potential Adversarial / Failure Behavior |
|---|---|---|
| **Model Operator** | Runs data/feature pipeline, LightGBM + SHAP, packages canonical JSON, pins to IPFS/Git. | Alters risk scores, thresholds, or SHAP explanations retroactively after a controversial prediction; serves forged JSON to third-party verifiers. |
| **Auditor** ($n$ authorized wallets, default $n=3$) | Reviews off-chain evidence in Streamlit, registers cases (`register_case`), and signs `Approve` / `Reject` / `NeedsReview` via own EVM wallet. | Individual auditor key compromise, bribery, bias, or post-hoc repudiation ("I never signed that approval"). |
| **Owner / Admin** (Safe multisig on Sepolia; documented if EOA in demo) | Manages auditor membership (`add_auditor`, `remove_auditor`) and quorum parameter (`set_threshold`). Cannot be an auditor (`a != owner`). | Compromised or malicious admin tries to delete an embarrassing case, overwrite `evidence_hash`, forge/revoke an auditor's attestation, or remove auditors to bypass quorum. |
| **Public Verifier** | Any third party inspecting contract risk provenance via RPC/block explorer and `evidenceURI`. | Unprivileged external observer; has no write access and refuses to blindly trust the group's backend server. |

---

## 3. Why Blockchain? Comparative Threat Analysis

A common architectural challenge is whether a centralized relational database storing Ed25519/ECDSA signatures achieves the same goals at lower cost. The matrix below defines the concrete threats where a signed database falls short without an external consensus transparency log, and how `RiskAttestationRegistry` mitigates each threat:

| # | Threat Scenario | Signed Centralized Database | $k$-of-$n$ Blockchain Registry (`RiskAttestationRegistry`) | Verification Test |
|---|---|---|---|---|
| 1 | **Operator alters score, threshold, or SHAP evidence post-publication** | Signature mismatch detects tampering if verifier holds the old snapshot, **but** DB admin can replace both row and signature with a newer timestamped payload or drop the old record. | `evidence_hash` (`keccak256` of canonical JSON), `model_version_hash`, and `block.timestamp` are permanently anchored on-chain; `register_case` reverts on duplicate `case_id`. | `T2`, `T8` (1-byte JSON tamper → `verify_evidence == false` / `❌`) |
| 2 | **Auditor repudiates a past decision** | Mitigated if digital signatures are stored and unalterable. | Auditor must sign an EVM transaction from their own MetaMask wallet; every change increments `revision` and emits an append-only `Attested` event. | `T5`, `T9` |
| 3 | **Admin / Owner rewrites, revokes, or deletes audit history** | **Vulnerable:** DB superuser can `UPDATE`/`DELETE` rows, truncate audit tables, or silence records unless an external transparency log is added. | **Owner has zero functions** to modify or delete cases, alter `evidence_hash`, or revoke/edit attestations. Removing an auditor (`remove_auditor`) keeps their historical attestations intact. | `T6`, `T7` (enforced on Anvil & Sepolia) |
| 4 | **Single-auditor compromise or unilateral collusion** | Single compromised auditor key or single insider signs and finalizes a biased verdict. | Case reaches `1 Approved` or `2 Rejected` **only** when $\ge k$ distinct authorized auditors agree (`k = 2` of `n = 3` by default); conflicting votes yield `3 Disputed`. | `T4`, `T10` (`auditor_count >= threshold`) |
| 5 | **Third-party verification without trusting project server** | Verifier must rely on the operator's API returning complete, uncensored rows. | Verifier queries public EVM state/events directly, fetches JSON from `evidenceURI` (`ipfs://<CID>` or Git commit mirror), and recomputes `keccak256` locally. | Phase 6 Public Verifier E2E + tamper test |
| 6 | **Server-side private key theft (Streamlit compromise)** | Server hosting signing keys leaks all auditor identities upon host compromise. | Streamlit **never holds** Sepolia/auditor keys; signing is delegated to static `signer/index.html` (`ethers.js` + MetaMask). Local Anvil test keys are explicitly labeled `"TEST KEY – ANVIL ONLY"`. | Phase 6 code audit + zero-secret Git history |
| 7 | **Off-chain evidence loss ("hash without data")** | Broken URLs render hashes unverifiable. | `evidenceURI` is emitted in `CaseRegistered` and backed by dual persistence: IPFS pin (`ipfs://<CID>`) plus versioned Git archive (`evidence/<case_id>.json`). | Phase 6 E2E retrieval check |
| 8 | **Identifier collision / replay across chains or runs** | Weak ID concatenation allows cross-chain or cross-run ambiguity. | `case_id = keccak256(abi.encode(chain_id, subject, model_version_hash, run_id))` uses strict ABI encoding (never `abi.encodePacked`) and includes `subject_chain_id`. | Unit tests in `tests/evidence/` |

---

## 4. Contract Security Invariants (Mapped to `T1`–`T12`)

1. **Authorization Isolation (`T1`, `T6`, `T7`):** Non-auditors (including `owner`) cannot call `register_case` or `attest`. Removed auditors cannot submit new attestations, while their prior attestations remain valid in storage/events.
2. **Role Disjointness:** `add_auditor(a)` reverts if `a == owner` or `a == 0x0` or `is_auditor[a] == True`.
3. **Quorum Preservation (`T10`):** `set_threshold(k)` reverts if `k == 0` or `k > auditor_count`; `remove_auditor(a)` reverts if `auditor_count - 1 < threshold`.
4. **Immutable Case Binding (`T2`, `T8`):** Duplicate `case_id` reverts; zero hashes revert; `verify_evidence(case_id, h)` returns `true` iff stored `evidence_hash == h`.
5. **State Machine Integrity (`T4`, `T5`, `T11`):** Across arbitrary random sequences of `register_case` and `attest`, `approve_count + reject_count + review_count` always equals the count of auditors with `decision != 0` for that case, and `status` strictly matches the deterministic specification (`Open / Approved / Rejected / Disputed`).
6. **ETH Safety & Minimal Attack Surface:** No `payable` endpoints or `__default__` payable fallback, no `raw_call`, no `selfdestruct`, bounded `String[128]` for `evidence_uri`.

---

## 5. Explicit Non-Goals & Residual Risks

To maintain academic honesty, X-SPIDE-G explicitly documents what the blockchain layer **does not** solve:

1. **Does not certify ML accuracy or ground truth:** A `2-of-3 Approved` on-chain status attests that two authorized reviewers agreed with the recorded ML risk assessment and its canonical evidence bundle—not that the target smart contract is mathematically proven to be a Ponzi scheme.
2. **Does not prevent $\ge k$ auditor collusion:** If $k$ or more of the $n$ auditors collude or lose their private keys simultaneously (e.g., 2 of 3), they can finalize an arbitrary `Approved` or `Rejected` status.
3. **Residual `owner` key & roster-rotation risk if EOA is used in demo:** While `owner` can never delete cases/attestations or call `attest` from the `owner` address, a compromised `owner` could add a Sybil auditor address it controls (`add_auditor`) and/or lower global `threshold` (`set_threshold(1)`), influencing both new and pre-existing cases upon a subsequent `attest` call. Moreover, because `remove_auditor` preserves prior vote tallies while newly added auditors can still attest to older cases, and `_compute_status` checks `approve_count >= threshold` before `reject_count >= threshold`, governance must enforce $k > n/2$ under a Safe multisig + timelock and avoid rotating auditors while cases remain open.
4. **Off-chain data availability dependence:** Ethereum does not store the full JSON evidence payload (`D1`–`D3` store only `bytes32` commitments and emit `evidenceURI`). If both the IPFS pinning service and the Git repository lose the JSON file, third parties can verify on-chain status history but cannot re-verify feature/SHAP contents against `evidence_hash`.
5. **Ethical & Mainnet Scope Boundary:** Testnet contracts (`Anvil`, `Sepolia`, `L2 testnet`) are used exclusively for evaluation; the group does not publish public Ponzi accusations for live mainnet contracts on Ethereum mainnet.
