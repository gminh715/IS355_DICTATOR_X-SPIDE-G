"""Unit tests for F-GSEM CFG construction and semantic features (gsem.py)."""

from __future__ import annotations

import networkx as nx
import pytest
import solcx

from src.data.bytecode import parse_hex_bytecode, strip_cbor_metadata
from src.features.disasm import disassemble
from src.features.gsem import GSEM_FEATURE_NAMES, build_cfg, extract_gsem_features

_HAS_SOLC_0826 = "0.8.26" in {str(v) for v in solcx.get_installed_solc_versions()}

_LOOP_PAY_SOL = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;
contract LoopPay {
    address payable[] public investors;
    function join() external payable {
        investors.push(payable(msg.sender));
    }
    function payout() external {
        for (uint256 i = 0; i < investors.length; i++) {
            investors[i].transfer(1 wei);
        }
    }
}
"""

_NO_LOOP_PAY_SOL = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;
contract NoLoopPay {
    address payable public recipient;
    constructor(address payable _recipient) {
        recipient = _recipient;
    }
    function payOnce() external payable {
        recipient.transfer(msg.value);
    }
}
"""


def _compile_runtime_features(source: str, *, optimize: bool) -> dict[str, float]:
    compiled = solcx.compile_source(
        source,
        output_values=["bin-runtime"],
        solc_version="0.8.26",
        optimize=optimize,
    )
    _, artifact = next(iter(compiled.items()))
    raw = parse_hex_bytecode(artifact["bin-runtime"])
    stripped = strip_cbor_metadata(raw)
    disasm_res = disassemble(stripped.stripped_bytes)
    return extract_gsem_features(disasm_res)


@pytest.mark.skipif(not _HAS_SOLC_0826, reason="solc 0.8.26 not installed")
@pytest.mark.parametrize("optimize", [False, True])
def test_solidity_loop_vs_noloop_contracts(optimize: bool) -> None:
    loop_feats = _compile_runtime_features(_LOOP_PAY_SOL, optimize=optimize)
    noloop_feats = _compile_runtime_features(_NO_LOOP_PAY_SOL, optimize=optimize)

    assert set(loop_feats.keys()) == set(GSEM_FEATURE_NAMES)
    assert loop_feats["has_loop_with_call"] == 1.0
    assert loop_feats["n_loops_with_call"] >= 1.0
    assert loop_feats["n_scc_cycles"] >= 1.0
    assert loop_feats["n_blocks_with_call"] >= 1.0
    assert loop_feats["cyclomatic"] >= 1.0

    assert noloop_feats["has_loop_with_call"] == 0.0
    assert noloop_feats["n_loops_with_call"] == 0.0
    assert noloop_feats["n_scc_cycles"] == 0.0
    assert noloop_feats["n_blocks_with_call"] >= 1.0
    assert noloop_feats["cyclomatic"] >= 1.0


def test_cfg_jump_resolution_and_unresolved_ratio() -> None:
    # Block 0: pc=0 PUSH1 0x05 (pc=2 JUMP) -> resolves to JUMPDEST at pc=5
    # Block 1: pc=3 POP (pc=4 STOP)  (dead/non-jumpdest block)
    # Block 2: pc=5 JUMPDEST, pc=6 PUSH1 0x00, pc=8 CALLDATALOAD, pc=9 JUMP (dynamic -> unresolved)
    # Total jumps = 2, unresolved = 1 -> ratio = 0.5
    # Byte layout:
    # 00: 60 05  (PUSH1 0x05)
    # 02: 56     (JUMP)
    # 03: 50     (POP)
    # 04: 00     (STOP)
    # 05: 5b     (JUMPDEST)
    # 06: 60 00  (PUSH1 0x00)
    # 08: 35     (CALLDATALOAD)
    # 09: 56     (JUMP)
    code = bytes.fromhex("60055650005b60003556")
    cfg = build_cfg(disassemble(code))
    assert len(cfg.blocks) == 3
    assert cfg.total_jumps == 2
    assert cfg.unresolved_jumps == 1
    assert cfg.unresolved_jump_ratio == pytest.approx(0.5)
    assert cfg.graph.has_edge(0, 2)
    assert not cfg.graph.has_edge(0, 1)


def test_path_callvalue_to_call_ordering_and_reachability() -> None:
    # Intra-block CALLVALUE -> POP -> CALL (with dummy zeros via PUSH1 0 -> POP): path = 1.0
    # 34 (CALLVALUE), 60 00 (PUSH1 0), 60 00, 60 00, 60 00, 60 00, 60 00, 60 00, f1 (CALL), 00 (STOP)
    c_fwd = bytes.fromhex("34f100")
    assert extract_gsem_features(disassemble(c_fwd))["path_callvalue_to_call"] == 1.0

    # Intra-block reverse order CALL then CALLVALUE, no loop: path = 0.0
    c_rev = bytes.fromhex("f13400")
    assert extract_gsem_features(disassemble(c_rev))["path_callvalue_to_call"] == 0.0

    # Disconnected dead CALL block after STOP: CALLVALUE cannot reach CALL -> path = 0.0
    c_dead = bytes.fromhex("34005bf100")
    assert extract_gsem_features(disassemble(c_dead))["path_callvalue_to_call"] == 0.0

    # Cross-block reachability: CALLVALUE; PUSH1 0x04; JUMP | STOP | JUMPDEST; CALL; STOP
    # 00: 34 60 05 56 00 5b f1 00
    c_cross = bytes.fromhex("34600556005bf100")
    f_cross = extract_gsem_features(disassemble(c_cross))
    assert f_cross["path_callvalue_to_call"] == 1.0
    assert f_cross["pagerank_CALL"] > 0.0


