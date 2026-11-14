"""Launch helper for Phase 6 DApp: static signer HTTP server + optional Anvil PyEVM RPC + Streamlit."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SIGNER_DIR = REPO_ROOT / "signer"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return None


def start_signer_http_server(host: str = "127.0.0.1", port: int = 8502) -> ThreadingHTTPServer:
    handler = partial(_QuietHandler, directory=str(SIGNER_DIR))
    server = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Start X-SPIDE-G Streamlit DApp and static MetaMask signer.")
    parser.add_argument("--streamlit-port", type=int, default=8501)
    parser.add_argument("--signer-port", type=int, default=8502)
    parser.add_argument("--with-anvil-rpc", action="store_true", help="Also start local PyEVM Anvil bridge on :8545.")
    parser.add_argument("--rpc-port", type=int, default=8545)
    args = parser.parse_args()

    rpc_server = None
    if args.with_anvil_rpc:
        from scripts.local_rpc_server import start_rpc_server

        rpc_server, bridge = start_rpc_server("127.0.0.1", args.rpc_port, deploy_on_start=True)
        threading.Thread(target=rpc_server.serve_forever, daemon=True).start()
        print(f"Local PyEVM RPC running at http://127.0.0.1:{args.rpc_port} (deployments={bridge.deployment_record})")

    signer_server = start_signer_http_server("127.0.0.1", args.signer_port)
    print(f"Static MetaMask signer serving {SIGNER_DIR} at http://127.0.0.1:{args.signer_port}/index.html")

    env = dict(os.environ)
    env["SIGNER_BASE_URL"] = f"http://127.0.0.1:{args.signer_port}/index.html"
    env.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(REPO_ROOT / "app" / "streamlit_app.py"),
                "--server.port",
                str(args.streamlit_port),
                "--server.headless",
                "true",
            ],
            cwd=REPO_ROOT,
            env=env,
            check=False,
        )
    finally:
        signer_server.shutdown()
        signer_server.server_close()
        if rpc_server is not None:
            rpc_server.shutdown()
            rpc_server.server_close()


if __name__ == "__main__":
    main()
