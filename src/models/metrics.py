"""Pre-registered evaluation metrics and strictly in-fold threshold optimization."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)


def compute_recall_at_precision(
    y_true: np.ndarray,
    y_score: np.ndarray,
    min_precision: float = 0.90,
) -> tuple[float, bool]:
    """Return max recall achieving precision >= min_precision (and fallback flag if unattainable)."""
    y_t = np.asarray(y_true, dtype=int)
    y_s = np.asarray(y_score, dtype=float)
    prec, rec, _ = precision_recall_curve(y_t, y_s)
    # Exclude the synthetic final endpoint (precision=1.0, recall=0.0, no threshold).
    p_valid = prec[:-1]
    r_valid = rec[:-1]
    mask = (p_valid >= min_precision) & (r_valid > 0.0)
    if not np.any(mask):
        return 0.0, True
    return float(np.max(r_valid[mask])), False


def find_best_f1_threshold(y_true: np.ndarray, y_score: np.ndarray) -> float:
    """Find probability threshold >= tau maximizing F1 on out-of-fold validation scores."""
    y_t = np.asarray(y_true, dtype=int)
    y_s = np.asarray(y_score, dtype=float)
    prec, rec, thresh = precision_recall_curve(y_t, y_s)
    if len(thresh) == 0:
        return 0.5

    p = prec[:-1]
    r = rec[:-1]
    denom = p + r
    f1 = np.where(denom > 0.0, 2.0 * p * r / denom, 0.0)
    best_f1 = float(np.max(f1))
    if best_f1 <= 0.0:
        return 0.5

    best_indices = np.flatnonzero(np.isclose(f1, best_f1, rtol=0.0, atol=1e-12))
    cand_thresholds = thresh[best_indices]
    # Deterministic tie-breaking closest to 0.5.
    best_tau = float(cand_thresholds[np.argmin(np.abs(cand_thresholds - 0.5))])
    return float(np.clip(best_tau, 1e-6, 1.0 - 1e-6))


def evaluate_predictions(
    y_true: np.ndarray,
    y_score: np.ndarray,
    threshold: float,
) -> dict[str, Any]:
    """Compute all pre-registered classification and ranking metrics for a fold."""
    y_t = np.asarray(y_true, dtype=int)
    y_s = np.asarray(y_score, dtype=float)
    y_pred = (y_s >= threshold).astype(int)

    tn, fp, fn, tp = confusion_matrix(y_t, y_pred, labels=[0, 1]).ravel()
    recall_p90, p90_fallback = compute_recall_at_precision(y_t, y_s, min_precision=0.90)

    return {
        "pr_auc": float(average_precision_score(y_t, y_s)),
        "roc_auc": float(roc_auc_score(y_t, y_s)),
        "f1": float(f1_score(y_t, y_pred, zero_division=0)),
        "precision": float(precision_score(y_t, y_pred, zero_division=0)),
        "recall": float(recall_score(y_t, y_pred, zero_division=0)),
        "accuracy": float(accuracy_score(y_t, y_pred)),
        "recall_at_p90": recall_p90,
        "p90_fallback": bool(p90_fallback),
        "threshold": float(threshold),
        "tp": int(tp),
        "fp": int(fp),
        "tn": int(tn),
        "fn": int(fn),
    }
