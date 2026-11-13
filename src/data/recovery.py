"""Bytecode recovery helper via X-SPIDE repo, public RPC eth_getCode, and optional BigQuery/archive."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Sequence

DEFAULT_RPCS = (
    "https://ethereum-rpc.publicnode.com",
    "https://1rpc.io/eth",
)


def batch_eth_get_code(
    addresses: Sequence[str],
    *,
    rpcs: Sequence[str] = DEFAULT_RPCS,
    batch_size: int = 25,
    timeout: float = 10.0,
) -> dict[str, str]:
    """Query eth_getCode(address, 'latest') in JSON-RPC batches with RPC fallback."""
    results: dict[str, str] = {}
    addrs = [a.strip().lower() for a in addresses]
    for start in range(0, len(addrs), batch_size):
        chunk = addrs[start : start + batch_size]
        payload = json.dumps(
            [
                {
                    "jsonrpc": "2.0",
                    "method": "eth_getCode",
                    "params": [addr, "latest"],
                    "id": idx,
                }
                for idx, addr in enumerate(chunk)
            ]
        ).encode("utf-8")

        fetched = False
        for rpc in rpcs:
            try:
                req = urllib.request.Request(
                    rpc,
                    data=payload,
                    headers={"Content-Type": "application/json", "User-Agent": "x-spide-g/1.0"},
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    items = json.loads(resp.read().decode("utf-8"))
                if isinstance(items, list):
                    for item in items:
                        if "id" in item and "result" in item:
                            results[chunk[item["id"]]] = str(item["result"]).strip()
                    fetched = True
                    break
            except (urllib.error.URLError, TimeoutError, ValueError, OSError):
                continue

        if not fetched:
            for addr in chunk:
                results.setdefault(addr, "rpc_error")
    return results


def has_bigquery_credentials() -> bool:
    """Return True if GCP credentials appear configured for BigQuery fallback."""
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return os.path.exists(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
    appdata = os.environ.get("APPDATA", "")
    if appdata and os.path.exists(os.path.join(appdata, "gcloud", "application_default_credentials.json")):
        return True
    return False