def test_selfdestruct_reachability_and_empty_guard() -> None:
    # Reachable SELFDESTRUCT
    f_reach = extract_gsem_features(disassemble(bytes.fromhex("33ff")))
    assert f_reach["has_selfdestruct"] == 1.0
    assert f_reach["selfdestruct_reachable"] == 1.0

    # Unreachable SELFDESTRUCT hidden behind STOP
    f_dead = extract_gsem_features(disassemble(bytes.fromhex("005b33ff")))
    assert f_dead["has_selfdestruct"] == 1.0
    assert f_dead["selfdestruct_reachable"] == 0.0

    # Empty bytecode guard
    f_empty = extract_gsem_features(disassemble(b""))
    assert set(f_empty.keys()) == set(GSEM_FEATURE_NAMES)
    assert all(val == 0.0 for val in f_empty.values())


def test_cyclomatic_complexity_connected_and_fragmented_cfgs() -> None:
    """Verify multi-component McCabe formula M = E - V + 2P on P=1 and P>1 CFGs."""
    # 1. Connected single block (V=1, E=0, P=1) -> M = 1.0
    f_single = extract_gsem_features(disassemble(bytes.fromhex("600100")))
    assert (f_single["n_blocks"], f_single["n_cfg_edges"], f_single["cyclomatic"]) == (1.0, 0.0, 1.0)

    # 2. Connected single-block self-loop (V=1, E=1, P=1): JUMPDEST; PUSH1 0x00; JUMP -> M = 2.0
    f_selfloop = extract_gsem_features(disassemble(bytes.fromhex("5b600056")))
    assert (f_selfloop["n_blocks"], f_selfloop["n_cfg_edges"], f_selfloop["cyclomatic"]) == (1.0, 1.0, 2.0)

    # 3. Connected if-else diamond (V=4, E=4, P=1) -> M = 4 - 4 + 2(1) = 2.0
    # 00: 60 01 60 09 57  (PUSH1 1; PUSH1 9; JUMPI -> fallthrough to 5, jump to 9)
    # 05: 50 60 0b 56     (POP; PUSH1 11; JUMP -> jump to 11)
    # 09: 5b 50           (JUMPDEST; POP -> fallthrough to 11)
    # 0b: 5b 00           (JUMPDEST; STOP)
    diamond_dis = disassemble(bytes.fromhex("600160095750600b565b505b00"))
    diamond_cfg = build_cfg(diamond_dis)
    assert nx.number_weakly_connected_components(diamond_cfg.graph) == 1
    f_diamond = extract_gsem_features(diamond_dis)
    assert (f_diamond["n_blocks"], f_diamond["n_cfg_edges"], f_diamond["cyclomatic"]) == (4.0, 4.0, 2.0)

    # 4. Fragmented CFG from dynamic indirect jumps (V=4, E=0, P=4):
    #    Old formula E - V + 2 would yield -2.0; multi-component formula yields 0 - 4 + 2(4) = 4.0.
    frag_dis = disassemble(bytes.fromhex("600035565b602035565b604035565b00"))
    frag_cfg = build_cfg(frag_dis)
    n_comp_frag = nx.number_weakly_connected_components(frag_cfg.graph)
    assert n_comp_frag == 4
    assert frag_cfg.unresolved_jump_ratio == pytest.approx(1.0)
    f_frag = extract_gsem_features(frag_dis)
    assert f_frag["n_blocks"] == 4.0
    assert f_frag["n_cfg_edges"] == 0.0
    assert f_frag["cyclomatic"] == 4.0
    assert f_frag["cyclomatic"] >= float(n_comp_frag) >= 1.0

    # 5. Mixed fragmented CFG: 2-block static cycle + 2 disconnected blocks (V=4, E=2, P=3) -> M = 4.0
    # 00: 5b 60 04 56     (JUMPDEST; PUSH1 4; JUMP -> 0->1)
    # 04: 5b 60 00 56     (JUMPDEST; PUSH1 0; JUMP -> 1->0)
    # 08: 5b 60 00 35 56  (JUMPDEST; PUSH1 0; CALLDATALOAD; JUMP -> unresolved)
    # 0d: 5b 00           (JUMPDEST; STOP)
    mixed_dis = disassemble(bytes.fromhex("5b6004565b6000565b600035565b00"))
    mixed_cfg = build_cfg(mixed_dis)
    assert nx.number_weakly_connected_components(mixed_cfg.graph) == 3
    f_mixed = extract_gsem_features(mixed_dis)
    assert (f_mixed["n_blocks"], f_mixed["n_cfg_edges"], f_mixed["cyclomatic"]) == (4.0, 2.0, 4.0)
    assert f_mixed["n_scc_cycles"] == 1.0
