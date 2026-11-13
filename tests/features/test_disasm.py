"""Unit tests for the minimal EVM disassembler (Phase 1.5 & Phase 3.1)."""

from __future__ import annotations

import logging

from src.features.disasm import disassemble, normalize_mnemonic


def test_five_handcrafted_bytecodes() -> None:
    # 1. PUSH0, CALLVALUE, ISZERO, PUSH1 0x0a, JUMPI, STOP
    c1 = bytes.fromhex("5f3415600a5700")
    r1 = disassemble(c1)
    assert [(i.pc, i.mnemonic) for i in r1.instructions] == [
        (0, "PUSH0"),
        (1, "CALLVALUE"),
        (2, "ISZERO"),
        (3, "PUSH1"),
        (5, "JUMPI"),
        (6, "STOP"),
    ]
    assert r1.mnemonics(normalize=True) == ["PUSH0", "CALLVALUE", "ISZERO", "PUSH", "JUMPI", "STOP"]

    # 2. PUSH4 selector, DUP1, EQ, SWAP1, LOG2, RETURN
    c2 = bytes.fromhex("63deadbeef801490a2f3")
    r2 = disassemble(c2)
    assert r2.mnemonics(normalize=False) == ["PUSH4", "DUP1", "EQ", "SWAP1", "LOG2", "RETURN"]
    assert r2.mnemonics(normalize=True) == ["PUSH", "DUP", "EQ", "SWAP", "LOG", "RETURN"]

    # 3. CALLER, SELFDESTRUCT
    c3 = bytes.fromhex("33ff")
    r3 = disassemble(c3)
    assert r3.mnemonics(normalize=True) == ["CALLER", "SELFDESTRUCT"]

    # 4. PUSH2 0x0007, JUMP, INVALID(0xFE), JUMPDEST, STOP
    c4 = bytes.fromhex("61000756fe5b00")
    r4 = disassemble(c4)
    assert [(i.pc, i.mnemonic) for i in r4.instructions] == [
        (0, "PUSH2"),
        (3, "JUMP"),
        (4, "INVALID"),
        (5, "JUMPDEST"),
        (6, "STOP"),
    ]
    assert r4.designated_invalid_count == 1
    assert r4.invalid_opcode_count == 0

    # 5. Unmapped opcodes 0x0C, 0xEF alongside valid PUSH0
    c5 = bytes.fromhex("5f0cef00")
    r5 = disassemble(c5)
    assert r5.mnemonics(normalize=True) == ["PUSH0", "INVALID_0C", "INVALID_EF", "STOP"]
    assert r5.invalid_opcode_count == 2


def test_truncated_push32_logged_and_counted(caplog) -> None:
    # PUSH32 (0x7F) followed by only 4 bytes instead of 32
    code = bytes.fromhex("7f11223344")
    with caplog.at_level(logging.WARNING):
        res = disassemble(code)
    assert res.truncated_push_count == 1
    assert len(res.instructions) == 1
    assert res.instructions[0].mnemonic == "PUSH32"
    assert res.instructions[0].truncated is True
    assert res.instructions[0].immediate == bytes.fromhex("11223344")
    assert "Truncated PUSH32" in caplog.text


def test_normalize_mnemonic_preserves_push0() -> None:
    assert normalize_mnemonic("PUSH0") == "PUSH0"
    assert normalize_mnemonic("PUSH1") == "PUSH"
    assert normalize_mnemonic("PUSH32") == "PUSH"
    assert normalize_mnemonic("DUP16") == "DUP"
    assert normalize_mnemonic("SWAP12") == "SWAP"
    assert normalize_mnemonic("LOG4") == "LOG"
