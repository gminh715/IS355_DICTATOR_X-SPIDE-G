"""Unit tests for F-BIGRAM (bigram.py) and F-GSTAT (gstat.py)."""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest
from sklearn.base import clone

from src.features.bigram import (
    BigramTopKVectorizer,
    extract_bigram_frequencies,
    extract_bigram_row,
)
from src.features.disasm import disassemble
from src.features.gstat import GSTAT_FEATURE_NAMES, extract_gstat_features


def test_bigram_relative_frequencies_sum_to_one() -> None:
    # PUSH1 0x60, PUSH1 0x40, MSTORE  -> normalized ["PUSH", "PUSH", "MSTORE"]
    code = bytes.fromhex("6060604052")
    res = disassemble(code)

    norm_freqs = extract_bigram_frequencies(res, normalize=True)
    assert norm_freqs == {"PUSH|PUSH": pytest.approx(0.5), "PUSH|MSTORE": pytest.approx(0.5)}
    assert sum(norm_freqs.values()) == pytest.approx(1.0)

    # Distinct PUSH widths remain distinct when normalize=False (S4 sensitivity).
    code_diff_push = bytes.fromhex("600161000200")  # PUSH1 0x01, PUSH2 0x0002, STOP
    res2 = disassemble(code_diff_push)
    assert extract_bigram_frequencies(res2, normalize=True) == {
        "PUSH|PUSH": pytest.approx(0.5),
        "PUSH|STOP": pytest.approx(0.5),
    }
    assert extract_bigram_frequencies(res2, normalize=False) == {
        "PUSH1|PUSH2": pytest.approx(0.5),
        "PUSH2|STOP": pytest.approx(0.5),
    }


def test_bigram_empty_and_single_instruction_guards() -> None:
    empty_res = disassemble(b"")
    assert extract_bigram_frequencies(empty_res) == {}
    row_empty = extract_bigram_row(empty_res)
    assert row_empty["bigram_total_norm"] == 0
    assert json.loads(str(row_empty["bigram_freq_norm_json"])) == {}

    single_res = disassemble(b"\x00")  # STOP
    assert extract_bigram_frequencies(single_res) == {}
    row_single = extract_bigram_row(single_res)
    assert row_single["bigram_total_norm"] == 0
    assert row_single["bigram_unique_norm"] == 0


def test_bigram_topk_vectorizer_leakage_free() -> None:
    # Train docs: "PUSH|JUMPI" (DF=3), "CALLVALUE|ISZERO" (DF=2), "ADD|SSTORE" (DF=1).
    train_df = pd.DataFrame(
        {
            "bigram_freq_norm_json": [
                json.dumps({"PUSH|JUMPI": 0.6, "CALLVALUE|ISZERO": 0.4}),
                json.dumps({"PUSH|JUMPI": 0.5, "CALLVALUE|ISZERO": 0.5}),
                json.dumps({"PUSH|JUMPI": 0.2, "ADD|SSTORE": 0.8}),
                json.dumps({}),
            ]
        }
    )
    # Test docs introduce a frequent unseen bigram "SELFDESTRUCT|STOP" (DF_test=2).
    test_df = pd.DataFrame(
        {
            "bigram_freq_norm_json": [
                json.dumps({"PUSH|JUMPI": 0.25, "SELFDESTRUCT|STOP": 0.75}),
                json.dumps({"CALLVALUE|ISZERO": 0.9, "SELFDESTRUCT|STOP": 0.1}),
            ]
        }
    )

    vec = BigramTopKVectorizer(top_k=2, column="bigram_freq_norm_json")
    cloned = clone(vec)
    X_train = cloned.fit_transform(train_df)
    X_test = cloned.transform(test_df)

    # Top-2 must come strictly from training DF, ignoring ADD|SSTORE and test-only tokens.
    assert cloned.vocabulary_ == ("PUSH|JUMPI", "CALLVALUE|ISZERO")
    assert list(cloned.get_feature_names_out()) == [
        "bigram__PUSH|JUMPI",
        "bigram__CALLVALUE|ISZERO",
    ]
    assert X_train.shape == (4, 2)
    np.testing.assert_allclose(
        X_train,
        [[0.6, 0.4], [0.5, 0.5], [0.2, 0.0], [0.0, 0.0]],
    )
    np.testing.assert_allclose(
        X_test,
        [[0.25, 0.0], [0.0, 0.9]],
    )


def test_gstat_hand_computed_values() -> None:
    # Instructions: PUSH1 01, PUSH1 02, ADD, PUSH1 03, STOP -> ["PUSH", "PUSH", "ADD", "PUSH", "STOP"]
    # L = 5, T = 4 transitions: PUSH->PUSH, PUSH->ADD, ADD->PUSH, PUSH->STOP
    res = disassemble(bytes.fromhex("6001600201600300"))
    feats = extract_gstat_features(res, normalize=True)

    assert set(feats.keys()) == set(GSTAT_FEATURE_NAMES)
    assert feats["gstat_n_nodes"] == 3.0
    assert feats["gstat_n_edges"] == 4.0
    assert feats["gstat_total_transitions"] == 4.0
    assert feats["gstat_density"] == pytest.approx(4.0 / 9.0)
    assert feats["gstat_self_loop_ratio"] == pytest.approx(1.0 / 4.0)
    assert feats["gstat_transition_entropy"] == pytest.approx(2.0)  # -4 * (0.25 * log2(0.25))
    assert feats["gstat_mean_w_in_deg"] == pytest.approx(4.0 / 3.0)
    assert feats["gstat_max_w_in_deg"] == pytest.approx(2.0)
    assert feats["gstat_mean_w_out_deg"] == pytest.approx(4.0 / 3.0)
    assert feats["gstat_max_w_out_deg"] == pytest.approx(3.0)
    # Length-normalized (/ L where L = 5)
    assert feats["gstat_nodes_norm"] == pytest.approx(3.0 / 5.0)
    assert feats["gstat_edges_norm"] == pytest.approx(4.0 / 5.0)
    assert feats["gstat_mean_w_in_deg_norm"] == pytest.approx(4.0 / 15.0)
    assert feats["gstat_max_w_in_deg_norm"] == pytest.approx(2.0 / 5.0)
    assert feats["gstat_mean_w_out_deg_norm"] == pytest.approx(4.0 / 15.0)
    assert feats["gstat_max_w_out_deg_norm"] == pytest.approx(3.0 / 5.0)


def test_gstat_empty_and_single_instruction_guards() -> None:
    empty_feats = extract_gstat_features(disassemble(b""))
    assert all(val == 0.0 and not math.isnan(val) for val in empty_feats.values())

    single_feats = extract_gstat_features(disassemble(b"\x00"))
    assert single_feats["gstat_n_nodes"] == 1.0
    assert single_feats["gstat_n_edges"] == 0.0
    assert single_feats["gstat_density"] == 0.0
    assert single_feats["gstat_nodes_norm"] == 1.0
    assert single_feats["gstat_transition_entropy"] == 0.0
