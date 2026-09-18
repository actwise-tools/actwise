r"""Phase 3 live e2e — real streamable-HTTP wire path against a running MCP.

Proves, over the actual protocol the eve portal uses:
  * bad X-DOCenter-User signature -> 401 at _AuthGate (never reaches a tool)
  * alice (seeded from the shared cookie) -> real portal results
  * bob   (unseeded)                       -> SessionRequired tool error
  * no user header                         -> shared-cookie results (Copilot path)

Env in:  DOCENTER_MCP_URL, DOCENTER_PROXY_API_KEY, DOCENTER_USER_TOKEN_SECRET
Run:     py components\docenter\docenter_mcp\_phase3_e2e.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from docenter_mcp.user_token import mint_docenter_user_token

URL = os.environ.get("DOCENTER_MCP_URL", "http://127.0.0.1:8787/mcp")
API_KEY = os.environ["DOCENTER_PROXY_API_KEY"]
SECRET = os.environ["DOCENTER_USER_TOKEN_SECRET"]
QUERY = "purge alert"

_fail = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _fail
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}{('  ' + detail) if detail else ''}")
    if not cond:
        _fail += 1


async def call(user_header: str | None):
    """Return ('ok', count) | ('tool_error', text) | ('http_error', repr)."""
    headers = {"X-API-Key": API_KEY}
    if user_header is not None:
        headers["X-DOCenter-User"] = user_header
    try:
        async with streamablehttp_client(URL, headers=headers, timeout=60) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = await s.call_tool("search_docs", {"query": QUERY, "max_results": 3})
                text = " ".join(getattr(c, "text", "") for c in res.content)
                if res.isError:
                    return ("tool_error", text)
                # The tool serializes its result dict as JSON text content.
                try:
                    count = len(json.loads(text).get("results", []))
                except Exception:  # noqa: BLE001
                    count = None
                return ("ok", count)
    except Exception as exc:  # noqa: BLE001
        return ("http_error", f"{type(exc).__name__}: {exc}")


async def main() -> int:
    now = int(__import__("time").time())
    alice = mint_docenter_user_token("alice@example.com", SECRET)
    bob = mint_docenter_user_token("bob@example.com", SECRET)
    bad = alice[:-4] + ("AAAA" if not alice.endswith("AAAA") else "BBBB")

    print("bad signature -> 401 at gate:")
    kind, info = await call(bad)
    check("bad token rejected before any tool runs", kind == "http_error", f"({kind}: {info})")

    print("alice (seeded) -> results:")
    kind, info = await call(alice)
    check("alice gets real portal results", kind == "ok" and (info or 0) > 0, f"({kind}: {info} hits)")

    print("bob (unseeded) -> SessionRequired:")
    kind, info = await call(bob)
    check("bob gets a SessionRequired tool error",
          kind == "tool_error" and "bob@example.com" in str(info) and "login" in str(info).lower(),
          f"({kind}: {info})")

    print("no user header -> shared results (Copilot path):")
    kind, info = await call(None)
    check("shared-cookie path still returns results", kind == "ok" and (info or 0) > 0, f"({kind}: {info} hits)")

    print(f"\n{'ALL PASS' if _fail == 0 else str(_fail) + ' FAILED'}")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
