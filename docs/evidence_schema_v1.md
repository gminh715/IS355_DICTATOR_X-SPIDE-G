# Canonical Evidence Schema Specification (`v1.0`)

**Project:** X-SPIDE-G (`IS355 – Blockchain Technology · Group 4 – DICTATOR`)  
**Phase:** Phase 6.1 Specification  
**Companion Docs:** [design_v2.md](design_v2.md) · [threat_model.md](threat_model.md) · [contract_spec.md](contract_spec.md)

---

## 1. Purpose

This specification defines the deterministic JSON serialization, cryptographic hashing, `case_id` derivation, and off-chain persistence rules linking an off-chain LightGBM + SHAP prediction (`models/baseline_v1/`) to the on-chain `RiskAttestationRegistry` Vyper contract (`contracts/RiskAttestationRegistry.vy`).

Any third-party verifier holding the raw JSON file (retrieved via `evidenceURI` on IPFS or the Git mirror) and the on-chain `Case` / `CaseRegistered` record can independently recompute `shap_digest`, `evidence_hash`, and `case_id` without trusting the Streamlit server.

---

## 2. Canonical JSON Rules

All evidence documents MUST obey these canonicalization rules prior to hashing:

1. **Encoding:** UTF-8 without BOM (`ensure_ascii=False`).
2. **Key Ordering & Whitespace:** `sort_keys=True`, `separators=(",", ":")` (zero extra whitespace after commas or colons).
3. **No Raw Floating-Point Numbers or Non-Finite Values:**
   - `allow_nan=False` (`NaN`, `Infinity`, `-Infinity` are forbidden).
   - Every real-valued numeric quantity (`score`, `threshold`, `shap_top_k[*].value`, `shap_top_k[*].shap_value`) MUST be formatted as a fixed **6-decimal string** (`f"{x:.6f}"`, with `"-0.000000"` normalized to `"0.000000"`).
   - Integer fields (`source_chain_id`, `predicted_label`) remain JSON integers.
4. **Addresses & Hex Hashes:**
   - Ethereum addresses (`subject_address`) MUST be lowercase `0x` + 40 hexadecimal characters (`len == 42`).
   - 32-byte digests (`code_hash`, `feature_schema_hash`, `model_version_hash`, `shap_digest`, `run_id`) MUST be lowercase `0x` + 64 hexadecimal characters (`len == 66`).
5. **Timestamps:**
   - `created_at_utc` MUST be UTC ISO-8601 with trailing `Z` at second precision (`YYYY-MM-DDTHH:MM:SSZ`).

---

## 3. Evidence Schema (`schema_version = "1.0"`)

| Field | Type | Constraints / Example |
|---|---|---|
| `schema_version` | `string` | Constant `"1.0"` |
| `source_chain_id` | `integer` | Positive integer chain ID of analyzed contract (`1` = Ethereum mainnet) |
| `subject_address` | `string` | Lowercase `0x` + 40 hex chars, e.g. `"0x0006157838d5a6b33ab66588a6a693a57c869999"` |
| `code_hash` | `string` | `keccak256(runtime_bytecode_stripped)` as lowercase `0x` + 64 hex chars |
| `dataset_id` | `string` | Non-empty identifier, e.g. `"xspide_S_code"` or `"custom_bytecode"` |
| `sample_id` | `string` | Non-empty sample identifier, e.g. `"xspide_00000"` |
| `feature_schema_hash` | `string` | `keccak256(feature_schema.json)` from `model_card.json` (`0x...`) |
| `model_version_hash` | `string` | `keccak256(model_file_bytes \|\| feature_schema_json)` (`0x...`) |
| `score` | `string` | Predicted Ponzi probability as 6-decimal string, e.g. `"0.873421"` |
| `threshold` | `string` | Decision threshold $\tau^*$ as 6-decimal string, e.g. `"0.256746"` |
| `predicted_label` | `integer` | Binary prediction (`1` if `score >= threshold` else `0`); **risk indicator, not legal verdict** |
| `shap_top_k` | `array[object]` | Top-10 SHAP contributors sorted by `abs(shap_value)` descending, tie-broken by `feature` ascending |
| `shap_digest` | `string` | `"0x" + keccak256(canonical_bytes(shap_top_k)).hex()` |
| `run_id` | `string` | Unique 32-byte run identifier (`0x` + 64 hex chars) |
| `created_at_utc` | `string` | UTC timestamp `YYYY-MM-DDTHH:MM:SSZ` |

### `shap_top_k` Entry Structure

Each element in `shap_top_k` (`1 <= len(shap_top_k) <= 10`) contains exactly three keys:

| Key | Type | Description |
|---|---|---|
| `feature` | `string` | Exact feature name from `models/baseline_v1/feature_schema.json` |
| `value` | `string` | Feature input value formatted to 6 decimals (`"0.000000"`) |
| `shap_value` | `string` | Positive-class TreeExplainer SHAP log-odds contribution formatted to 6 decimals (`"-0.412305"`) |

---

## 4. Cryptographic Identifiers

```python
import json
from eth_abi import encode
from eth_utils import keccak

def canonical_bytes(evidence: dict) -> bytes:
    return json.dumps(
        evidence,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

def evidence_hash(evidence: dict) -> bytes:
    return keccak(canonical_bytes(evidence))

def case_id(
    chain_id: int,
    subject: str,
    model_version_hash: bytes,
    run_id: bytes,
) -> bytes:
    # Strict ABI encoding (never encode_packed) prevents concatenation collisions.
    return keccak(
        encode(
            ["uint256", "address", "bytes32", "bytes32"],
            [chain_id, subject, model_version_hash, run_id],
        )
    )
```

---

## 5. Off-Chain Persistence & Tamper Detection

1. **Content-Addressed URI (`evidence_uri`):**
   - Computed as IPFS CIDv1 (`raw` multicodec `0x55`, `sha2-256` multihash `0x12`, base32lower multibase `'b'`, e.g. `ipfs://bafkrei...`, 66 ASCII chars, strictly within the contract's `String[128]` bound).
   - Pinned via local Kubo daemon (`IPFS_API_URL`) or Pinata (`PINATA_JWT`) when configured; otherwise stored content-addressed locally with explicit `pin_status = "local_content_addressed_unpinned"`.
2. **Git Mirror Backup:**
   - Canonical JSON bytes are saved verbatim to `evidence/<case_id>.json` and indexed in `evidence/cid_index.json` alongside the repository commit hash.
3. **Public Verification Check (`✅` / `❌`):**
   - Fetch raw bytes from `evidence_uri` (or Git mirror / user upload).
   - Compute `h = keccak256(raw_bytes)`.
   - Verify `h == onchain_case.evidence_hash` AND `contract.verify_evidence(case_id, h) == True` AND `shap_digest` matches `shap_top_k`.
   - Cross-check all identity bindings between the JSON payload and the on-chain `Case` struct: `subject_address == onchain_case.subject`, `source_chain_id == onchain_case.subject_chain_id`, `model_version_hash == onchain_case.model_version_hash`, and `case_id(source_chain_id, subject_address, model_version_hash, run_id) == case_id`.
   - Any 1-byte modification or identity mismatch triggers `❌ TAMPERED / MISMATCH`.
