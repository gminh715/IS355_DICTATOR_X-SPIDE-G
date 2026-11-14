"""Sorted-pair Merkle tree helpers matching D3_MerkleBatch.vy."""

from __future__ import annotations

from typing import Sequence

from eth_abi import encode
from eth_utils import keccak


def _to_bytes32(value: bytes | str, name: str = "value") -> bytes:
    if isinstance(value, str):
        hex_str = value[2:] if value.startswith("0x") else value
        raw = bytes.fromhex(hex_str)
    else:
        raw = bytes(value)
    if len(raw) != 32:
        raise ValueError(f"{name} must be exactly 32 bytes, got {len(raw)}")
    return raw


def compute_leaf(
    case_id: bytes | str,
    evidence_hash: bytes | str,
    model_version_hash: bytes | str,
) -> bytes:
    """Compute keccak256(abi.encode(case_id, evidence_hash, model_version_hash))."""
    cid = _to_bytes32(case_id, "case_id")
    eh = _to_bytes32(evidence_hash, "evidence_hash")
    mh = _to_bytes32(model_version_hash, "model_version_hash")
    return bytes(keccak(encode(["bytes32", "bytes32", "bytes32"], [cid, eh, mh])))


def hash_pair(a: bytes, b: bytes) -> bytes:
    """Hash two 32-byte nodes in sorted unsigned integer order."""
    a32 = _to_bytes32(a, "left")
    b32 = _to_bytes32(b, "right")
    if int.from_bytes(a32, "big") <= int.from_bytes(b32, "big"):
        return bytes(keccak(a32 + b32))
    return bytes(keccak(b32 + a32))


def verify_merkle_proof(leaf: bytes | str, proof: Sequence[bytes | str], root: bytes | str) -> bool:
    """Verify a sorted-pair Merkle inclusion proof against a 32-byte root."""
    computed = _to_bytes32(leaf, "leaf")
    expected_root = _to_bytes32(root, "root")
    for sibling in proof:
        computed = hash_pair(computed, _to_bytes32(sibling, "sibling"))
    return computed == expected_root


class MerkleTree:
    """Balanced sorted-pair Merkle tree with odd-node promotion (no duplicate padding)."""

    def __init__(self, leaves: Sequence[bytes | str]) -> None:
        if not leaves:
            raise ValueError("MerkleTree requires at least one leaf")
        self.leaves: list[bytes] = [_to_bytes32(leaf, f"leaf[{i}]") for i, leaf in enumerate(leaves)]
        self.levels: list[list[bytes]] = [self.leaves]

        current = self.leaves
        while len(current) > 1:
            nxt: list[bytes] = []
            for idx in range(0, len(current), 2):
                if idx + 1 < len(current):
                    nxt.append(hash_pair(current[idx], current[idx + 1]))
                else:
                    # Odd trailing node promoted without duplicating leaves.
                    nxt.append(current[idx])
            self.levels.append(nxt)
            current = nxt

    @property
    def root(self) -> bytes:
        return self.levels[-1][0]

    def get_proof(self, index: int) -> list[bytes]:
        if index < 0 or index >= len(self.leaves):
            raise IndexError(f"Leaf index {index} out of range [0, {len(self.leaves)})")
        proof: list[bytes] = []
        idx = index
        for level in self.levels[:-1]:
            sibling_idx = idx ^ 1
            if sibling_idx < len(level):
                proof.append(level[sibling_idx])
            idx //= 2
        return proof
