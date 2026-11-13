"""Consecutive opcode bigram extraction and leak-free top-k vectorization (F-BIGRAM)."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin

from src.features.disasm import DisassemblyResult


def format_bigram(op1: str, op2: str) -> str:
    """Format an ordered pair of mnemonics as a canonical bigram key."""
    return f"{op1}|{op2}"


def count_bigrams(mnemonics: Sequence[str]) -> tuple[Counter[str], int]:
    """Count consecutive opcode bigrams from a sequence of mnemonics.

    Returns ``(counts, total_bigrams)`` where ``total_bigrams = max(len(mnemonics) - 1, 0)``.
    """
    n = len(mnemonics)
    if n < 2:
        return Counter(), 0
    counts = Counter(format_bigram(mnemonics[i], mnemonics[i + 1]) for i in range(n - 1))
    return counts, n - 1


def extract_bigram_frequencies(
    disasm_res: DisassemblyResult,
    *,
    normalize: bool = True,
) -> dict[str, float]:
    """Compute length-normalized consecutive opcode bigram relative frequencies.

    Each bigram ``(o_i, o_{i+1})`` gets weight ``count / (L - 1)`` so all non-empty
    documents of length ``L >= 2`` have frequencies summing to ``1.0``.
    """
    mnemonics = disasm_res.mnemonics(normalize=normalize)
    counts, total = count_bigrams(mnemonics)
    if total == 0:
        return {}
    inv_total = 1.0 / total
    return {tok: cnt * inv_total for tok, cnt in counts.items()}


def extract_bigram_row(disasm_res: DisassemblyResult) -> dict[str, int | str]:
    """Extract compact scalar/JSON fields for both normalized and raw bigrams.

    Storing full sparse frequency maps per contract defers top-k vocabulary selection
    to each training fold in ``BigramTopKVectorizer`` (avoiding test-fold leakage).
    """
    norm_counts, norm_total = count_bigrams(disasm_res.mnemonics(normalize=True))
    raw_counts, raw_total = count_bigrams(disasm_res.mnemonics(normalize=False))

    norm_freqs = (
        {tok: cnt / norm_total for tok, cnt in norm_counts.items()} if norm_total > 0 else {}
    )
    raw_freqs = (
        {tok: cnt / raw_total for tok, cnt in raw_counts.items()} if raw_total > 0 else {}
    )

    return {
        "bigram_total_norm": norm_total,
        "bigram_unique_norm": len(norm_freqs),
        "bigram_freq_norm_json": json.dumps(norm_freqs, separators=(",", ":"), sort_keys=True),
        "bigram_total_raw": raw_total,
        "bigram_unique_raw": len(raw_freqs),
        "bigram_freq_raw_json": json.dumps(raw_freqs, separators=(",", ":"), sort_keys=True),
    }


def _iter_freq_dicts(
    X: pd.DataFrame | pd.Series | Iterable[str | Mapping[str, float]],
    column: str,
) -> list[dict[str, float]]:
    """Normalize input tables or sequences into a list of parsed frequency dicts."""
    if isinstance(X, pd.DataFrame):
        if column not in X.columns:
            raise KeyError(f"Column '{column}' not found in DataFrame columns={list(X.columns)}")
        items: Iterable[Any] = X[column].tolist()
    elif isinstance(X, pd.Series):
        items = X.tolist()
    else:
        items = X

    parsed: list[dict[str, float]] = []
    for item in items:
        if isinstance(item, Mapping):
            parsed.append({str(k): float(v) for k, v in item.items()})
        elif isinstance(item, str):
            loaded = json.loads(item) if item else {}
            parsed.append({str(k): float(v) for k, v in loaded.items()})
        elif item is None or (isinstance(item, float) and np.isnan(item)):
            parsed.append({})
        else:
            raise TypeError(f"Unsupported bigram payload type: {type(item)!r}")
    return parsed


class BigramTopKVectorizer(BaseEstimator, TransformerMixin):
    """Select the top-k opcode bigrams by training-fold document frequency.

    Designed for ``sklearn.pipeline.Pipeline`` so vocabulary selection strictly sees
    only ``X_train`` in every CV fold.
    """

    def __init__(
        self,
        top_k: int = 200,
        column: str = "bigram_freq_norm_json",
        prefix: str = "bigram__",
    ) -> None:
        self.top_k = top_k
        self.column = column
        self.prefix = prefix

    def fit(
        self,
        X: pd.DataFrame | pd.Series | Iterable[str | Mapping[str, float]],
        y: Any = None,
    ) -> BigramTopKVectorizer:
        """Fit top-k bigram vocabulary strictly on training documents."""
        if self.top_k <= 0:
            raise ValueError(f"top_k must be positive, got {self.top_k}")

        docs = _iter_freq_dicts(X, self.column)
        df_counts: Counter[str] = Counter()
        total_freqs: Counter[str] = Counter()
        for doc in docs:
            for tok, freq in doc.items():
                if freq > 0.0:
                    df_counts[tok] += 1
                    total_freqs[tok] += freq

        ranked = sorted(
            df_counts.keys(),
            key=lambda tok: (-df_counts[tok], -total_freqs[tok], tok),
        )
        vocab = tuple(ranked[: self.top_k])
        self.vocabulary_: tuple[str, ...] = vocab
        self.token_to_idx_: dict[str, int] = {tok: idx for idx, tok in enumerate(vocab)}
        self.document_frequencies_: dict[str, int] = {tok: df_counts[tok] for tok in vocab}
        self.n_features_in_ = 1 if isinstance(X, pd.DataFrame) else None
        return self

    def transform(
        self,
        X: pd.DataFrame | pd.Series | Iterable[str | Mapping[str, float]],
    ) -> np.ndarray:
        """Transform contracts into a dense ``(n_samples, len(vocabulary_))`` array."""
        if not hasattr(self, "token_to_idx_"):
            raise RuntimeError("BigramTopKVectorizer must be fitted before calling transform.")

        docs = _iter_freq_dicts(X, self.column)
        out = np.zeros((len(docs), len(self.vocabulary_)), dtype=np.float64)
        token_to_idx = self.token_to_idx_
        for row_idx, doc in enumerate(docs):
            for tok, freq in doc.items():
                col_idx = token_to_idx.get(tok)
                if col_idx is not None:
                    out[row_idx, col_idx] = freq
        return out

    def get_feature_names_out(self, input_features: Any = None) -> np.ndarray:
        """Return output feature names compatible with scikit-learn estimators."""
        if not hasattr(self, "vocabulary_"):
            raise RuntimeError("BigramTopKVectorizer must be fitted first.")
        return np.asarray([f"{self.prefix}{tok}" for tok in self.vocabulary_], dtype=object)
