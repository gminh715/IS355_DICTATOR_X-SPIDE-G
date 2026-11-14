"""Local PyEVM JSON-RPC bridge emulating Anvil (chainId=31337) on Windows.

Used when native Foundry `anvil.exe` is blocked by Application Control policy.
Seeds the exact Foundry/Anvil default test accounts (#0..#9) with 10,000 ETH each,
supports EIP-155/EIP-1559 raw transactions signed with chainId=31337 (for Web3.py
and MetaMask/ethers.js), and optionally deploys D1/D2/D3 to their deterministic
addresses matching `deployments.json`.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from eth_keys import keys
from eth_tester import EthereumTester, PyEVMBackend
from eth_tester.backends.pyevm.main import generate_genesis_state_for_keys
from eth_utils import to_hex
from web3 import Web3
from web3.providers.eth_tester import EthereumTesterProvider
from web3.providers.eth_tester.middleware import (
    request_formatters as ETH_TESTER_REQUEST_FORMATTERS,
    result_formatters as ETH_TESTER_RESULT_FORMATTERS,
    to_integer_if_hex,
)

from scripts.deploy_contracts import deploy_network

# Foundry/Anvil default accounts #0..#9 (TEST KEYS - LOCAL ANVIL ONLY).
ANVIL_TEST_PRIVATE_KEYS: tuple[str, ...] = (
    "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",  # #0 owner
    "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",  # #1 auditor 1
    "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",  # #2 auditor 2
    "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6",  # #3 auditor 3
    "0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a",  # #4
    "0x8b3a350cf5c34c9194ca85829a2df0ec3153be0318b5e2d3348e872092edffba",  # #5
    "0x92db14e403b83dfe3df233f83dfa3a0d7096f21ca9b0d6d6b8d88b2b4ec1564e",  # #6
    "0x4bbbf85ce3377467afe5d46f804f221813b2bb87f24d81f60f1fcdbf7cbf4356",  # #7
    "0xdbda1821b80551c9d65939329250298aa3472ba22feea921c0cf5d620ea67b97",  # #8
    "0x2a871d0798f97d79848a013d4936a73bf4cc922c825d33c1cf7073dff6d409c6",  # #9
)


def create_anvil_pyevm_tester() -> tuple[EthereumTester, Web3]:
    """Create an in-process PyEVM EthereumTester seeded with Anvil accounts and chain_id=31337."""
    priv_keys = [keys.PrivateKey(bytes.fromhex(pk[2:])) for pk in ANVIL_TEST_PRIVATE_KEYS]
    gstate = generate_genesis_state_for_keys(priv_keys)
    backend = PyEVMBackend(genesis_state=gstate)
    type(backend.chain).chain_id = 31337
    backend.account_keys = priv_keys
    tester = EthereumTester(backend)
    w3 = Web3(EthereumTesterProvider(tester))
    return tester, w3


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        return to_hex(bytes(value))
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if hasattr(value, "hex") and callable(value.hex):
        h = value.hex()
        return h if h.startswith("0x") else f"0x{h}"
    return value


def _encode_rpc_quantity(val: int) -> str:
    return hex(int(val))


def _format_rpc_scalars(value: Any) -> Any:
    """Recursively format Python ints/bytes into JSON-RPC hex strings while preserving bools and hex data."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return _encode_rpc_quantity(value)
    if isinstance(value, dict):
        return {k: _format_rpc_scalars(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_format_rpc_scalars(item) for item in value]
    return _to_jsonable(value)


def _format_rpc_result(method: str, result: Any) -> Any:
    """Apply EthereumTester result remapping (snake_case -> camelCase) and JSON-RPC hex formatting."""
    if result is None:
        return None
    formatter = ETH_TESTER_RESULT_FORMATTERS.get(method)
    if formatter is not None:
        result = formatter(result)
    return _format_rpc_scalars(result)


def _normalize_block_tag(tag: Any) -> Any:
    if tag in ("safe", "finalized"):
        return "latest"
    if isinstance(tag, str) and tag.startswith("0x"):
        return to_integer_if_hex(tag)
    return tag


def _normalize_rpc_params(
    method: str,
    params: list[Any],
    *,
    default_from: str = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
) -> list[Any]:
    """Decode JSON-RPC hex quantities and block tags into EthereumTester-compatible Python values."""
    args = list(params)
    if method in ("eth_call", "eth_estimateGas", "eth_sendTransaction", "eth_createAccessList"):
        if args and isinstance(args[0], dict):
            tx = {k: v for k, v in args[0].items() if v is not None}
            if "input" in tx and "data" not in tx:
                tx["data"] = tx.pop("input")
            tx.setdefault("from", default_from)
            args[0] = tx
        if len(args) > 1:
            args[1] = _normalize_block_tag(args[1])
    elif method in ("eth_getLogs", "eth_newFilter") and args and isinstance(args[0], dict):
        filt = {k: v for k, v in args[0].items() if v is not None}
        for key in ("fromBlock", "toBlock"):
            if key in filt:
                filt[key] = _normalize_block_tag(filt[key])
        args[0] = filt
    elif method == "eth_getStorageAt":
        if len(args) > 1:
            args[1] = to_integer_if_hex(args[1])
        if len(args) > 2:
            args[2] = _normalize_block_tag(args[2])
    elif method in (
        "eth_getBlockByNumber",
        "eth_getBlockTransactionCountByNumber",
        "eth_getUncleCountByBlockNumber",
        "eth_getTransactionByBlockNumberAndIndex",
    ) and args:
        args[0] = _normalize_block_tag(args[0])
    elif method in ("eth_getTransactionCount", "eth_getCode", "eth_getBalance") and len(args) > 1:
        args[1] = _normalize_block_tag(args[1])

    formatter = ETH_TESTER_REQUEST_FORMATTERS.get(method)
    if formatter is not None:
        args = list(formatter(args))
    return args


class PyEVMRPCBridge:
    """Thread-safe JSON-RPC dispatcher wrapping EthereumTesterProvider for chainId 31337."""

    def __init__(self, *, deploy_on_start: bool = False) -> None:
        self.lock = threading.Lock()
        self.tester, self.w3 = create_anvil_pyevm_tester()
        self.provider = self.w3.provider
        self.deployment_record: dict[str, Any] | None = None
        if deploy_on_start:
            self.deployment_record = self._deploy_default_contracts()

    def _deploy_default_contracts(self) -> dict[str, Any]:
        """Deploy D1, D2, D3 using owner (#0) and auditors (#1..#3) in deterministic nonce order."""
        from src.contracts.compiler import compile_contract

        owner = self.w3.eth.accounts[0]
        auditors = list(self.w3.eth.accounts[1:4])
        deployed: dict[str, Any] = {}
        for variant in ("D1", "D2", "D3"):
            compiled = compile_contract(variant, use_cache=True)
            factory = self.w3.eth.contract(abi=compiled.abi, bytecode=compiled.bytecode)
            rc_dep = self.w3.eth.wait_for_transaction_receipt(
                factory.constructor("0x0000000000000000000000000000000000000000").transact({"from": owner})
            )
            contract = self.w3.eth.contract(address=rc_dep.contractAddress, abi=compiled.abi)
            for aud in auditors:
                self.w3.eth.wait_for_transaction_receipt(
                    contract.functions.add_auditor(aud).transact({"from": owner})
                )
            self.w3.eth.wait_for_transaction_receipt(
                contract.functions.set_threshold(2).transact({"from": owner})
            )
            deployed[variant] = rc_dep.contractAddress
        return {"owner": owner, "auditors": auditors, "contracts": deployed}

    def handle_single(self, req: dict[str, Any]) -> dict[str, Any]:
        req_id = req.get("id")
        method = str(req.get("method", ""))
        params = req.get("params") or []

        try:
            with self.lock:
                if method == "eth_chainId":
                    return {"jsonrpc": "2.0", "id": req_id, "result": "0x7a69"}
                if method == "net_version":
                    return {"jsonrpc": "2.0", "id": req_id, "result": "31337"}
                if method == "web3_clientVersion":
                    return {"jsonrpc": "2.0", "id": req_id, "result": "X-SPIDE-G/PyEVM-AnvilBridge/31337"}
                if method == "eth_maxPriorityFeePerGas":
                    return {"jsonrpc": "2.0", "id": req_id, "result": "0x3b9aca00"}
                if method == "eth_feeHistory":
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "baseFeePerGas": ["0x3b9aca00", "0x3b9aca00"],
                            "gasUsedRatio": [0.1],
                            "oldestBlock": _encode_rpc_quantity(max(0, self.w3.eth.block_number)),
                            "reward": [["0x3b9aca00"]],
                        },
                    }
                params = _normalize_rpc_params(method, params)
                raw_resp = self.provider.make_request(method, params)
                if "error" in raw_resp:
                    return {"jsonrpc": "2.0", "id": req_id, "error": raw_resp["error"]}
                formatted = _format_rpc_result(method, raw_resp.get("result"))
                return {"jsonrpc": "2.0", "id": req_id, "result": formatted}
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(exc)},
            }


