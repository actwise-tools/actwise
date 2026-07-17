"""DOCenter login broker — FastAPI service.

Endpoints:
  GET  /healthz             unauthenticated liveness probe
  POST /links  {user}       MINT a one-time login link (auth: X-Broker-Secret, R1′)
  GET  /connect?state=…     render the two-door login page (idempotent, no consume)
  POST /connect/sso         Door 1: consume state → open hosted browser → capture _SESSION
  POST /connect/password    Door 2: browser-free password login, authorized by the state
  GET  /status?nonce=…      poll an in-flight SSO login's status (for the connect page)
  POST /password-login      Door 2 (server-to-server): password login, auth: X-Broker-Secret

The broker OWNS state signing + TTL + one-time use; the MCP only calls POST /links
and forwards the returned ``login_url`` (R1′). The login_url opens the two-door page,
so the chat/agent only ever surfaces ONE link and passwords never reach the model.
Additive to everything else.

Run:  docenter-broker            (or: py -m uvicorn docenter_broker.app:app --port 8099)
"""

from __future__ import annotations

import html
import os
import threading

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from .backends import get_backend
from .capture import LoginTimeout, poll_capture
from .password import PasswordLoginError, password_login
from .state import broker_secret, sign_state, verify_state

SERVER_NAME = "actwise-docenter-broker"

# Public base the user's browser can reach (used to build login_url).
PUBLIC_BASE_ENV = "BROKER_PUBLIC_BASE"

# In-flight login sessions keyed by the state nonce, and the set of consumed
# nonces (one-time use). In production both move to Redis/DB; in-process is fine
# for the local Phase-4 spike.
_sessions: dict = {}
_sessions_lock = threading.Lock()
_consumed_nonces: set = set()

# Test seams — monkeypatched by the proof to avoid a real browser / network.
BACKEND_FACTORY = get_backend
CAPTURE_FN = poll_capture
PASSWORD_LOGIN_FN = password_login

app = FastAPI(title=SERVER_NAME)


class LinkRequest(BaseModel):
    user: str


class PasswordLoginRequest(BaseModel):
    user: str
    email: str
    password: str


class SsoStartRequest(BaseModel):
    state: str


class ConnectPasswordRequest(BaseModel):
    state: str
    email: str
    password: str


def _public_base(request: Request) -> str:
    base = os.environ.get(PUBLIC_BASE_ENV, "").rstrip("/")
    if base:
        return base
    return str(request.base_url).rstrip("/")


@app.get("/healthz")
def healthz():
    return {"status": "ok", "server": SERVER_NAME, "backend": os.environ.get("BROKER_BACKEND", "self-hosted")}


@app.post("/links")
def create_link(body: LinkRequest, request: Request, x_broker_secret: str = Header(default="")):
    """Mint a one-time login link for a user. Requires the shared broker secret (R1′)."""
    secret = broker_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="broker not configured (DOCENTER_BROKER_SECRET unset)")
    if not (x_broker_secret and _consteq(x_broker_secret, secret)):
        raise HTTPException(status_code=401, detail="unauthorized")
    if not body.user:
        raise HTTPException(status_code=400, detail="user is required")

    state = sign_state(body.user, secret)
    login_url = f"{_public_base(request)}/connect?state={state}"
    return {"login_url": login_url, "state": state}


@app.post("/password-login")
def password_login_endpoint(body: PasswordLoginRequest, x_broker_secret: str = Header(default="")):
    """Door 2: browser-free login for a password (non-SSO) DOCenter account.

    The portal collects the customer's own DOCenter email+password and forwards
    them here (auth: the shared broker secret, like /links). No Playwright, no
    Entra, no Conditional Access — the captured cookie lands in the same per-user
    store as the SSO door, so the MCP serves both identically."""
    secret = broker_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="broker not configured (DOCENTER_BROKER_SECRET unset)")
    if not (x_broker_secret and _consteq(x_broker_secret, secret)):
        raise HTTPException(status_code=401, detail="unauthorized")
    if not (body.user and body.email and body.password):
        raise HTTPException(status_code=400, detail="user, email and password are required")

    try:
        result = PASSWORD_LOGIN_FN(body.user, body.email, body.password)
    except PasswordLoginError as exc:
        raise HTTPException(status_code=401, detail=f"login failed: {exc}")
    return {"status": "connected", "user_id": result.user_id, "expires": result.expires}


