"""Two-level clone clustering: exact code_hash (group_exact) and MinHash LSH (group_near)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from datasketch import MinHash, MinHashLSH

from src.features.disasm import disassemble


class UnionFind:
    """Disjoint-set data structure with path compression and union by rank."""

    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


def opcode_shingles(code: bytes, k: int = 5) -> set[bytes]:
    """Extract unique normalized k-gram opcode shingles from stripped bytecode."""
    if not code:
        return set()
    mnemonics = disassemble(code, log_truncated=False).mnemonics(normalize=True)
    if not mnemonics:
        return set()
    if len(mnemonics) < k:
        return {"|".join(mnemonics).encode("ascii")}
    return {
        "|".join(mnemonics[i : i + k]).encode("ascii")
        for i in range(len(mnemonics) - k + 1)
    }


def compute_minhash(shingles: set[bytes], num_perm: int = 128) -> MinHash:
    """Compute a deterministic MinHash signature from byte shingles."""
    mh = MinHash(num_perm=num_perm)
    for sh in sorted(shingles):
        mh.update(sh)
    return mh


@dataclass(frozen=True)
class CloneGroupingResult:
    """Cluster IDs aligned to input contract list."""

    group_exact: list[str]
    group_near: list[str]
    exact_groups_count: int
    near_groups_count: int
    lsh_candidate_pairs: int
    verified_near_edges: int


def cluster_clones(
    code_hashes: list[str | None],
    stripped_codes: list[bytes],
    *,
    shingle_k: int = 5,
    num_perm: int = 128,
    jaccard_threshold: float = 0.90,
) -> CloneGroupingResult:
    """Assign deterministic group_exact and group_near labels for contracts.

    Contracts missing bytecode (code_hash is None or stripped_code empty) receive unique
    singleton IDs (`missing_<idx>`) so they are never falsely merged.
    """
    n = len(code_hashes)
    if len(stripped_codes) != n:
        raise ValueError("code_hashes and stripped_codes must have identical length")

    # Level 1: Exact code_hash grouping
    exact_map: dict[str, str] = {}
    group_exact: list[str] = []
    valid_indices: list[int] = []
    for idx, (ch, code) in enumerate(zip(code_hashes, stripped_codes)):
        if not ch or not code:
            group_exact.append(f"missing_{idx}")
        else:
            if ch not in exact_map:
                exact_map[ch] = f"exact_{len(exact_map):05d}"
            group_exact.append(exact_map[ch])
            valid_indices.append(idx)

    # Deduplicate by code_hash before MinHash LSH so identical bytecodes run once.
    hash_to_indices: dict[str, list[int]] = defaultdict(list)
    for idx in valid_indices:
        assert code_hashes[idx] is not None
        hash_to_indices[code_hashes[idx]].append(idx)

    unique_hashes = sorted(hash_to_indices.keys())
    uf = UnionFind(len(unique_hashes))

    shingle_sets: list[set[bytes]] = []
    minhashes: list[MinHash] = []
    lsh = MinHashLSH(threshold=jaccard_threshold, num_perm=num_perm)

    for u_idx, ch in enumerate(unique_hashes):
        rep_idx = hash_to_indices[ch][0]
        sh = opcode_shingles(stripped_codes[rep_idx], k=shingle_k)
        shingle_sets.append(sh)
        mh = compute_minhash(sh, num_perm=num_perm)
        minhashes.append(mh)
        if sh:
            lsh.insert(str(u_idx), mh)

    candidate_pairs = 0
    verified_edges = 0
    for u_idx in range(len(unique_hashes)):
        if not shingle_sets[u_idx]:
            continue
        candidates = lsh.query(minhashes[u_idx])
        for cand_str in candidates:
            v_idx = int(cand_str)
            if v_idx <= u_idx:
                continue
            candidate_pairs += 1
            a, b = shingle_sets[u_idx], shingle_sets[v_idx]
            union_sz = len(a | b)
            exact_jacc = (len(a & b) / union_sz) if union_sz else 0.0
            if exact_jacc >= jaccard_threshold:
                uf.union(u_idx, v_idx)
                verified_edges += 1

    # Map unique hashes -> canonical deterministic near_XXXXX IDs
    root_to_near_id: dict[int, str] = {}
    hash_to_near: dict[str, str] = {}
    for u_idx, ch in enumerate(unique_hashes):
        root = uf.find(u_idx)
        if root not in root_to_near_id:
            root_to_near_id[root] = f"near_{len(root_to_near_id):05d}"
        hash_to_near[ch] = root_to_near_id[root]

    group_near: list[str] = []
    for idx, ch in enumerate(code_hashes):
        if not ch or not stripped_codes[idx]:
            group_near.append(f"missing_{idx}")
        else:
            group_near.append(hash_to_near[ch])

    return CloneGroupingResult(
        group_exact=group_exact,
        group_near=group_near,
        exact_groups_count=len(exact_map),
        near_groups_count=len(root_to_near_id),
        lsh_candidate_pairs=candidate_pairs,
        verified_near_edges=verified_edges,
    )