def start_rpc_server(
    host: str = "127.0.0.1",
    port: int = 8545,
    *,
    deploy_on_start: bool = True,
) -> tuple[ThreadingHTTPServer, PyEVMRPCBridge]:
    """Build a ThreadingHTTPServer serving the PyEVM Anvil bridge."""
    bridge = PyEVMRPCBridge(deploy_on_start=deploy_on_start)

    class Handler(BaseHTTPRequestHandler):
        def _send_cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self._send_cors()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            body = json.dumps(
                {
                    "status": "ok",
                    "chain_id": 31337,
                    "deployments": bridge.deployment_record,
                }
            ).encode("utf-8")
            self.send_response(200)
            self._send_cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
            if isinstance(payload, list):
                resp: Any = [bridge.handle_single(item) for item in payload]
            else:
                resp = bridge.handle_single(payload)
            body = json.dumps(resp).encode("utf-8")
            self.send_response(200)
            self._send_cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return None

    server = ThreadingHTTPServer((host, port), Handler)
    return server, bridge


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local PyEVM JSON-RPC bridge (chain_id=31337).")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8545)
    parser.add_argument("--no-deploy", action="store_true", help="Skip auto-deploying D1/D2/D3 on startup.")
    args = parser.parse_args()

    server, bridge = start_rpc_server(
        args.host,
        args.port,
        deploy_on_start=not args.no_deploy,
    )
    print(
        json.dumps(
            {
                "rpc_url": f"http://{args.host}:{args.port}",
                "chain_id": 31337,
                "deployments": bridge.deployment_record,
            },
            indent=2,
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
