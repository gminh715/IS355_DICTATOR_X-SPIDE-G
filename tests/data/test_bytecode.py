"""Unit tests for CBOR metadata stripping and keccak256 code hashing."""

from __future__ import annotations

import cbor2
from eth_utils import keccak

from src.data.bytecode import extract_runtime_from_initcode, parse_hex_bytecode, strip_cbor_metadata


def test_strip_cbor_with_valid_solidity_metadata() -> None:
    body = bytes.fromhex("6080604052600080fd")
    meta = cbor2.dumps({"ipfs": b"\x12\x20" + b"\xaa" * 32, "solc": b"\x00\x08\x1a"})
    full_code = body + meta + len(meta).to_bytes(2, "big")

    res = strip_cbor_metadata(full_code)
    assert res.metadata_stripped == "true"
    assert res.stripped_bytes == body
    assert res.code_hash == "0x" + keccak(body).hex()
    assert res.metadata_length == len(meta) + 2


def test_pre_047_bytecode_without_cbor_kept_intact() -> None:
    # Hand-written / pre-0.4.7 EVM bytecode ending in JUMPDEST STOP (no CBOR)
    legacy_code = bytes.fromhex("60606040525b00")
    res = strip_cbor_metadata(legacy_code)
    assert res.metadata_stripped == "false"
    assert res.stripped_bytes == legacy_code
    assert res.code_hash == "0x" + keccak(legacy_code).hex()
    assert res.metadata_length == 0


def test_missing_or_empty_bytecode() -> None:
    assert parse_hex_bytecode("0x") == b""
    assert parse_hex_bytecode(None) == b""
    res = strip_cbor_metadata(b"")
    assert res.metadata_stripped == "none"
    assert res.code_hash is None


def test_false_positive_length_footer_not_stripped() -> None:
    # Last 2 bytes look like length=5, but preceding 5 bytes are invalid CBOR / non-map
    body = bytes.fromhex("6080604052") + b"\x01\x02\x03\x04\x05" + (5).to_bytes(2, "big")
    res = strip_cbor_metadata(body)
    assert res.metadata_stripped == "false"
    assert res.stripped_bytes == body


def test_extract_runtime_from_initcode() -> None:
    runtime = bytes.fromhex("6080604052600080fd")
    # Classic Solidity initcode: PUSH1 <len>, DUP1, PUSH1 <offset>, PUSH1 0x00, CODECOPY, PUSH1 0x00, RETURN, STOP
    init_header = bytes.fromhex(f"60{len(runtime):02x}80600c6000396000f300")
    assert len(init_header) == 12
    extracted = extract_runtime_from_initcode(init_header + runtime)
    assert extracted == runtime

