r"""Door-3 offline proof — client-side capture ingest (POST /ingest), no browser.

Deterministic. Exercises the employee-SSO client-capture contract with fakes:
  A. POST /ingest rejects a bad/expired state (400) and an unconfigured broker (503).
  B. A COMPLETED payload (ZD__userAuthenticated=true + _SESSION) authorized by a
     signed one-time state → 200, stored under the STATE's user_id (R2), _SESSION
     round-trips through the per-user store.
  C. An INCOMPLETE payload (pre-auth _SESSION only / missing cookies) → 400 and is
     NOT stored (can't poison the store with a forged/half-baked cookie set).
  D. One-time: a second /ingest with the same state → 409.
  E. GET /connect renders the employee "connect from your own device" door with the
     copy-paste `docenter auth connect` command carrying the broker base + state.

Run from repo root:  py components\portal\broker\_ingest_proof.py
"""
from __future__ import annotations

import os
import sys
import tempfile

SECRET = "ingest-proof-secret"
ALICE = "alice@niceactimize.com"
MALLORY = "mallory@evil.example"

_fail = 0


def check(label: str, cond: bool) -> None:
    global _fail
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        _fail += 1


def _payload(authed: bool) -> dict:
    cookies = [{"name": "_SESSION", "value": "sess-xyz", "domain": ".niceactimize.com",
                "path": "/", "expires": 4102444800, "httpOnly": True, "secure": True}]
    cookies.append({"name": "ZD__userAuthenticated",
                    "value": "true" if authed else "false",
                    "domain": ".niceactimize.com", "path": "/"})
    return {"data": {"cookies": cookies}}


def main() -> int:
    store = tempfile.mkdtemp(prefix="ingest-proof-")
    os.environ["DOCENTER_USER_STORE_DIR"] = store
    os.environ["DOCENTER_BROKER_SECRET"] = SECRET

    from fastapi.testclient import TestClient

    from docenter_broker import app as broker_app
    from docenter_broker.state import sign_state
    from docenter_mcp import user_store

    client = TestClient(broker_app.app)

    # ── A. auth / state failures ─────────────────────────────────────────────
    print("A. state + config guards:")
    check("bad state → 400", client.post(
        "/ingest", json={"state": "v1.bad.sig", "payload": _payload(True)}).status_code == 400)

    saved = os.environ.pop("DOCENTER_BROKER_SECRET", None)
    with TestClient(broker_app.app) as c_unset:
        r = c_unset.post("/ingest", json={"state": "x", "payload": _payload(True)})
        check("503 when broker secret unset", r.status_code == 503)
    os.environ["DOCENTER_BROKER_SECRET"] = saved or SECRET

    # ── B. completed payload → stored under the STATE's user (R2) ─────────────
    print("B. completed capture → per-user store (R2 user from state):")
    st = sign_state(ALICE, SECRET)
    ok = client.post("/ingest", json={"state": st, "payload": _payload(True)})
    check("200 with completed payload + valid state", ok.status_code == 200)
    body = ok.json()
    check("response user_id is the STATE's user (not a client field)", body.get("user_id") == ALICE)
    check("response status connected", body.get("status") == "connected")
    stored = user_store.load_user_cookie_data(ALICE)
    names = {ck["name"] for ck in (stored or {}).get("data", {}).get("cookies", [])}
    check("per-user cookie written with _SESSION", "_SESSION" in names)

    # ── C. incomplete / malformed payloads → 400, not stored ─────────────────
    print("C. incomplete payloads rejected (no store poisoning):")
    st_m = sign_state(MALLORY, SECRET)
    pre_auth = client.post("/ingest", json={"state": st_m, "payload": _payload(False)})
    check("pre-auth (_SESSION only, ZD=false) → 400", pre_auth.status_code == 400)
    check("nothing stored for the rejected user", user_store.load_user_cookie_data(MALLORY) is None)

    st_m2 = sign_state(MALLORY, SECRET)
    empty = client.post("/ingest", json={"state": st_m2, "payload": {"data": {"cookies": []}}})
    check("missing cookies[] → 400", empty.status_code == 400)
    check("still nothing stored for the rejected user", user_store.load_user_cookie_data(MALLORY) is None)

    # ── D. one-time use ──────────────────────────────────────────────────────
    print("D. one-time state:")
    again = client.post("/ingest", json={"state": st, "payload": _payload(True)})
    check("second /ingest with the same state → 409", again.status_code == 409)

    # ── E. connect page renders the employee door + command ──────────────────
    print("E. /connect employee door (Door 3 UI):")
    os.environ["BROKER_PUBLIC_BASE"] = "https://broker.actwise.example"
    st_page = sign_state(ALICE, SECRET)
    page = client.get(f"/connect?state={st_page}")
    check("/connect renders the employee 'connect from your own device' door",
          page.status_code == 200 and "connect from your own device" in page.text)
    check("page shows the docenter auth connect command with broker base + state",
          "docenter auth connect --broker https://broker.actwise.example --state " in page.text
          and st_page in page.text)
    os.environ.pop("BROKER_PUBLIC_BASE", None)

    print()
    if _fail:
        print(f"RESULT: {_fail} check(s) FAILED")
        return 1
    print("RESULT: all checks PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
