"""Unit tests for Phase 2 metrics, in-fold RFE selector, and leakage-free nested CV."""

from __future__ import annotations

import numpy as np
from sklearn.pipeline import Pipeline

from src.models.metrics import compute_recall_at_precision, evaluate_predictions, find_best_f1_threshold
from src.models.tuning import CachedRFESelector, run_nested_cv_fold


def test_recall_at_precision_and_fallback() -> None:
    y_true = np.array([1, 1, 1, 0, 0, 0, 0, 0])
    # Top 2 scores are true positives (precision=1.0, recall=2/3), 3rd is FP -> precision 2/3 < 0.90
    y_score = np.array([0.95, 0.90, 0.40, 0.80, 0.30, 0.20, 0.10, 0.05])
    r90, fb = compute_recall_at_precision(y_true, y_score, min_precision=0.90)
    assert fb is False
    assert abs(r90 - (2.0 / 3.0)) < 1e-9

    # Never reaches 0.90 precision at any recall > 0 (highest score is negative!)
    y_bad = np.array([0.5, 0.4, 0.3, 0.99, 0.2, 0.1, 0.05, 0.01])
    r_fb, fb2 = compute_recall_at_precision(y_true, y_bad, min_precision=0.90)
    assert fb2 is True
    assert r_fb == 0.0


def test_find_best_f1_threshold_consistent_with_eval() -> None:
    y_true = np.array([1, 1, 1, 0, 0, 0, 0, 0])
    y_score = np.array([0.92, 0.85, 0.78, 0.60, 0.30, 0.20, 0.10, 0.05])
    tau = find_best_f1_threshold(y_true, y_score)
    m = evaluate_predictions(y_true, y_score, tau)
    assert abs(m["f1"] - 1.0) < 1e-9


def test_cached_rfe_selector_pipeline_runs_strictly_in_fold() -> None:
    rng = np.random.default_rng(42)
    X = rng.normal(size=(120, 30))
    # Signal strictly in columns 0, 1, 2
    y = ((X[:, 0] + X[:, 1] - 0.5 * X[:, 2]) > 0.3).astype(int)
    cache: dict[str, np.ndarray] = {}
    sel = CachedRFESelector(n_features_to_select=10, step=5, min_features=5, ranking_cache=cache)
    pipe = Pipeline([("rfe", sel)])
    pipe.fit(X[:90], y[:90])
    Xt = pipe.transform(X[90:])
    assert Xt.shape == (30, 10)
    assert len(cache) == 1
    # Refitting on the exact same slice with different k hits the cache
    sel2 = CachedRFESelector(n_features_to_select=15, step=5, min_features=5, ranking_cache=cache)
    Xt2 = sel2.fit_transform(X[:90], y[:90])
    assert Xt2.shape == (90, 15)
    assert len(cache) == 1


def test_run_nested_cv_fold_smoke() -> None:
    rng = np.random.default_rng(7)
    n = 90
    X = rng.normal(size=(n, 25))
    y = ((X[:, 0] + 0.8 * X[:, 1]) > 0.7).astype(int)
    groups = np.repeat(np.arange(15), 6)
    tr_idx = np.arange(72)
    te_idx = np.arange(72, 90)
    row, pipe = run_nested_cv_fold(
        X,
        y,
        groups,
        tr_idx,
        te_idx,
        seed=42,
        fold=0,
        experiment_id="SMOKE",
        n_trials=3,
        n_inner_splits=3,
        n_jobs=1,
        use_rfe=False,
    )
    assert 0.0 <= row["PR-AUC"] <= 1.0
    assert 0.0 < row["threshold"] < 1.0
    assert row["n_features"] == 25
    assert hasattr(pipe, "predict_proba")