@app.get("/connect")
def connect(state: str, request: Request):
    """Render the two-door login page for a one-time state.

    GET is idempotent (safe to reload) — it neither consumes the nonce nor starts
    a browser. The user then picks a door: SSO (POST /connect/sso, employees) or
    username+password (POST /connect/password, customers/partners). Both actions
    authorize with this same signed ``state`` (the capability minted by /links),
    so nothing here needs the broker secret and passwords never reach the chat."""
    secret = broker_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="broker not configured")
    try:
        ls = verify_state(state, secret)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid state: {exc}")

    with _sessions_lock:
        already = ls.nonce in _consumed_nonces
    return HTMLResponse(_connect_page(state, ls.user_id, already))


@app.post("/connect/sso")
def connect_sso(body: SsoStartRequest):
    """Door 1: consume the one-time state and open a hosted browser for SSO login."""
    secret = broker_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="broker not configured")
    try:
        ls = verify_state(body.state, secret)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid state: {exc}")

    with _sessions_lock:
        if ls.nonce in _consumed_nonces:
            raise HTTPException(status_code=409, detail="login link already used")
        _consumed_nonces.add(ls.nonce)
        _sessions[ls.nonce] = {"status": "starting", "user_id": ls.user_id,
                               "interactive_url": None, "expires": None, "error": None}

    threading.Thread(target=_run_login, args=(ls.nonce, ls.user_id), daemon=True).start()
    return {"nonce": ls.nonce}


@app.post("/connect/password")
def connect_password(body: ConnectPasswordRequest):
    """Door 2: browser-free password login authorized by the one-time state.

    The user_id comes from the SIGNED state (R2 — never the form), so the captured
    cookie always lands in the right per-user store and a form field cannot
    impersonate another user. On success the nonce is consumed (one-time); a failed
    attempt leaves the link usable so a typo can be retried within its TTL."""
    secret = broker_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="broker not configured")
    try:
        ls = verify_state(body.state, secret)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid state: {exc}")
    if not (body.email and body.password):
        raise HTTPException(status_code=400, detail="email and password are required")

    with _sessions_lock:
        if ls.nonce in _consumed_nonces:
            raise HTTPException(status_code=409, detail="login link already used")

    try:
        result = PASSWORD_LOGIN_FN(ls.user_id, body.email, body.password)
    except PasswordLoginError as exc:
        raise HTTPException(status_code=401, detail=f"login failed: {exc}")

    with _sessions_lock:
        _consumed_nonces.add(ls.nonce)
    return {"status": "connected", "user_id": result.user_id, "expires": result.expires}


@app.get("/status")
def status(nonce: str):
    with _sessions_lock:
        sess = _sessions.get(nonce)
    if sess is None:
        return JSONResponse({"error": "unknown session"}, status_code=404)
    return {k: sess[k] for k in ("status", "interactive_url", "expires", "error")}


def _run_login(nonce: str, user_id: str) -> None:
    """Background worker: open the browser, wait for the user's login, capture + store."""
    def _set(**kw):
        with _sessions_lock:
            _sessions[nonce].update(kw)

    handle = None
    try:
        handle = BACKEND_FACTORY().open()
        _set(status="waiting", interactive_url=handle.interactive_url)
        result = CAPTURE_FN(handle.context, user_id)
        _set(status="connected", expires=result.expires)
    except LoginTimeout as exc:
        _set(status="timeout", error=str(exc))
    except Exception as exc:  # noqa: BLE001 — surface a status, never a stack to the user
        _set(status="error", error=str(exc))
    finally:
        if handle is not None:
            try:
                handle.close()
            except Exception:  # noqa: BLE001
                pass


