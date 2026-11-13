"""Statistical opcode transition graph and descriptor extraction (F-GSTAT)."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence

import networkx as nx

from src.features.disasm import DisassemblyResult

GSTAT_FEATURE_NAMES: tuple[str, ...] = (
    "gstat_n_nodes",
    "gstat_n_edges",
    "gstat_density",
    "gstat_total_transitions",
    "gstat_mean_w_in_deg",
    "gstat_max_w_in_deg",
    "gstat_mean_w_out_deg",
    "gstat_max_w_out_deg",
    "gstat_transition_entropy",
    "gstat_self_loop_ratio",
    "gstat_nodes_norm",
    "gstat_edges_norm",
    "gstat_mean_w_in_deg_norm",
    "gstat_max_w_in_deg_norm",
    "gstat_mean_w_out_deg_norm",
    "gstat_max_w_out_deg_norm",
)


def build_transition_graph(mnemonics: Sequence[str]) -> tuple[nx.DiGraph, int]:
    """Build a weighted directed transition graph over consecutive opcodes.

    Returns ``(graph, total_transitions)`` where edge weight counts adjacent
    transitions ``u -> v`` in the mnemonic sequence.
    """
    graph = nx.DiGraph()
    n_inst = len(mnemonics)
    if n_inst == 0:
        return graph, 0
    if n_inst == 1:
        graph.add_node(mnemonics[0])
        return graph, 0

    edge_counts = Counter(zip(mnemonics[:-1], mnemonics[1:]))
    graph.add_weighted_edges_from(
        (u, v, float(w)) for (u, v), w in edge_counts.items()
    )
    return graph, n_inst - 1


def extract_gstat_features(
    disasm_res: DisassemblyResult,
    *,
    normalize: bool = True,
) -> dict[str, float]:
    """Extract 16 statistical descriptors from the opcode transition graph.

    Includes self-loop-aware density ``|E| / |V|^2``, weighted in/out degree stats,
    transition Shannon entropy (bits), self-loop weight ratio, and ``/ L``
    length-normalized variants to separate topology from bytecode size.
    """
    mnemonics = disasm_res.mnemonics(normalize=normalize)
    seq_len = len(mnemonics)
    if seq_len == 0:
        return {name: 0.0 for name in GSTAT_FEATURE_NAMES}

    graph, total_transitions = build_transition_graph(mnemonics)
    n_nodes = graph.number_of_nodes()
    n_edges = graph.number_of_edges()

    density = float(n_edges) / float(n_nodes * n_nodes) if n_nodes > 0 else 0.0

    if total_transitions == 0:
        mean_w_in = 0.0
        max_w_in = 0.0
        mean_w_out = 0.0
        max_w_out = 0.0
        entropy = 0.0
        self_loop_ratio = 0.0
    else:
        in_weights = [float(deg) for _, deg in graph.in_degree(weight="weight")]
        out_weights = [float(deg) for _, deg in graph.out_degree(weight="weight")]
        mean_w_in = sum(in_weights) / float(n_nodes)
        max_w_in = max(in_weights)
        mean_w_out = sum(out_weights) / float(n_nodes)
        max_w_out = max(out_weights)

        inv_total = 1.0 / float(total_transitions)
        entropy = 0.0
        self_loop_weight = 0.0
        for u, v, data in graph.edges(data=True):
            w = float(data["weight"])
            p = w * inv_total
            if p > 0.0:
                entropy -= p * math.log2(p)
            if u == v:
                self_loop_weight += w
        self_loop_ratio = self_loop_weight * inv_total

    inv_len = 1.0 / float(seq_len)
    return {
        "gstat_n_nodes": float(n_nodes),
        "gstat_n_edges": float(n_edges),
        "gstat_density": float(density),
        "gstat_total_transitions": float(total_transitions),
        "gstat_mean_w_in_deg": float(mean_w_in),
        "gstat_max_w_in_deg": float(max_w_in),
        "gstat_mean_w_out_deg": float(mean_w_out),
        "gstat_max_w_out_deg": float(max_w_out),
        "gstat_transition_entropy": float(entropy),
        "gstat_self_loop_ratio": float(self_loop_ratio),
        "gstat_nodes_norm": float(n_nodes) * inv_len,
        "gstat_edges_norm": float(n_edges) * inv_len,
        "gstat_mean_w_in_deg_norm": float(mean_w_in) * inv_len,
        "gstat_max_w_in_deg_norm": float(max_w_in) * inv_len,
        "gstat_mean_w_out_deg_norm": float(mean_w_out) * inv_len,
        "gstat_max_w_out_deg_norm": float(max_w_out) * inv_len,
    }
