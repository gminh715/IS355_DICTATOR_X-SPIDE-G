"""Deterministic Vyper 0.4.x compiler wrapper and artifact loader."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = REPO_ROOT / "contracts" / "artifacts"

CONTRACT_PATHS: dict[str, Path] = {
    "D1": REPO_ROOT / "contracts" / "RiskAttestationRegistry.vy",
    "RiskAttestationRegistry": REPO_ROOT / "contracts" / "RiskAttestationRegistry.vy",
    "D2": REPO_ROOT / "contracts" / "variants" / "D2_EventOnly.vy",
    "D2_EventOnly": REPO_ROOT / "contracts" / "variants" / "D2_EventOnly.vy",
    "D3": REPO_ROOT / "contracts" / "variants" / "D3_MerkleBatch.vy",
    "D3_MerkleBatch": REPO_ROOT / "contracts" / "variants" / "D3_MerkleBatch.vy",
}

CANONICAL_NAMES: dict[str, str] = {
    "D1": "RiskAttestationRegistry",
    "RiskAttestationRegistry": "RiskAttestationRegistry",
    "D2": "D2_EventOnly",
    "D2_EventOnly": "D2_EventOnly",
    "D3": "D3_MerkleBatch",
    "D3_MerkleBatch": "D3_MerkleBatch",
}


@dataclass(frozen=True)
class CompiledContract:
    """Compiled Vyper contract metadata, ABI, and EVM bytecode."""

    name: str
    source_path: str
    source_sha256: str
    vyper_version: str
    abi: list[dict[str, Any]]
    bytecode: str
    bytecode_runtime: str
    layout: dict[str, Any]
    method_identifiers: dict[str, str]
    settings_dict: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "vyper_version": self.vyper_version,
            "abi": self.abi,
            "bytecode": self.bytecode,
            "bytecode_runtime": self.bytecode_runtime,
            "layout": self.layout,
            "method_identifiers": self.method_identifiers,
            "settings_dict": self.settings_dict,
        }


def find_vyper_binary() -> str:
    """Locate the Vyper 0.4.x compiler executable."""
    env_bin = os.environ.get("VYPER_BIN", "").strip()
    if env_bin and Path(env_bin).is_file():
        return env_bin

    on_path = shutil.which("vyper")
    if on_path:
        return on_path

    candidates = [
        Path.home() / ".local" / "bin" / "vyper.exe",
        Path.home() / ".local" / "bin" / "vyper",
        REPO_ROOT / ".venv" / "Scripts" / "vyper.exe",
        REPO_ROOT / ".venv" / "bin" / "vyper",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    raise FileNotFoundError(
        "Vyper compiler binary not found. Set VYPER_BIN or install Vyper 0.4.x on PATH."
    )


def _resolve_source(name_or_path: str | Path) -> tuple[str, Path]:
    key = str(name_or_path)
    if key in CONTRACT_PATHS:
        return CANONICAL_NAMES[key], CONTRACT_PATHS[key]
    p = Path(name_or_path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return p.stem, p.resolve()


def compile_contract(
    name_or_path: str | Path,
    *,
    use_cache: bool = True,
    write_artifact: bool = False,
) -> CompiledContract:
    """Compile a Vyper contract (or load matching cached artifact) and return ABI/bytecode."""
    canonical_name, src_path = _resolve_source(name_or_path)
    if not src_path.is_file():
        raise FileNotFoundError(f"Vyper source file not found: {src_path}")

    source_bytes = src_path.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    rel_path = src_path.relative_to(REPO_ROOT).as_posix()
    artifact_path = ARTIFACTS_DIR / f"{canonical_name}.json"

    if use_cache and artifact_path.is_file():
        cached = json.loads(artifact_path.read_text(encoding="utf-8"))
        if cached.get("source_sha256") == source_sha256:
            return CompiledContract(**cached)

    vyper_bin = find_vyper_binary()
    proc = subprocess.run(
        [vyper_bin, "-f", "combined_json", rel_path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Vyper compilation failed for {rel_path} (exit {proc.returncode}):\n{proc.stderr}"
        )

    raw = json.loads(proc.stdout)
    vyper_version = str(raw.get("version", "unknown"))
    entry_keys = [k for k in raw if k != "version"]
    if len(entry_keys) != 1:
        raise RuntimeError(f"Unexpected combined_json keys for {rel_path}: {entry_keys}")
    entry = raw[entry_keys[0]]

    compiled = CompiledContract(
        name=canonical_name,
        source_path=rel_path,
        source_sha256=source_sha256,
        vyper_version=vyper_version,
        abi=entry["abi"],
        bytecode=entry["bytecode"],
        bytecode_runtime=entry["bytecode_runtime"],
        layout=entry.get("layout", {}),
        method_identifiers=entry.get("method_identifiers", {}),
        settings_dict=entry.get("settings_dict", {}),
    )

    if write_artifact:
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(
            json.dumps(compiled.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    return compiled


def compile_all_contracts(*, write_artifacts: bool = True) -> dict[str, CompiledContract]:
    """Compile D1, D2, and D3 contracts and optionally write JSON artifacts."""
    return {
        alias: compile_contract(alias, use_cache=False, write_artifact=write_artifacts)
        for alias in ("D1", "D2", "D3")
    }