def _connect_page(state: str, user_id: str, already_used: bool) -> str:
    safe_user = html.escape(user_id)
    safe_state = html.escape(state)
    if already_used:
        return """<!doctype html><html><head><meta charset="utf-8">
<title>Connect your DOCenter account</title>
<style>body{font-family:system-ui,sans-serif;max-width:640px;margin:3rem auto;padding:0 1rem}</style>
</head><body><h2>Connect your DOCenter account</h2>
<p>⚠️ This login link has already been used. Return to the chat and ask your question
again to get a fresh link.</p></body></html>"""
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Connect your DOCenter account</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:640px;margin:3rem auto;padding:0 1rem;color:#222}}
.door{{border:1px solid #ddd;border-radius:8px;padding:1.1rem 1.2rem;margin:1rem 0}}
.door h3{{margin:.1rem 0 .4rem}}
button,input{{font:inherit}}
button{{padding:.55rem 1rem;background:#0b5;color:#fff;border:0;border-radius:6px;cursor:pointer}}
button.secondary{{background:#345}}
input{{width:100%;box-sizing:border-box;padding:.5rem;margin:.3rem 0;border:1px solid #ccc;border-radius:6px}}
.muted{{color:#666;font-size:.92rem}}
#sso-status,#pw-status{{margin-top:.6rem;color:#555}}
a.btn{{display:inline-block;padding:.55rem 1rem;background:#0b5;color:#fff;border-radius:6px;text-decoration:none}}
</style></head><body>
<h2>Connect your DOCenter account</h2>
<p>Signing in as <b>{safe_user}</b>. Choose how you sign in to the NICE Actimize
documentation portal.</p>

<div class="door">
  <h3>NICE employee — Single Sign-On</h3>
  <p class="muted">Opens a secure browser and signs you in with your NICE account (SSO/MFA).</p>
  <button id="sso-btn" onclick="startSso()">Sign in with SSO</button>
  <p id="sso-link"></p>
  <p id="sso-status"></p>
</div>

<div class="door">
  <h3>Customer / partner — username &amp; password</h3>
  <p class="muted">For DOCenter accounts registered with an email and password (not SSO).</p>
  <form id="pw-form" onsubmit="return submitPassword(event)">
    <input id="pw-email" type="email" placeholder="DOCenter email" autocomplete="username" required>
    <input id="pw-password" type="password" placeholder="DOCenter password" autocomplete="current-password" required>
    <button class="secondary" type="submit">Sign in with password</button>
  </form>
  <p id="pw-status"></p>
</div>

<script>
const state = "{safe_state}";

async function startSso() {{
  const btn = document.getElementById("sso-btn");
  const status = document.getElementById("sso-status");
  btn.disabled = true;
  status.textContent = "Starting secure browser…";
  try {{
    const r = await fetch("connect/sso", {{
      method: "POST", headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{state}}),
    }});
    if (!r.ok) {{ status.textContent = "⚠️ " + (await r.text()); btn.disabled = false; return; }}
    const {{nonce}} = await r.json();
    pollStatus(nonce);
  }} catch (e) {{ status.textContent = "⚠️ " + e; btn.disabled = false; }}
}}

async function pollStatus(nonce) {{
  const status = document.getElementById("sso-status");
  const link = document.getElementById("sso-link");
  const r = await fetch("status?nonce=" + encodeURIComponent(nonce));
  if (!r.ok) {{ status.textContent = "Session not found."; return; }}
  const d = await r.json();
  if (d.interactive_url)
    link.innerHTML = '<a class="btn" href="' + d.interactive_url + '" target="_blank">Open secure login browser</a>';
  if (d.status === "connected") {{ status.textContent = "✅ Connected! Return to the chat and ask again."; return; }}
  if (d.status === "timeout") {{ status.textContent = "⌛ Login timed out — reload to try again."; return; }}
  if (d.status === "error") {{ status.textContent = "⚠️ " + (d.error || "error"); return; }}
  status.textContent = "Waiting for you to finish login… (" + d.status + ")";
  setTimeout(() => pollStatus(nonce), 2000);
}}

async function submitPassword(ev) {{
  ev.preventDefault();
  const status = document.getElementById("pw-status");
  const email = document.getElementById("pw-email").value;
  const password = document.getElementById("pw-password").value;
  status.textContent = "Signing in…";
  try {{
    const r = await fetch("connect/password", {{
      method: "POST", headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{state, email, password}}),
    }});
    if (r.ok) {{ status.textContent = "✅ Connected! Return to the chat and ask again."; return false; }}
    let detail = await r.text();
    try {{ detail = JSON.parse(detail).detail || detail; }} catch (e) {{}}
    status.textContent = "⚠️ " + detail;
  }} catch (e) {{ status.textContent = "⚠️ " + e; }}
  return false;
}}
</script></body></html>"""


def _consteq(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a, b)


def main() -> None:
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("BROKER_HOST", "127.0.0.1"),
        port=int(os.environ.get("BROKER_PORT", "8099")),
    )


if __name__ == "__main__":
    main()
