"""Basic-block Control Flow Graph construction and semantic features (F-GSEM)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import networkx as nx

from src.features.disasm import DisassemblyResult, Instruction
from src.features.gstat import build_transition_graph

_HARD_TERMINATORS = frozenset({"JUMP", "STOP", "RETURN", "REVERT", "SELFDESTRUCT", "INVALID"})
_ALL_TERMINATORS = _HARD_TERMINATORS | frozenset({"JUMPI"})

GSEM_FEATURE_NAMES: tuple[str, ...] = (
    "n_blocks",
    "n_cfg_edges",
    "cyclomatic",
    "n_scc_cycles",
    "n_loops_with_call",
    "has_loop_with_call",
    "n_loops_with_sstore",
    "path_callvalue_to_call",
    "n_blocks_with_call",
    "call_block_ratio",
    "pagerank_CALL",
    "pagerank_SSTORE",
    "has_selfdestruct",
    "selfdestruct_reachable",
    "unresolved_jump_ratio",
)


def _is_terminator(mnemonic: str) -> bool:
    return mnemonic in _ALL_TERMINATORS or mnemonic.startswith("INVALID_")


def _is_hard_terminator(mnemonic: str) -> bool:
    return mnemonic in _HARD_TERMINATORS or mnemonic.startswith("INVALID_")


@dataclass(frozen=True)
class BasicBlock:
    """Single-entry basic block of disassembled EVM instructions."""

    block_id: int
    start_pc: int
    end_pc: int
    instructions: tuple[Instruction, ...]
    has_call: bool
    has_sstore: bool
    has_callvalue: bool
    has_selfdestruct: bool
    terminator: str | None


@dataclass(frozen=True)
class CFGResult:
    """Recovered EVM basic-block CFG and jump-resolution diagnostics."""

    blocks: tuple[BasicBlock, ...]
    graph: nx.DiGraph
    pc_to_block_id: dict[int, int]
    valid_jumpdest_pcs: frozenset[int]
    total_jumps: int
    unresolved_jumps: int
    unresolved_jump_ratio: float


def _make_block(block_id: int, insts: list[Instruction]) -> BasicBlock:
    mnemonics = [inst.mnemonic for inst in insts]
    last_mnemonic = mnemonics[-1]
    return BasicBlock(
        block_id=block_id,
        start_pc=insts[0].pc,
        end_pc=insts[-1].pc,
        instructions=tuple(insts),
        has_call="CALL" in mnemonics,
        has_sstore="SSTORE" in mnemonics,
        has_callvalue="CALLVALUE" in mnemonics,
        has_selfdestruct="SELFDESTRUCT" in mnemonics,
        terminator=last_mnemonic if _is_terminator(last_mnemonic) else None,
    )


def _resolve_static_jump_target(block: BasicBlock) -> int | None:
    """Return static PUSH target immediately preceding JUMP/JUMPI, or None if dynamic."""
    if len(block.instructions) < 2:
        return None
    prev = block.instructions[-2]
    if prev.truncated:
        return None
    if prev.mnemonic == "PUSH0":
        return 0
    if prev.mnemonic.startswith("PUSH"):
        return int.from_bytes(prev.immediate, "big")
    return None


def build_cfg(disasm_res: DisassemblyResult) -> CFGResult:
    """Partition EVM instructions into basic blocks and recover static CFG edges."""
    instructions = disasm_res.instructions
    if not instructions:
        return CFGResult(
            blocks=(),
            graph=nx.DiGraph(),
            pc_to_block_id={},
            valid_jumpdest_pcs=frozenset(),
            total_jumps=0,
            unresolved_jumps=0,
            unresolved_jump_ratio=0.0,
        )

    blocks_list: list[BasicBlock] = []
    current: list[Instruction] = []
    for inst in instructions:
        if inst.mnemonic == "JUMPDEST" and current:
            blocks_list.append(_make_block(len(blocks_list), current))
            current = [inst]
        else:
            current.append(inst)

        if _is_terminator(inst.mnemonic):
            blocks_list.append(_make_block(len(blocks_list), current))
            current = []

    if current:
        blocks_list.append(_make_block(len(blocks_list), current))

    blocks = tuple(blocks_list)
    pc_to_block_id = {b.start_pc: b.block_id for b in blocks}
    valid_jumpdest_pcs = frozenset(
        b.start_pc for b in blocks if b.instructions[0].mnemonic == "JUMPDEST"
    )

    graph = nx.DiGraph()
    for b in blocks:
        graph.add_node(
            b.block_id,
            start_pc=b.start_pc,
            has_call=b.has_call,
            has_sstore=b.has_sstore,
            has_callvalue=b.has_callvalue,
            has_selfdestruct=b.has_selfdestruct,
        )

    total_jumps = 0
    unresolved_jumps = 0
    n_blocks = len(blocks)

    for idx, b in enumerate(blocks):
        last_mnemonic = b.instructions[-1].mnemonic
        # Fall-through edge exists unless halted or unconditional JUMP.
        if idx + 1 < n_blocks and not _is_hard_terminator(last_mnemonic):
            graph.add_edge(b.block_id, idx + 1)

        if last_mnemonic in {"JUMP", "JUMPI"}:
            total_jumps += 1
            target_pc = _resolve_static_jump_target(b)
            if target_pc is not None and target_pc in valid_jumpdest_pcs:
                graph.add_edge(b.block_id, pc_to_block_id[target_pc])
            else:
                unresolved_jumps += 1

    unresolved_ratio = float(unresolved_jumps) / float(total_jumps) if total_jumps > 0 else 0.0
    return CFGResult(
        blocks=blocks,
        graph=graph,
        pc_to_block_id=pc_to_block_id,
        valid_jumpdest_pcs=valid_jumpdest_pcs,
        total_jumps=total_jumps,
        unresolved_jumps=unresolved_jumps,
        unresolved_jump_ratio=unresolved_ratio,
    )


def _has_path_callvalue_to_call(cfg_res: CFGResult) -> bool:
    """Return True if any execution path runs CALLVALUE before CALL."""
    blocks = cfg_res.blocks
    graph = cfg_res.graph

    # 1. Intra-block ordering check: CALLVALUE strictly precedes CALL.
    for b in blocks:
        if b.has_callvalue and b.has_call:
            first_cv = next(
                i for i, inst in enumerate(b.instructions) if inst.mnemonic == "CALLVALUE"
            )
            last_call = max(
                i for i, inst in enumerate(b.instructions) if inst.mnemonic == "CALL"
            )
            if first_cv < last_call:
                return True

    # 2. Multi-source BFS across >= 1 CFG edges from every block with CALLVALUE.
    visited: set[int] = set()
    queue: deque[int] = deque()
    for b in blocks:
        if b.has_callvalue:
            for succ in graph.successors(b.block_id):
                if succ not in visited:
                    visited.add(succ)
                    queue.append(succ)

    while queue:
        node = queue.popleft()
        if blocks[node].has_call:
            return True
        for succ in graph.successors(node):
            if succ not in visited:
                visited.add(succ)
                queue.append(succ)

    return False


def _compute_opcode_pagerank(
    disasm_res: DisassemblyResult,
    *,
    normalize: bool,
) -> tuple[float, float]:
    """Compute PageRank scores of CALL and SSTORE in the mnemonic transition graph."""
    mnemonics = disasm_res.mnemonics(normalize=normalize)
    if not mnemonics:
        return 0.0, 0.0

    tgraph, _ = build_transition_graph(mnemonics)
    if tgraph.number_of_nodes() == 0:
        return 0.0, 0.0

    try:
        pr = nx.pagerank(tgraph, weight="weight", max_iter=300)
    except nx.PowerIterationFailedConvergence:
        pr = nx.pagerank(tgraph, weight="weight", max_iter=1000, tol=1e-4)

    return float(pr.get("CALL", 0.0)), float(pr.get("SSTORE", 0.0))


def extract_gsem_features(
    disasm_res: DisassemblyResult,
    *,
    normalize: bool = True,
) -> dict[str, float]:
    """Extract 15 semantic CFG and opcode-importance features (F-GSEM)."""
    cfg_res = build_cfg(disasm_res)
    blocks = cfg_res.blocks
    n_blocks = len(blocks)
    if n_blocks == 0:
        return {name: 0.0 for name in GSEM_FEATURE_NAMES}

    graph = cfg_res.graph
    n_edges = graph.number_of_edges()
    cyclomatic = float(n_edges - n_blocks + 2)

    loop_sccs: list[set[int]] = []
    for scc in nx.strongly_connected_components(graph):
        if len(scc) > 1:
            loop_sccs.append(scc)
        else:
            node = next(iter(scc))
            if graph.has_edge(node, node):
                loop_sccs.append(scc)

    n_scc_cycles = len(loop_sccs)
    n_loops_with_call = sum(
        1 for scc in loop_sccs if any(blocks[bid].has_call for bid in scc)
    )
    n_loops_with_sstore = sum(
        1 for scc in loop_sccs if any(blocks[bid].has_sstore for bid in scc)
    )

    n_blocks_with_call = sum(1 for b in blocks if b.has_call)
    call_block_ratio = float(n_blocks_with_call) / float(n_blocks)
    path_cv_call = 1.0 if _has_path_callvalue_to_call(cfg_res) else 0.0

    has_selfdestruct = any(b.has_selfdestruct for b in blocks)
    if has_selfdestruct:
        reachable = nx.descendants(graph, 0) | {0}
        selfdestruct_reachable = any(blocks[bid].has_selfdestruct for bid in reachable)
    else:
        selfdestruct_reachable = False

    pagerank_call, pagerank_sstore = _compute_opcode_pagerank(
        disasm_res, normalize=normalize
    )

    return {
        "n_blocks": float(n_blocks),
        "n_cfg_edges": float(n_edges),
        "cyclomatic": cyclomatic,
        "n_scc_cycles": float(n_scc_cycles),
        "n_loops_with_call": float(n_loops_with_call),
        "has_loop_with_call": 1.0 if n_loops_with_call > 0 else 0.0,
        "n_loops_with_sstore": float(n_loops_with_sstore),
        "path_callvalue_to_call": path_cv_call,
        "n_blocks_with_call": float(n_blocks_with_call),
        "call_block_ratio": call_block_ratio,
        "pagerank_CALL": pagerank_call,
        "pagerank_SSTORE": pagerank_sstore,
        "has_selfdestruct": 1.0 if has_selfdestruct else 0.0,
        "selfdestruct_reachable": 1.0 if selfdestruct_reachable else 0.0,
        "unresolved_jump_ratio": float(cfg_res.unresolved_jump_ratio),
    }
