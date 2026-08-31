r"""Phase 4 offline proof — DOCenter login broker (no real browser, no real login).

Deterministic. Exercises the whole broker contract with fakes:
  A. state sign/verify + TTL expiry + tamper rejection (R1′ signing).
  B. POST /links auth matrix via FastAPI TestClient: 503 (secret unset),
     401 (absent / wrong secret), 200 + login_url (verifies back to the user).
  C. capture.poll_capture against a fake Playwright-like context: the success
     signal (ZD__userAuthenticated=true + _SESSION) writes ONLY the per-user
     store (R3) and the payload round-trips through user_store.
  D. GET /connect orchestration with BACKEND_FACTORY / CAPTURE_FN monkeypatched:
     one-time nonce is consumed (second /connect → 409) and /status reaches
     "connected".
  E. MCP _mint_login_url wired to the TestClient broker → returns a login_url;
     with no broker configured → None (⇒ plain SessionRequired, Phase-3 behavior).

Run from repo root:  py components\portal\broker\_broker_proof.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

SECRET = "phase4-broker-secret"
ALICE = "alice@example.com"

_fail = 0


def check(label: str, cond: bool) -> None:
    global _fail
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        _fail += 1


class _FakeContext:
    """A Playwright-context stand-in: returns pre_auth cookies until `flip()`d."""

    def __init__(self):
        self._authed = False

    def flip(self):
        self._authed = True

    def cookies(self):
        cookies = [{"name": "_SESSION", "value": "sess-abc", "domain": ".niceactimize.com",
                    "path": "/", "expires": 4102444800, "httpOnly": True, "secure": True}]
        cookies.append({
            "name": "ZD__userAuthenticated",
            "value": "true" if self._authed else "false",
            "domain": ".niceactimize.com", "path": "/",
        })
        return cookies


def main() -> int:
    store = tempfile.mkdtemp(prefix="broker-users-")
    os.environ["DOCENTER_USER_STORE_DIR"] = store
    os.environ["DOCENTER_BROKER_SECRET"] = SECRET

    from docenter_broker import app as broker_app
    from docenter_broker.backends import BrowserHandle
    from docenter_broker.capture import CaptureResult, LoginTimeout, poll_capture
    from docenter_broker.state import sign_state, verify_state
    from docenter_mcp import user_store

    # ── A. state signing ─────────────────────────────────────────────────────
    print("A. one-time signed state (R1′):")
    st = sign_state(ALICE, SECRET)
    ls = verify_state(st, SECRET)
    check("sign→verify round-trips the user_id", ls.user_id == ALICE)
    check("nonce is present and non-empty", bool(ls.nonce))

    tampered = st[:-2] + ("aa" if not st.endswith("aa") else "bb")
    try:
        verify_state(tampered, SECRET)
        check("tampered signature rejected", False)
    except ValueError:
        check("tampered signature rejected", True)

    try:
        verify_state(st, "wrong-secret")
        check("wrong secret rejected", False)
    except ValueError:
        check("wrong secret rejected", True)

    expired = sign_state(ALICE, SECRET, ttl_seconds=10, now_seconds=int(time.time()) - 10_000)
    try:
        verify_state(expired, SECRET)
        check("expired state rejected", False)
    except ValueError:
        check("expired state rejected", True)

    # ── B. POST /links auth matrix ───────────────────────────────────────────
    print("B. POST /links auth (R1′ MCP→broker hop):")
    from fastapi.testclient import TestClient

    # secret UNSET → 503
    saved = os.environ.pop("DOCENTER_BROKER_SECRET", None)
    with TestClient(broker_app.app) as c_unset:
        r = c_unset.post("/links", json={"user": ALICE})
        check("503 when DOCENTER_BROKER_SECRET unset", r.status_code == 503)
    os.environ["DOCENTER_BROKER_SECRET"] = saved or SECRET

    client = TestClient(broker_app.app)
    check("401 with no secret header", client.post("/links", json={"user": ALICE}).status_code == 401)
    check("401 with wrong secret", client.post(
        "/links", json={"user": ALICE}, headers={"X-Broker-Secret": "nope"}).status_code == 401)

    ok = client.post("/links", json={"user": ALICE}, headers={"X-Broker-Secret": SECRET})
    check("200 with correct secret", ok.status_code == 200)
    body = ok.json()
    check("response carries a login_url", bool(body.get("login_url")))
    minted_state = body.get("state", "")
    check("minted state verifies back to the user", bool(minted_state) and
          verify_state(minted_state, SECRET).user_id == ALICE)
    check("login_url points at /connect", "/connect?state=" in body.get("login_url", ""))

    # ── C. capture → per-user store (R3) ─────────────────────────────────────
    print("C. capture.poll_capture → per-user store (R3 isolation):")
    ctx = _FakeContext()
    # pre-auth cookies must NOT be treated as complete → times out fast.
    try:
        poll_capture(ctx, ALICE, timeout_s=1, poll_s=0, now_fn=_seq([0, 0, 2]), sleep_fn=lambda *_: None)
        check("pre-auth (_SESSION only) is NOT a success", False)
    except LoginTimeout:
        check("pre-auth (_SESSION only) is NOT a success", True)

    ctx.flip()
    res = poll_capture(ctx, ALICE, timeout_s=5, poll_s=0, sleep_fn=lambda *_: None)
    check("authenticated context → CaptureResult", res.user_id == ALICE)
    stored = user_store.load_user_cookie_data(ALICE)
    check("per-user cookie file written", stored is not None)
    names = {ck["name"] for ck in (stored or {}).get("data", {}).get("cookies", [])}
    check("stored payload round-trips _SESSION", "_SESSION" in names)

    # ── D. /connect two-door page + SSO door one-time nonce ──────────────────
    print("D. GET /connect chooser + POST /connect/sso orchestration:")
    broker_app._sessions.clear()
    broker_app._consumed_nonces.clear()

    class _FakeBackend:
        def open(self):
            return BrowserHandle(context=object(), interactive_url="http://novnc.local/vnc.html",
                                 close=lambda: None)

    def _fake_capture(context, user_id, **kw):
        return CaptureResult(user_id=user_id, expires=4102444800)

    broker_app.BACKEND_FACTORY = _FakeBackend
    broker_app.CAPTURE_FN = _fake_capture

    connect_state = sign_state(ALICE, SECRET)
    r1 = client.get(f"/connect?state={connect_state}")
    check("/connect returns the two-door HTML page", r1.status_code == 200 and "DOCenter" in r1.text)
    check("/connect page offers the SSO door", "Sign in with SSO" in r1.text)
    check("/connect page offers the password door", 'id="pw-form"' in r1.text)

    # GET is idempotent — reloading the chooser does NOT consume the link.
    check("/connect is idempotent (reload still 200)",
          client.get(f"/connect?state={connect_state}").status_code == 200)

    # Door 1: POST /connect/sso consumes the nonce and starts the browser worker.
    sso = client.post("/connect/sso", json={"state": connect_state})
    check("POST /connect/sso → 200 with a nonce", sso.status_code == 200 and bool(sso.json().get("nonce")))
    nonce = sso.json()["nonce"]

    connected = False
    for _ in range(50):
        s = client.get(f"/status?nonce={nonce}").json()
        if s.get("status") == "connected":
            connected = True
            break
        time.sleep(0.05)
    check("/status reaches 'connected' via the background worker", connected)

    r2 = client.post("/connect/sso", json={"state": connect_state})
    check("one-time link: second /connect/sso → 409", r2.status_code == 409)
    check("/connect now shows the 'already used' page", "already been used" in
          client.get(f"/connect?state={connect_state}").text)

    bad_state = client.post("/connect/sso", json={"state": "v1.bad.sig"})
    check("POST /connect/sso rejects a bad state (400)", bad_state.status_code == 400)

    broker_app.BACKEND_FACTORY = broker_app.get_backend
    broker_app.CAPTURE_FN = poll_capture

    # ── E. MCP _mint_login_url wired to the broker ───────────────────────────
    print("E. MCP _mint_login_url ↔ broker:")
    os.environ["DOCENTER_USER_TOKEN_SECRET"] = "irrelevant-for-this-check"
    from docenter_mcp import server

    class _ClientShim:
        """Route server.requests.post(f'{base}/links', ...) into the TestClient."""

        def post(self, url, headers=None, json=None, timeout=None):
            path = url.split("://", 1)[-1].split("/", 1)[-1]
            return client.post("/" + path, headers=headers or {}, json=json or {})

    real_requests = server.requests
    server.requests = _ClientShim()
    try:
        os.environ["DOCENTER_BROKER_URL"] = "http://broker.local"
        os.environ["DOCENTER_BROKER_SECRET"] = SECRET
        url = server._mint_login_url(ALICE)
        check("_mint_login_url returns a login_url when broker configured", bool(url) and "/connect?state=" in url)

        os.environ.pop("DOCENTER_BROKER_URL", None)
        check("_mint_login_url → None when broker unconfigured (plain SessionRequired)",
              server._mint_login_url(ALICE) is None)
    finally:
        server.requests = real_requests

    # ── F. Password door (Door 2) — browser-free login for password accounts ─
    print("F. POST /password-login (Door 2, no browser / no CA):")
    import requests as _requests

    import docenter.cli as _cli

    CUSTOMER = "customer@partner.example"

    def _fake_http_login(email, password, save=True):
        s = _requests.Session()
        s.cookies.set("_SESSION", "pw-sess-xyz", domain="docs-be.niceactimize.com")
        s.cookies.set("ZD__userAuthenticated", "true", domain="docs.niceactimize.com")
        return s

    real_http_login = _cli.http_login
    _cli.http_login = _fake_http_login
    try:
        check("401 without secret", client.post(
            "/password-login", json={"user": CUSTOMER, "email": "e", "password": "p"}).status_code == 401)
        check("400 with missing fields", client.post(
            "/password-login", json={"user": CUSTOMER, "email": "", "password": ""},
            headers={"X-Broker-Secret": SECRET}).status_code == 400)

        ok = client.post("/password-login",
                         json={"user": CUSTOMER, "email": "c@x", "password": "secret"},
                         headers={"X-Broker-Secret": SECRET})
        check("200 with secret + creds → connected", ok.status_code == 200 and ok.json().get("status") == "connected")
        stored = user_store.load_user_cookie_data(CUSTOMER)
        pw_names = {ck["name"] for ck in (stored or {}).get("data", {}).get("cookies", [])}
        check("password account's per-user cookie written (_SESSION)", "_SESSION" in pw_names)

        # Door 2 via the browser page: POST /connect/password authorized by a signed
        # state (no broker secret, no user field — the user_id comes from the state).
        STATE_USER = "state-user@partner.example"
        pw_state = sign_state(STATE_USER, SECRET)
        check("/connect/password rejects a bad state (400)", client.post(
            "/connect/password", json={"state": "v1.bad.sig", "email": "e", "password": "p"}
        ).status_code == 400)
        check("/connect/password requires email+password (400)", client.post(
            "/connect/password", json={"state": pw_state, "email": "", "password": ""}
        ).status_code == 400)
        cok = client.post("/connect/password",
                          json={"state": pw_state, "email": "c@x", "password": "secret"})
        check("/connect/password (state-authorized) → connected", cok.status_code == 200 and
              cok.json().get("status") == "connected")
        check("cookie stored under the STATE's user_id (R2, not a form field)",
              user_store.load_user_cookie_data(STATE_USER) is not None)
        check("/connect/password consumes the one-time state (second → 409)", client.post(
            "/connect/password", json={"state": pw_state, "email": "c@x", "password": "secret"}
        ).status_code == 409)

        def _bad_login(email, password, save=True):
            raise RuntimeError("portal login failed (HTTP 401)")

        _cli.http_login = _bad_login
        bad = client.post("/password-login",
                          json={"user": CUSTOMER, "email": "c@x", "password": "wrong"},
                          headers={"X-Broker-Secret": SECRET})
        check("bad credentials → 401 login failed", bad.status_code == 401)
    finally:
        _cli.http_login = real_http_login

    print()
    if _fail:
        print(f"RESULT: {_fail} check(s) FAILED")
        return 1
    print("RESULT: all checks PASSED")
    return 0


def _seq(values):
    """A now_fn that yields the given values then repeats the last (for timeout tests)."""
    it = iter(values)
    last = [0]

    def _now():
        try:
            last[0] = next(it)
        except StopIteration:
            pass
        return last[0]

    return _now


if __name__ == "__main__":
    sys.exit(main())
