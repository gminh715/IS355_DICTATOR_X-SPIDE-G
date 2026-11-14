"""Security boundary tests verifying no live keys touch Streamlit, signer, or evidence modules."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.evidence.chain_client import get_anvil_test_accounts

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_no_live_private_key_references_in_phase6_code() -> None:
    forbidden_tokens = (
        "SEPOLIA_DEPLOYER_PRIVATE_KEY",
        "L2_DEPLOYER_PRIVATE_KEY",
        "SEPOLIA_PRIVATE_KEY",
        "MAINNET_PRIVATE_KEY",
    )
    target_paths = [
        *REPO_ROOT.joinpath("app").rglob("*.py"),
        *REPO_ROOT.joinpath("src", "evidence").rglob("*.py"),
        REPO_ROOT / "signer" / "index.html",
    ]
    assert target_paths, "Expected Phase 6 source files to exist"
    for path in target_paths:
        text = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            assert token not in text, f"Forbidden live key token {token!r} found in {path}"


def test_anvil_keys_strictly_rejected_on_non_anvil_chain() -> None:
    class FakeEth:
        chain_id = 11155111

    class FakeW3:
        eth = FakeEth()

    with pytest.raises(RuntimeError, match="SECURITY GUARD"):
        get_anvil_test_accounts(FakeW3())  # type: ignore[arg-type]
