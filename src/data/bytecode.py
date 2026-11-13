"""Bytecode normalization, CBOR metadata stripping, and keccak256 hashing."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Literal

import cbor2
from eth_utils import keccak

from src.features.disasm import disassemble

MetadataStatus = Literal["true", "false", "none"]

# Recognized keys inside Solidity / Vyper CBOR metadata maps (Solidity >= 0.4.7).
KNOWN_METADATA_KEYS = frozenset(
    {"ipfs", "bzzr0", "bzzr1", "solc", "vyper", "experimental", "abi"}
)


@dataclass(frozen=True)
class StrippedBytecode:
    """Result of stripping trailing CBOR metadata from deployed EVM bytecode."""

    raw_bytes: bytes
    stripped_bytes: bytes
    metadata_stripped: MetadataStatus
    code_hash: str | None
    metadata_length: int = 0


def parse_hex_bytecode(hex_str: str | None) -> bytes:
    """Parse a hex string (with or without 0x) into raw bytes; returns b'' for empty/missing."""
    if hex_str is None:
        return b""
    s = str(hex_str).strip()
    if not s or s.lower() in {"nan", "none", "null", "0x"}:
        return b""
    if s.startswith(("0x", "0X")):
        s = s[2:]
    if len(s) % 2 != 0:
        raise ValueError(f"Odd-length bytecode hex string (len={len(s)})")
    return bytes.fromhex(s)


def strip_cbor_metadata(code: bytes) -> StrippedBytecode:
    """Strip trailing Solidity/Vyper CBOR metadata if and only if it decodes cleanly.

    Contracts compiled prior to Solidity ~0.4.7 or hand-written assembly may have no
    CBOR footer; those are preserved intact with metadata_stripped='false'.
    """
    if not code:
        return StrippedBytecode(
            raw_bytes=b"",
            stripped_bytes=b"",
            metadata_stripped="none",
            code_hash=None,
            metadata_length=0,
        )

    if len(code) > 2:
        meta_len = int.from_bytes(code[-2:], "big")
        if 0 < meta_len <= len(code) - 2:
            meta_start = len(code) - 2 - meta_len
            meta_bytes = code[meta_start:-2]
            try:
                bio = io.BytesIO(meta_bytes)
                decoded = cbor2.load(bio)
                consumed_all = bio.tell() == len(meta_bytes)
                if consumed_all and isinstance(decoded, dict) and decoded:
                    str_keys = {str(k) for k in decoded.keys()}
                    if str_keys & KNOWN_METADATA_KEYS or all(isinstance(k, str) for k in decoded.keys()):
                        stripped = code[:meta_start]
                        if stripped:
                            return StrippedBytecode(
                                raw_bytes=code,
                                stripped_bytes=stripped,
                                metadata_stripped="true",
                                code_hash="0x" + keccak(stripped).hex(),
                                metadata_length=meta_len + 2,
                            )
            except Exception:
                pass

    return StrippedBytecode(
        raw_bytes=code,
        stripped_bytes=code,
        metadata_stripped="false",
        code_hash="0x" + keccak(code).hex(),
        metadata_length=0,
    )


def extract_runtime_from_initcode(creation_code: bytes) -> bytes | None:
    """Extract deployed runtime bytecode from Solidity creation initcode via CODECOPY pattern.

    Returns None when the initcode layout cannot be matched cleanly.
    """
    if not creation_code:
        return None
    insts = disassemble(creation_code, log_truncated=False).instructions
    for i in range(4, len(insts)):
        if insts[i].mnemonic != "CODECOPY":
            continue
        m4, m3, m2, m1 = (
            insts[i - 4].mnemonic,
            insts[i - 3].mnemonic,
            insts[i - 2].mnemonic,
            insts[i - 1].mnemonic,
        )
        if m4.startswith("PUSH") and m3 == "DUP1" and m2.startswith("PUSH") and m1 in ("PUSH0", "PUSH1"):
            size = int.from_bytes(insts[i - 4].immediate, "big") if insts[i - 4].immediate else 0
            offset = int.from_bytes(insts[i - 2].immediate, "big") if insts[i - 2].immediate else 0
            if 0 < offset < len(creation_code) and size > 0 and offset + size <= len(creation_code):
                return creation_code[offset : offset + size]
        if m2.startswith("PUSH") and m1 in ("PUSH0", "PUSH1"):
            offset = int.from_bytes(insts[i - 2].immediate, "big") if insts[i - 2].immediate else 0
            if m3.startswith("PUSH"):
                size = int.from_bytes(insts[i - 3].immediate, "big") if insts[i - 3].immediate else 0
                if 0 < offset < len(creation_code) and size > 0 and offset + size <= len(creation_code):
                    return creation_code[offset : offset + size]
            elif 0 < offset < len(creation_code) and creation_code[offset : offset + 4] in (
                b"\x60\x60\x60\x40",
                b"\x60\x80\x60\x40",
            ):
                return creation_code[offset:]
    return None

