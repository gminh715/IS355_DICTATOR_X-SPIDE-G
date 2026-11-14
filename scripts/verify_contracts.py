"""Verify deployed Vyper contracts on Etherscan v2 / Sourcify for Sepolia and L2 testnets."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from eth_abi import encode

from src.contracts.compiler import CONTRACT_PATHS, find_vyper_binary

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENTS_PATH = REPO_ROOT / "deployments.json"

CHAIN_IDS: dict[str, int] = {
    "sepolia": 11155111,
    "arbitrum-sepolia": 421614,
    "base-sepolia": 84532,
}


def build_vyper_standard_json(source_path: Path) -> str:
    """Invoke `vyper -f solc_json` to produce Etherscan-compatible standard JSON."""
    vyper_bin = find_vyper_binary()
    rel = source_path.relative_to(REPO_ROOT).as_posix()
    proc = subprocess.run(
        [vyper_bin, "-f", "solc_json", rel],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


def verify_on_etherscan_v2(
    *,
    network: str,
    variant: str,
    contract_info: dict[str, Any],
    api_key: str,
) -> dict[str, Any]:
    chain_id = CHAIN_IDS[network]
    src_path = CONTRACT_PATHS[variant]
    solc_json_str = build_vyper_standard_json(src_path)
    owner_arg = contract_info.get("constructor_arg_initial_owner") or (
        contract_info["owner"]
        if contract_info["owner"].lower() != contract_info["deployer"].lower()
        else "0x0000000000000000000000000000000000000000"
    )
    ctor_args_hex = encode(["address"], [owner_arg]).hex()

    query_params = {
        "chainid": chain_id,
        "module": "contract",
        "action": "verifysourcecode",
        "apikey": api_key,
    }
    payload = {
        "contractaddress": contract_info["address"],
        "sourceCode": solc_json_str,
        "codeformat": "vyper-json",
        "contractname": f"{src_path.relative_to(REPO_ROOT).as_posix()}:{contract_info['contract_name']}",
        "compilerversion": f"vyper:{contract_info['vyper_version']}",
        "optimizationUsed": "0",
        "constructorArguments": ctor_args_hex,
    }
    resp = requests.post(
        "https://api.etherscan.io/v2/api",
        params=query_params,
        data=payload,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "1":
        raise RuntimeError(f"Etherscan verify submission failed: {data}")

    guid = data["result"]
    for _ in range(12):
        time.sleep(5)
        check = requests.get(
            "https://api.etherscan.io/v2/api",
            params={
                "chainid": chain_id,
                "module": "contract",
                "action": "checkverifystatus",
                "guid": guid,
                "apikey": api_key,
            },
            timeout=20,
        )
        check.raise_for_status()
        status_json = check.json()
        result_msg = str(status_json.get("result", ""))
        if "Pending" not in result_msg:
            return {"guid": guid, "status_response": status_json}
    return {"guid": guid, "status_response": "pending_timeout"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify X-SPIDE-G contracts on Etherscan v2.")
    parser.add_argument("--network", choices=list(CHAIN_IDS.keys()), required=True)
    parser.add_argument("--variants", nargs="+", choices=["D1", "D2", "D3"], default=["D1", "D2", "D3"])
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    api_key = os.environ.get("ETHERSCAN_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ETHERSCAN_API_KEY is missing from environment/.env")
    if not DEPLOYMENTS_PATH.is_file():
        raise FileNotFoundError(f"Deployments manifest not found: {DEPLOYMENTS_PATH}")

    deployments = json.loads(DEPLOYMENTS_PATH.read_text(encoding="utf-8"))
    net_entry = deployments.get("networks", {}).get(args.network)
    if not net_entry:
        raise KeyError(f"No deployed records found for network={args.network} in deployments.json")

    for variant in args.variants:
        info = net_entry["contracts"].get(variant)
        if not info:
            continue
        res = verify_on_etherscan_v2(
            network=args.network,
            variant=variant,
            contract_info=info,
            api_key=api_key,
        )
        status_resp = res.get("status_response")
        info["verified_explorer"] = isinstance(status_resp, dict) and status_resp.get("status") == "1"
        info["verification_receipt"] = res
        print(variant, res)

    DEPLOYMENTS_PATH.write_text(json.dumps(deployments, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
