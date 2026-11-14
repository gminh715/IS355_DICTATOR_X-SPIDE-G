# Canonical Risk Evidence JSON Specification (`v1.0`)

**Project:** X-SPIDE-G (`IS355 – Blockchain Technology · Group 4 – DICTATOR`)  
**Phase:** Phase 6 (`6.1` & `6.2`)  
**Version:** `1.0` (Aligned with [design_v2.md](design_v2.md), [threat_model.md](threat_model.md), and [contract_spec.md](contract_spec.md))

---

## 1. Purpose & Design Goals

On-chain storage in `RiskAttestationRegistry` (`D1`–`D3`) anchors 32-byte cryptographic commitments (`case_id`, `evidence_hash`, `model_version_hash`) and an off-chain locator (`evidence_uri: String[128]`), while full machine-learning predictions and SHAP feature attributions reside off-chain.

To guarantee that any independent third party (in Python, JavaScript, or CLI) can fetch the off-chain JSON file and recompute the **exact same** `keccak256` digest without floating-point or whitespace ambiguity, all evidence bundles follow a strict canonical serialization specification.

---

## 2. Schema Fields (`schema_version = "1.0"`)

Every top-level evidence JSON object contains exactly the following 15 keys:

| Field | JSON Type | Format / Constraint | Description |
|---|---|---|---|
| `schema_version` | `string` | `"1.0"` | Canonical evidence schema version |
| `source_chain_id` | `integer` | $\ge 1$ (e.g., `1` for Ethereum Mainnet) | Chain ID where the subject smart contract resides |
| `subject_address` | `string` | `^0x[0-9a-f]{40}$` (lowercase) | Normalized 20-byte Ethereum address of the evaluated contract |
| `code_hash` | `string` | `^0x[0-9a-f]{64}$` (lowercase) | `keccak256(runtime_bytecode_stripped)` after valid CBOR stripping |
| `dataset_id` | `string` | Non-empty ASCII identifier | Dataset provenance tag (e.g., `"xspide_s_code"`) |
| `sample_id` | `string` | Non-empty string | Deterministic dataset row identifier |
| `feature_schema_hash` | `string` | `^0x[0-9a-f]{64}$` (lowercase) | `keccak256` of `models/baseline_v1/feature_schema.json` |
| `model_version_hash` | `string` | `^0x[0-9a-f]{64}$` (lowercase) | `keccak256(model_file_bytes \|\| feature_schema_json)` |
| `score` | `string` | Fixed 6-decimal string (e.g., `"0.873421"`) | Predicted positive-class (`Ponzi = 1`) probability in $[0, 1]$ |
| `threshold` | `string` | Fixed 6-decimal string (e.g., `"0.256746"`) | Inner-CV validation-tuned classification threshold $\tau^*$ |
| `predicted_label` | `integer` | `0` or `1` | Binary prediction (`1` if `float(score) >= float(threshold)` else `0`) |
| `shap_top_k` | `array<object>` | Length $1 \le k \le 10$ | Top-$k$ features ranked by descending $\|\text{SHAP value}\|$ |
| `shap_digest` | `string` | `^0x[0-9a-f]{64}$` (lowercase) | `keccak256` of the canonical JSON bytes of `shap_top_k` |
| `run_id` | `string` | `^0x[0-9a-f]{64}$` (lowercase) | 32-byte run identifier binding this evaluation instance |
| `created_at_utc` | `string` | ISO-8601 UTC ending in `Z` | Creation timestamp (`YYYY-MM-DDTHH:MM:SSZ`) |

### `shap_top_k` Element Structure

Each element in `shap_top_k` has 4 keys:

```json
{
  "feature": "has_loop_with_call",
  "feature_value": "1.000000",
  "rank": 1,
  "shap_value": "0.314159"
}
```

---

## 3. Canonicalization Rules

1. **Encoding:** UTF-8 without BOM.
2. **Key Ordering:** Lexicographically sorted keys at every nesting level (`sort_keys=True`).
3. **Whitespace Elimination:** Compact separators `separators=(",", ":")` with zero spaces or trailing newlines.
4. **No Raw Floats / NaN / Infinity:**
   - `allow_nan=False` is strictly enforced (`NaN`, `Infinity`, `-Infinity` raise `ValueError`).
   - All real numbers (`score`, `threshold`, `feature_value`, `shap_value`) are formatted prior to serialization as **fixed 6-decimal strings** (`f"{val:.6f}"`, with `-0.000000` normalized to `"0.000000"`). Raw Python `float` values inside an evidence dictionary are rejected during validation so cross-language serializers never diverge on IEEE-754 formatting.
5. **Hex Normalization:** All Ethereum addresses (`0x` + 40 hex chars) and 32-byte hashes (`0x` + 64 hex chars) must be lowercase.
6. **UTC Timestamp:** ISO-8601 UTC format `YYYY-MM-DDTHH:MM:SSZ` (always suffix `Z`, never local offset).

---

## 4. Cryptographic Hash Formulas

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
    # Standard abi.encode (never encode_packed) prevents dynamic collision attacks
    return keccak(
        encode(
            ["uint256", "address", "bytes32", "bytes32"],
            [chain_id, subject, model_version_hash, run_id],
        )
    )
```

---

## 5. Dual Off-Chain Persistence (`6.2`)

To mitigate Threat #7 (*"hash without data"* if an off-chain host disappears):

1. **IPFS Content Addressing (`evidence_uri`):**
   - The canonical bytes are hashed with SHA-256 into a deterministic **IPFS CIDv1** (`raw` multicodec `0x55`, `sha2-256` multihash `0x1220...`, base32lower `bafkrei...`).
   - The primary `evidence_uri` emitted in `CaseRegistered` is `ipfs://<CIDv1>` (66 characters $\le$ `String[128]`).
   - When a local Kubo daemon (`IPFS_API_URL`) or Pinata (`PINATA_JWT`) is reachable, the canonical payload is pinned automatically.
2. **Git Repository Mirror (`evidence/`):**
   - Every generated bundle is saved verbatim as `evidence/<case_id_hex>.json` in the repository so verifiers can always retrieve the exact bytes from Git history even without an IPFS gateway.
