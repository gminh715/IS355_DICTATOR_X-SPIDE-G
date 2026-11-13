"""Minimal, verified EVM bytecode disassembler supporting PUSH0 and truncated PUSH logging."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Standard EVM opcode table (up to Cancun, including Shanghai PUSH0 = 0x5F).
OPCODES: dict[int, str] = {
    0x00: "STOP",
    0x01: "ADD",
    0x02: "MUL",
    0x03: "SUB",
    0x04: "DIV",
    0x05: "SDIV",
    0x06: "MOD",
    0x07: "SMOD",
    0x08: "ADDMOD",
    0x09: "MULMOD",
    0x0A: "EXP",
    0x0B: "SIGNEXTEND",
    0x10: "LT",
    0x11: "GT",
    0x12: "SLT",
    0x13: "SGT",
    0x14: "EQ",
    0x15: "ISZERO",
    0x16: "AND",
    0x17: "OR",
    0x18: "XOR",
    0x19: "NOT",
    0x1A: "BYTE",
    0x1B: "SHL",
    0x1C: "SHR",
    0x1D: "SAR",
    0x20: "KECCAK256",
    0x30: "ADDRESS",
    0x31: "BALANCE",
    0x32: "ORIGIN",
    0x33: "CALLER",
    0x34: "CALLVALUE",
    0x35: "CALLDATALOAD",
    0x36: "CALLDATASIZE",
    0x37: "CALLDATACOPY",
    0x38: "CODESIZE",
    0x39: "CODECOPY",
    0x3A: "GASPRICE",
    0x3B: "EXTCODESIZE",
    0x3C: "EXTCODECOPY",
    0x3D: "RETURNDATASIZE",
    0x3E: "RETURNDATACOPY",
    0x3F: "EXTCODEHASH",
    0x40: "BLOCKHASH",
    0x41: "COINBASE",
    0x42: "TIMESTAMP",
    0x43: "NUMBER",
    0x44: "PREVRANDAO",
    0x45: "GASLIMIT",
    0x46: "CHAINID",
    0x47: "SELFBALANCE",
    0x48: "BASEFEE",
    0x49: "BLOBHASH",
    0x4A: "BLOBBASEFEE",
    0x50: "POP",
    0x51: "MLOAD",
    0x52: "MSTORE",
    0x53: "MSTORE8",
    0x54: "SLOAD",
    0x55: "SSTORE",
    0x56: "JUMP",
    0x57: "JUMPI",
    0x58: "PC",
    0x59: "MSIZE",
    0x5A: "GAS",
    0x5B: "JUMPDEST",
    0x5C: "TLOAD",
    0x5D: "TSTORE",
    0x5E: "MCOPY",
    0x5F: "PUSH0",
    0xF0: "CREATE",
    0xF1: "CALL",
    0xF2: "CALLCODE",
    0xF3: "RETURN",
    0xF4: "DELEGATECALL",
    0xF5: "CREATE2",
    0xFA: "STATICCALL",
    0xFD: "REVERT",
    0xFE: "INVALID",
    0xFF: "SELFDESTRUCT",
}

for _i in range(1, 33):
    OPCODES[0x5F + _i] = f"PUSH{_i}"
for _i in range(1, 17):
    OPCODES[0x7F + _i] = f"DUP{_i}"
    OPCODES[0x8F + _i] = f"SWAP{_i}"
for _i in range(0, 5):
    OPCODES[0xA0 + _i] = f"LOG{_i}"


@dataclass(frozen=True)
class Instruction:
    """Single decoded EVM instruction."""

    pc: int
    opcode: int
    mnemonic: str
    immediate: bytes = b""
    truncated: bool = False


@dataclass(frozen=True)
class DisassemblyResult:
    """Decoded instruction stream plus diagnostic counts."""

    instructions: tuple[Instruction, ...]
    invalid_opcode_count: int
    designated_invalid_count: int
    truncated_push_count: int

    def mnemonics(self, normalize: bool = True) -> list[str]:
        """Return opcode mnemonic sequence (optionally normalized)."""
        if not normalize:
            return [inst.mnemonic for inst in self.instructions]
        return [normalize_mnemonic(inst.mnemonic) for inst in self.instructions]


def normalize_mnemonic(mnemonic: str) -> str:
    """Collapse numbered instruction families while preserving PUSH0."""
    if mnemonic == "PUSH0":
        return "PUSH0"
    if mnemonic.startswith("PUSH") and mnemonic[4:].isdigit():
        return "PUSH"
    if mnemonic.startswith("DUP") and mnemonic[3:].isdigit():
        return "DUP"
    if mnemonic.startswith("SWAP") and mnemonic[4:].isdigit():
        return "SWAP"
    if mnemonic.startswith("LOG") and mnemonic[3:].isdigit():
        return "LOG"
    return mnemonic


def disassemble(code: bytes, *, log_truncated: bool = True) -> DisassemblyResult:
    """Disassemble deployed EVM bytecode bytes into instructions."""
    instructions: list[Instruction] = []
    invalid_count = 0
    designated_invalid = 0
    truncated_count = 0

    n = len(code)
    pc = 0
    while pc < n:
        op = code[pc]
        if 0x60 <= op <= 0x7F:
            imm_len = op - 0x5F
            mnemonic = f"PUSH{imm_len}"
            start = pc + 1
            end = start + imm_len
            truncated = end > n
            imm = code[start:min(end, n)]
            if truncated:
                truncated_count += 1
                if log_truncated:
                    logger.warning(
                        "Truncated %s immediate at offset %d (expected %d bytes, got %d)",
                        mnemonic,
                        pc,
                        imm_len,
                        len(imm),
                    )
            instructions.append(
                Instruction(pc=pc, opcode=op, mnemonic=mnemonic, immediate=imm, truncated=truncated)
            )
            pc = end
        else:
            mnemonic = OPCODES.get(op)
            if mnemonic is None:
                mnemonic = f"INVALID_{op:02X}"
                invalid_count += 1
            elif op == 0xFE:
                designated_invalid += 1
            instructions.append(Instruction(pc=pc, opcode=op, mnemonic=mnemonic))
            pc += 1

    return DisassemblyResult(
        instructions=tuple(instructions),
        invalid_opcode_count=invalid_count,
        designated_invalid_count=designated_invalid,
        truncated_push_count=truncated_count,
    )
