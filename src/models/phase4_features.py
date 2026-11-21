"""Feature assembly, sensitivity feature variants (S2/S4), and E6 code-only loaders."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin

from src.data.bytecode import extract_runtime_from_initcode, parse_hex_bytecode, strip_cbor_metadata
from src.data.clones import compute_minhash, opcode_shingles
from src.data.parquet_io import read_parquet
from src.features.bigram import BigramTopKVectorizer, extract_bigram_frequencies
from src.features.disasm import disassemble
from src.features.gsem import GSEM_FEATURE_NAMES, extract_gsem_features
from src.features.gstat import GSTAT_FEATURE_NAMES
from src.models.data_prep import (
    get_xspide_feature_columns,
    load_contracts_dataset,
    prepare_xspide_99_features,
)

# X-SPIDE CSV uses pre-Shanghai opcode names for three instructions.
_DISASM_TO_XSPIDE_OPCODE: dict[str, str] = {
    "KECCAK256": "SHA3",
    "PREVRANDAO": "DIFFICULTY",
    "PC": "GETPC",
}


class TabularBigramAssembler(BaseEstimator, TransformerMixin):
    """Combine numeric tabular features with an in-fold top-k bigram vectorizer.

    Fits ``BigramTopKVectorizer`` strictly on each training fold and outputs a
    ``pandas.DataFrame`` with preserved column names for LightGBM and SHAP.
    """

    def __init__(
        self,
        tabular_cols: tuple[str, ...] = (),
        bigram_column: str = "bigram_freq_payload",
        top_k: int = 200,
        bigram_prefix: str = "bigram__",
    ) -> None:
        self.tabular_cols = tuple(tabular_cols)
        self.bigram_column = bigram_column
        self.top_k = top_k
        self.bigram_prefix = bigram_prefix

    def fit(self, X: pd.DataFrame, y: Any = None) -> TabularBigramAssembler:
        """Fit the top-k bigram vocabulary strictly on ``X``."""
        self.vectorizer_ = BigramTopKVectorizer(
            top_k=self.top_k,
            column=self.bigram_column,
            prefix=self.bigram_prefix,
        )
        self.vectorizer_.fit(X)
        bigram_names = self.vectorizer_.get_feature_names_out().tolist()
        self.tabular_cols_ = tuple(self.tabular_cols)
        self.feature_names_out_: tuple[str, ...] = (*self.tabular_cols_, *bigram_names)
        self.n_features_in_ = X.shape[1]
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """Transform ``X`` into a dense numeric DataFrame of tabular + top-k bigrams."""
        if not hasattr(self, "vectorizer_"):
            raise RuntimeError("TabularBigramAssembler must be fitted before transform.")
        bigram_arr = self.vectorizer_.transform(X)
        if self.tabular_cols_:
            tab_arr = X[list(self.tabular_cols_)].to_numpy(dtype=np.float64)
            combined = np.hstack([tab_arr, bigram_arr])
        else:
            combined = bigram_arr
        index = X.index if isinstance(X, pd.DataFrame) else None
        return pd.DataFrame(combined, columns=list(self.feature_names_out_), index=index)

    def get_feature_names_out(self, input_features: Any = None) -> np.ndarray:
        """Return output feature names for scikit-learn introspection."""
        if not hasattr(self, "feature_names_out_"):
            raise RuntimeError("TabularBigramAssembler must be fitted first.")
        return np.asarray(self.feature_names_out_, dtype=object)


def _parse_json_freq_column(series: pd.Series) -> pd.Series:
    """Parse JSON frequency strings once into dicts so inner CV avoids repeated JSON decoding."""
    return pd.Series(
        [json.loads(val) if isinstance(val, str) and val else (dict(val) if isinstance(val, dict) else {}) for val in series],
        index=series.index,
        dtype=object,
    )


def extract_bytecode_features_single_pass(
    hex_series: Sequence[str] | pd.Series,
    opcode_76_cols: Sequence[str],
    *,
    compute_op76: bool = True,
    compute_bigram: bool = False,
    compute_gsem: bool = False,
    normalize_opcodes: bool = True,
) -> dict[str, pd.DataFrame | pd.Series]:
    """Disassemble bytecodes in a single pass for consistent code-only / S2 / S4 features."""
    op76_set = set(opcode_76_cols)
    op76_rows: list[dict[str, float]] = []
    bigram_dicts: list[dict[str, float]] = []
    gsem_rows: list[dict[str, float]] = []

    for hx in hex_series:
        raw = parse_hex_bytecode(hx if isinstance(hx, str) else "")
        dis = disassemble(raw, log_truncated=False)

        if compute_op76:
            mnems_norm = dis.mnemonics(normalize=True)
            counts: Counter[str] = Counter()
            for m in mnems_norm:
                mapped = _DISASM_TO_XSPIDE_OPCODE.get(m, m)
                if mapped in op76_set:
                    counts[mapped] += 1
            total = float(sum(counts.values()))
            if total > 0.0:
                op76_rows.append({col: counts.get(col, 0) / total for col in opcode_76_cols})
            else:
                op76_rows.append({col: 0.0 for col in opcode_76_cols})

        if compute_bigram:
            bigram_dicts.append(extract_bigram_frequencies(dis, normalize=normalize_opcodes))

        if compute_gsem:
            gsem_rows.append(extract_gsem_features(dis, normalize=normalize_opcodes))

    out: dict[str, Any] = {}
    idx = hex_series.index if isinstance(hex_series, pd.Series) else None
    if compute_op76:
        out["op76"] = pd.DataFrame(op76_rows, columns=list(opcode_76_cols), index=idx, dtype=np.float64)
    if compute_bigram:
        out["bigram"] = pd.Series(bigram_dicts, index=idx, dtype=object)
    if compute_gsem:
        out["gsem"] = pd.DataFrame(gsem_rows, columns=list(GSEM_FEATURE_NAMES), index=idx, dtype=np.float64)
    return out


def _align_feature_table(df_base: pd.DataFrame, df_feat: pd.DataFrame) -> pd.DataFrame:
    """Align extracted feature Parquet rows to `df_base` strictly by `sample_id`."""
    base_ids = df_base["sample_id"].astype(str).tolist()
    feat_idx = df_feat.copy()
    feat_idx["sample_id"] = feat_idx["sample_id"].astype(str)
    feat_idx = feat_idx.set_index("sample_id")
    aligned = feat_idx.reindex(base_ids).reset_index(drop=True)
    if aligned.isna().any().any():
        raise ValueError("Aligned feature table contains NaN after reindexing by sample_id.")
    return aligned


def load_phase4_dataset(
    repo_root: Path,
    config_name: str,
) -> tuple[pd.DataFrame, pd.DataFrame, tuple[tuple[str, Any], ...] | None]:
    """Return `(df_meta, X, pipeline_pre_steps)` for any Phase 4 or S1/S2/S4 experiment."""
    df_meta = load_contracts_dataset(repo_root, subset="S_code")
    cols_99, acct_23, op_76 = get_xspide_feature_columns(df_meta)
    X99 = prepare_xspide_99_features(df_meta, normalize_opcodes=True)

    feat_dir = repo_root / "data" / "processed"

    if config_name in ("E1", "E1_S0_random_5x5", "E1_S1_group_exact"):
        return df_meta, X99, None

    if config_name == "E3":
        df_gstat = _align_feature_table(df_meta, read_parquet(feat_dir / "features_gstat.parquet"))
        X = df_gstat[list(GSTAT_FEATURE_NAMES)].astype("float64")
        return df_meta, X, None

    if config_name == "E3b":
        df_bg = _align_feature_table(df_meta, read_parquet(feat_dir / "features_bigram.parquet"))
        X = pd.DataFrame({"bigram_freq_payload": _parse_json_freq_column(df_bg["bigram_freq_norm_json"])})
        pre = (("assemble", TabularBigramAssembler(tabular_cols=(), bigram_column="bigram_freq_payload", top_k=200)),)
        return df_meta, X, pre

    if config_name == "E3c":
        df_gsem = _align_feature_table(df_meta, read_parquet(feat_dir / "features_gsem.parquet"))
        X = df_gsem[list(GSEM_FEATURE_NAMES)].astype("float64")
        return df_meta, X, None

    if config_name == "E4":
        df_gstat = _align_feature_table(df_meta, read_parquet(feat_dir / "features_gstat.parquet"))
        X = pd.concat([X99, df_gstat[list(GSTAT_FEATURE_NAMES)].astype("float64")], axis=1)
        return df_meta, X, None

    if config_name == "E4b":
        df_bg = _align_feature_table(df_meta, read_parquet(feat_dir / "features_bigram.parquet"))
        X = X99.copy()
        X["bigram_freq_payload"] = _parse_json_freq_column(df_bg["bigram_freq_norm_json"])
        pre = (("assemble", TabularBigramAssembler(tabular_cols=tuple(cols_99), bigram_column="bigram_freq_payload", top_k=200)),)
        return df_meta, X, pre

    if config_name in ("E4c", "E4c_S1_group_exact"):
        df_gsem = _align_feature_table(df_meta, read_parquet(feat_dir / "features_gsem.parquet"))
        X = pd.concat([X99, df_gsem[list(GSEM_FEATURE_NAMES)].astype("float64")], axis=1)
        return df_meta, X, None

    if config_name == "E4d":
        df_bg = _align_feature_table(df_meta, read_parquet(feat_dir / "features_bigram.parquet"))
        df_gsem = _align_feature_table(df_meta, read_parquet(feat_dir / "features_gsem.parquet"))
        gsem_df = df_gsem[list(GSEM_FEATURE_NAMES)].astype("float64")
        X = pd.concat([X99, gsem_df], axis=1)
        X["bigram_freq_payload"] = _parse_json_freq_column(df_bg["bigram_freq_norm_json"])
        tab_cols = (*cols_99, *GSEM_FEATURE_NAMES)
        pre = (("assemble", TabularBigramAssembler(tabular_cols=tab_cols, bigram_column="bigram_freq_payload", top_k=200)),)
        return df_meta, X, pre

    # Sensitivity S2: Raw bytecode (with CBOR metadata) vs CBOR-stripped bytecode
    if config_name == "E1_S2_cbor_stripped":
        ext = extract_bytecode_features_single_pass(
            df_meta["stripped_bytecode_hex"],
            op_76,
            compute_op76=True,
            compute_bigram=False,
            compute_gsem=False,
        )
        X = pd.concat([df_meta[acct_23].astype("float64").fillna(0.0), ext["op76"]], axis=1)[cols_99]
        return df_meta, X, None

    if config_name == "E4c_S2_raw_cbor":
        ext = extract_bytecode_features_single_pass(
            df_meta["bytecode_hex"],
            op_76,
            compute_op76=False,
            compute_bigram=False,
            compute_gsem=True,
            normalize_opcodes=True,
        )
        X = pd.concat([X99, ext["gsem"]], axis=1)
        return df_meta, X, None

    if config_name == "E4c_S2_cbor_stripped":
        ext = extract_bytecode_features_single_pass(
            df_meta["stripped_bytecode_hex"],
            op_76,
            compute_op76=True,
            compute_bigram=False,
            compute_gsem=False,
        )
        df_gsem = _align_feature_table(df_meta, read_parquet(feat_dir / "features_gsem.parquet"))
        X99_stripped = pd.concat([df_meta[acct_23].astype("float64").fillna(0.0), ext["op76"]], axis=1)[cols_99]
        X = pd.concat([X99_stripped, df_gsem[list(GSEM_FEATURE_NAMES)].astype("float64")], axis=1)
        return df_meta, X, None

    # Sensitivity S4: Mnemonic normalization sensitivity (raw opcodes vs collapsed families)
    if config_name == "E4b_S4_raw_opcodes":
        df_bg = _align_feature_table(df_meta, read_parquet(feat_dir / "features_bigram.parquet"))
        X = X99.copy()
        X["bigram_freq_payload"] = _parse_json_freq_column(df_bg["bigram_freq_raw_json"])
        pre = (("assemble", TabularBigramAssembler(tabular_cols=tuple(cols_99), bigram_column="bigram_freq_payload", top_k=200)),)
        return df_meta, X, pre

    if config_name == "E4c_S4_raw_opcodes":
        ext = extract_bytecode_features_single_pass(
            df_meta["stripped_bytecode_hex"],
            op_76,
            compute_op76=False,
            compute_bigram=False,
            compute_gsem=True,
            normalize_opcodes=False,
        )
        X = pd.concat([X99, ext["gsem"]], axis=1)
        return df_meta, X, None

    raise ValueError(f"Unknown Phase 4 configuration: {config_name!r}")


def load_e6_ponziguard_sanity_datasets(
    repo_root: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, tuple[tuple[str, Any], ...]]:
    """Prepare matched code-only features (76 opcodes + F-BIGRAM + F-GSEM) for S_code and deduped PonziGuard."""
    from datasketch import MinHashLSH

    df_s_code = load_contracts_dataset(repo_root, subset="S_code")
    _, _, op_76 = get_xspide_feature_columns(df_s_code)

    # Extract code-only features from stripped bytecode on S_code.
    s_ext = extract_bytecode_features_single_pass(
        df_s_code["stripped_bytecode_hex"],
        op_76,
        compute_op76=True,
        compute_bigram=True,
        compute_gsem=False,
        normalize_opcodes=True,
    )
    df_gsem = _align_feature_table(df_s_code, read_parquet(repo_root / "data" / "processed" / "features_gsem.parquet"))
    gsem_s = df_gsem[list(GSEM_FEATURE_NAMES)].astype("float64")
    X_train = pd.concat([s_ext["op76"], gsem_s], axis=1)
    X_train["bigram_freq_payload"] = s_ext["bigram"]

    # Build X-SPIDE overlap filters matching Phase 1 audit.py (code_hash + group_near LSH).
    x_hashes = set(df_s_code["code_hash"].dropna().str.lower())
    lsh = MinHashLSH(threshold=0.90, num_perm=128)
    x_shingles: dict[str, set[bytes]] = {}
    seen_hashes: set[str] = set()
    for ch, hx in zip(df_s_code["code_hash"], df_s_code["stripped_bytecode_hex"]):
        if not ch or ch in seen_hashes or not hx:
            continue
        seen_hashes.add(ch)
        sh = opcode_shingles(parse_hex_bytecode(hx), k=5)
        if sh:
            mh = compute_minhash(sh, num_perm=128)
            x_shingles[ch] = sh
            lsh.insert(ch, mh)

    def _overlaps_xspide(stripped_bytes: bytes, ch: str | None) -> bool:
        if ch and ch.lower() in x_hashes:
            return True
        if stripped_bytes:
            sh = opcode_shingles(stripped_bytes, k=5)
            if sh:
                mh = compute_minhash(sh, num_perm=128)
                for cand_ch in lsh.query(mh):
                    other = x_shingles[cand_ch]
                    union_sz = len(sh | other)
                    if union_sz and (len(sh & other) / union_sz) >= 0.90:
                        return True
        return False

    pg_base = repo_root / "data" / "raw" / "ponziguard" / "extracted"
    pg_dirs = [
        (pg_base / "Ponzi" / "Ponzi" / "verified_contract_bins", 1),
        (pg_base / "non-Ponzi" / "non-Ponzi" / "verified_contract_bins", 0),
    ]

    pg_rows: list[dict[str, Any]] = []
    seen_pg_hashes: dict[str, int] = {}
    for bin_dir, label in pg_dirs:
        for bpath in sorted(bin_dir.glob("*.bin")):
            hx = bpath.read_text(encoding="utf-8", errors="replace").strip()
            try:
                raw_init = parse_hex_bytecode(hx)
            except ValueError:
                continue
            if not raw_init:
                continue
            rt = extract_runtime_from_initcode(raw_init)
            if not rt:
                continue
            st = strip_cbor_metadata(rt)
            if _overlaps_xspide(st.stripped_bytes, st.code_hash):
                continue
            ch_low = st.code_hash.lower() if st.code_hash else bpath.stem
            if ch_low in seen_pg_hashes:
                if seen_pg_hashes[ch_low] != label:
                    raise ValueError(f"Conflicting PonziGuard labels for code_hash {ch_low}")
                continue
            seen_pg_hashes[ch_low] = label
            pg_rows.append(
                {
                    "sample_id": bpath.stem,
                    "label": int(label),
                    "code_hash": ch_low,
                    "stripped_bytecode_hex": "0x" + st.stripped_bytes.hex(),
                }
            )

    df_pg = pd.DataFrame(pg_rows)
    pg_ext = extract_bytecode_features_single_pass(
        df_pg["stripped_bytecode_hex"],
        op_76,
        compute_op76=True,
        compute_bigram=True,
        compute_gsem=True,
        normalize_opcodes=True,
    )
    X_pg = pd.concat([pg_ext["op76"], pg_ext["gsem"]], axis=1)
    X_pg["bigram_freq_payload"] = pg_ext["bigram"]

    tab_cols = (*op_76, *GSEM_FEATURE_NAMES)
    pre = (("assemble", TabularBigramAssembler(tabular_cols=tab_cols, bigram_column="bigram_freq_payload", top_k=200)),)
    return df_s_code, X_train, df_pg, X_pg, pre
