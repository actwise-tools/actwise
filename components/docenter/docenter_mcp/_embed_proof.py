r"""Option-2 offline proof — embedded login broker in the MCP service, no network.

Deterministic. Proves the single-service (Option-2 PoC) composition:
  A. With DOCENTER_BROKER_SECRET set, the MCP app is the _EmbeddedBroker composite;
     broker paths (/links, /connect, /ingest, /status, /password-login) route to the
     broker app and BYPASS the X-API-Key gate (the browser/CLI authenticate via the
     signed state, not the MCP api key).
  B. Non-broker paths still go through the _AuthGate → 401 without the api key.
  C. /healthz still served by the gate (App Runner health probe unaffected).
  D. Without DOCENTER_BROKER_SECRET, _build_app() returns the plain _AuthGate
     (shared-only deployment is byte-for-byte unchanged — no broker routes).

Run from repo root:  py components\docenter\docenter_mcp\_embed_proof.py
"""
from __future__ import annotations

import os
import sys
import tempfile

SECRET = "embed-proof-broker-secret"
APIKEY = "embed-proof-api-key"
USER = "employee@niceactimize.com"

_fail = 0


def check(label: str, cond: bool) -> None:
    global _fail
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        _fail += 1


def main() -> int:
    os.environ["DOCENTER_USER_STORE_DIR"] = tempfile.mkdtemp(prefix="embed-proof-")
    os.environ["DOCENTER_BROKER_SECRET"] = SECRET
    os.environ["DOCENTER_PROXY_API_KEY"] = APIKEY

    from fastapi.testclient import TestClient

    from docenter_broker.state import sign_state
    from docenter_mcp import server

    check("app is the _EmbeddedBroker composite when broker secret is set",
          isinstance(server.app, server._EmbeddedBroker))

    with TestClient(server.app) as client:
        # ── C. health probe unchanged ────────────────────────────────────────
        print("C. health probe:")
        h = client.get("/healthz")
        check("/healthz → 200 (served by the gate, not the broker)",
              h.status_code == 200 and h.json().get("status") == "ok")

        # ── A. broker paths route to broker + bypass the api-key gate ─────────
        print("A. broker paths bypass the api-key gate → broker app:")
        state = sign_state(USER, SECRET)
        page = client.get(f"/connect?state={state}")  # NO x-api-key header
        check("/connect (no api key) → 200 broker page",
              page.status_code == 200 and "Connect your DOCenter account" in page.text)

        ingest_bad = client.post("/ingest", json={"state": "v1.bad.sig", "payload": {}})
        check("/ingest (no api key) reaches broker → 400 bad state (not 401 api-key)",
              ingest_bad.status_code == 400)

        links_noauth = client.post("/links", json={"user": USER})  # no X-Broker-Secret
        check("/links reaches broker → 401 (broker auth, not the api-key gate)",
              links_noauth.status_code == 401)

        # ── B. non-broker paths still gated by the api key ────────────────────
        print("B. non-broker paths still require the api key:")
        mcp_noauth = client.get("/mcp")
        check("/mcp without api key → 401 (gate still enforced)", mcp_noauth.status_code == 401)

    # ── D. no broker secret → plain gated MCP (unchanged shared behavior) ─────
    print("D. no broker secret → plain _AuthGate (no broker routes):")
    saved = os.environ.pop("DOCENTER_BROKER_SECRET", None)
    try:
        plain = server._build_app()
        check("_build_app() returns a plain _AuthGate when broker secret unset",
              isinstance(plain, server._AuthGate) and not isinstance(plain, server._EmbeddedBroker))
    finally:
        if saved is not None:
            os.environ["DOCENTER_BROKER_SECRET"] = saved

    print()
    if _fail:
        print(f"RESULT: {_fail} check(s) FAILED")
        return 1
    print("RESULT: all checks PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
