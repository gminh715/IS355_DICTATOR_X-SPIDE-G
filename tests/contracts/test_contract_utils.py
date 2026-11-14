"""Unit tests for contract compiler loader, Merkle tree utilities, and Python reference."""

from __future__ import annotations

import pytest
from eth_utils import keccak

from src.contracts.compiler import compile_contract
from src.contracts.merkle import MerkleTree, compute_leaf, verify_merkle_proof
from src.contracts.reference import (
    DECISION_APPROVE,
    DECISION_REJECT,
    STATUS_APPROVED,
    STATUS_DISPUTED,
    STATUS_OPEN,
    STATUS_REJECTED,
    compute_status,
)


def test_compile_contract_cache_and_artifacts() -> None:
    d1 = compile_contract("D1", use_cache=True)
    d2 = compile_contract("D2", use_cache=True)
    d3 = compile_contract("D3", use_cache=True)
    assert d1.vyper_version.startswith("0.4.")
    assert d2.vyper_version.startswith("0.4.")
    assert d3.vyper_version.startswith("0.4.")
    assert d1.bytecode.startswith("0x")
    assert len(d2.bytecode_runtime) < len(d1.bytecode_runtime)


def test_merkle_tree_edge_cases_and_validation() -> None:
    with pytest.raises(ValueError, match="at least one leaf"):
        MerkleTree([])
    with pytest.raises(ValueError, match="32 bytes"):
        compute_leaf(b"\x01", b"\x02" * 32, b"\x03" * 32)

    leaves = [keccak(f"leaf-{i}".encode()) for i in range(7)]
    tree = MerkleTree(leaves)
    with pytest.raises(IndexError):
        tree.get_proof(7)

    for i, leaf in enumerate(leaves):
        proof = tree.get_proof(i)
        assert verify_merkle_proof(leaf, proof, tree.root) is True
        assert verify_merkle_proof(keccak(b"wrong"), proof, tree.root) is False


def test_reference_compute_status_boundaries() -> None:
    assert compute_status(0, 0, 2) == STATUS_OPEN
    assert compute_status(1, 0, 2) == STATUS_OPEN
    assert compute_status(1, 1, 2) == STATUS_DISPUTED
    assert compute_status(2, 1, 2) == STATUS_APPROVED
    assert compute_status(0, 2, 2) == STATUS_REJECTED
    assert DECISION_APPROVE == 1 and DECISION_REJECT == 2
