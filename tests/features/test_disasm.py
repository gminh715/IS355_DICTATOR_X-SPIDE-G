"""Unit tests for the minimal EVM disassembler (Phase 1.5 & Phase 3.1)."""

from __future__ import annotations

import logging

from src.data.bytecode import parse_hex_bytecode, strip_cbor_metadata
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


# Real Ethereum mainnet deployed bytecodes from S_code (contracts.parquet),
# cross-verified against Blockscout/Etherscan compiler metadata and ABI selectors.
_ICONOMI_BLACKHOLE_HEX = (
    "0x60606040525b600080fd00a165627a7a72305820cee253ae5729fcba5fd1b3734104fd68"
    "43fb85193a15bcff328578338a6a27940029"
)
_COUNTER_HEX = (
    "0x60606040526000357c01000000000000000000000000000000000000000000000000000000"
    "00900463ffffffff168063371303c01460475780636d4ce63c146059575b600080fd5b341560"
    "5157600080fd5b6057607f565b005b3415606357600080fd5b6069608e565b60405180828152"
    "60200191505060405180910390f35b6001600054016000819055505b565b6000805490505b90"
    "5600a165627a7a7230582012b9d9f8a085ab3f977d753548b23c92cfa7b7428f50be99b53a51"
    "63609b7b980029"
)
_EASYINVEST_HEX = (
    "0x60806040523360009081526020819052604081205481901560715733600090815260016020"
    "908152604080832054918390529091205461170c914303906064906004020402811515604c57"
    "fe5b6040519190049250339150819083156108fc029084906000818181858888f15050505050"
    "5b50503360009081526001602090815260408083204390559082905290208054340190550000"
    "a165627a7a723058206d6a4a0755167514c9121e502f530a3534f7141b8832f5a73dc4250111"
    "a9e5390029"
)
# Pre-0.4.7 mainnet contract (no CBOR metadata trailer, SimpleStorage set/get selectors).
_PRE047_SIMPLESTORAGE_HEX = (
    "0x606060405260e060020a600035046360fe47b1811460245780636d4ce63c14602e575b00"
    "5b6004356000556022565b6000546060908152602090f3"
)


def test_three_real_mainnet_contracts_verified() -> None:
    # 1. IconomiBlackHole (0x0006157838d5a6b33ab66588a6a693a57c869999, Solidity 0.4.12)
    blackhole_stripped = strip_cbor_metadata(parse_hex_bytecode(_ICONOMI_BLACKHOLE_HEX))
    assert blackhole_stripped.metadata_stripped == "true"
    r1 = disassemble(blackhole_stripped.stripped_bytes)
    assert r1.invalid_opcode_count == 0
    assert r1.truncated_push_count == 0
    assert [(i.pc, i.mnemonic, i.immediate.hex()) for i in r1.instructions] == [
        (0, "PUSH1", "60"),
        (2, "PUSH1", "40"),
        (4, "MSTORE", ""),
        (5, "JUMPDEST", ""),
        (6, "PUSH1", "00"),
        (8, "DUP1", ""),
        (9, "REVERT", ""),
        (10, "STOP", ""),
    ]

    # 2. Counter (0x67001700b122b44012de9cf7d7fa3338fe9265b3, Solidity 0.4.13)
    counter_stripped = strip_cbor_metadata(parse_hex_bytecode(_COUNTER_HEX))
    assert counter_stripped.metadata_stripped == "true"
    r2 = disassemble(counter_stripped.stripped_bytes)
    assert len(r2.instructions) == 91
    assert r2.invalid_opcode_count == 0
    assert r2.truncated_push_count == 0
    push4_selectors = {i.immediate.hex() for i in r2.instructions if i.mnemonic == "PUSH4"}
    assert "371303c0" in push4_selectors  # inc()
    assert "6d4ce63c" in push4_selectors  # get()
    assert "SSTORE" in r2.mnemonics(normalize=False)
    assert "SLOAD" in r2.mnemonics(normalize=False)

    # 3. EasyInvest Ponzi (0x7b307c1f0039f5d38770e15f8043b3dd26da5e8f, Solidity 0.4.24)
    easy_stripped = strip_cbor_metadata(parse_hex_bytecode(_EASYINVEST_HEX))
    assert easy_stripped.metadata_stripped == "true"
    r3 = disassemble(easy_stripped.stripped_bytes)
    assert len(r3.instructions) == 128
    assert r3.invalid_opcode_count == 0
    assert r3.designated_invalid_count == 1
    assert r3.truncated_push_count == 0
    mn3 = r3.mnemonics(normalize=False)
    assert mn3.count("CALL") == 1
    assert mn3.count("CALLVALUE") == 1
    assert mn3.count("SSTORE") == 2
    assert mn3.count("SLOAD") == 4
    assert mn3.count("NUMBER") == 2


def test_disasm_with_vs_without_cbor_metadata() -> None:
    # With CBOR trailer: raw bytes contain Swarm hash bytes that decode as spurious INVALID_*
    raw_blackhole = parse_hex_bytecode(_ICONOMI_BLACKHOLE_HEX)
    raw_res = disassemble(raw_blackhole)
    stripped_blackhole = strip_cbor_metadata(raw_blackhole)
    stripped_res = disassemble(stripped_blackhole.stripped_bytes)
    assert stripped_blackhole.metadata_stripped == "true"
    assert len(raw_res.instructions) == 25
    assert raw_res.invalid_opcode_count == 9
    assert len(stripped_res.instructions) == 8
    assert stripped_res.invalid_opcode_count == 0

    raw_easy = parse_hex_bytecode(_EASYINVEST_HEX)
    stripped_easy = strip_cbor_metadata(raw_easy)
    assert disassemble(raw_easy).invalid_opcode_count == 7
    assert disassemble(stripped_easy.stripped_bytes).invalid_opcode_count == 0

    # Without CBOR trailer (pre-0.4.7 contract): stripping is a no-op and instructions match
    raw_pre047 = parse_hex_bytecode(_PRE047_SIMPLESTORAGE_HEX)
    st_pre047 = strip_cbor_metadata(raw_pre047)
    assert st_pre047.metadata_stripped == "false"
    assert st_pre047.stripped_bytes == raw_pre047
    r_pre = disassemble(st_pre047.stripped_bytes)
    assert len(r_pre.instructions) == 38
    assert r_pre.invalid_opcode_count == 0
    push4_selectors = {i.immediate.hex() for i in r_pre.instructions if i.mnemonic == "PUSH4"}
    assert push4_selectors == {"60fe47b1", "6d4ce63c"}  # set(uint256), get()
