"""One-time, HMAC-signed login state (R1′: the broker owns state signing + TTL).

A ``state`` string binds a login link to a specific user for a short window and
is single-use. The MCP never signs state — it only calls ``POST /links`` and
forwards the returned ``login_url``. Format mirrors the X-DOCenter-User token::

    v1.<b64url(json{"u":user,"n":nonce,"exp":exp})>.<b64url(HMAC_SHA256(secret, "v1.<payload>"))>

Secret: ``DOCENTER_BROKER_SECRET``. One-time use is enforced by the broker's
in-process consumed-nonce set (a Redis/DB set is the production upgrade).
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from hashlib import sha256

VERSION = "v1"
DEFAULT_TTL_SECONDS = 600
BROKER_SECRET_ENV = "DOCENTER_BROKER_SECRET"


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def _sign(payload: str, secret: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), sha256).digest()
    return _b64url_encode(mac)


@dataclass(frozen=True)
class LoginState:
    user_id: str
    nonce: str
    exp: int


def sign_state(
    user_id: str,
    secret: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now_seconds: int | None = None,
    nonce: str | None = None,
) -> str:
    """Mint a signed one-time state for ``user_id``."""
    if not user_id:
        raise ValueError("sign_state: user_id is empty")
    if not secret:
        raise ValueError("sign_state: secret is empty")
    now = int(time.time()) if now_seconds is None else now_seconds
    body = {"u": user_id, "n": nonce or secrets.token_urlsafe(16), "exp": now + ttl_seconds}
    payload = f"{VERSION}.{_b64url_encode(json.dumps(body, separators=(',', ':')).encode())}"
    return f"{payload}.{_sign(payload, secret)}"


def verify_state(
    state: str,
    secret: str,
    now_seconds: int | None = None,
    clock_skew_seconds: int = 30,
) -> LoginState:
    """Verify signature + expiry; raise ``ValueError`` on any failure."""
    parts = state.split(".")
    if len(parts) != 3:
        raise ValueError("verify_state: malformed state")
    version, body_b64, sig = parts
    if version != VERSION:
        raise ValueError(f"verify_state: unsupported version {version}")

    payload = f"{version}.{body_b64}"
    if not hmac.compare_digest(_sign(payload, secret), sig):
        raise ValueError("verify_state: bad signature")

    try:
        body = json.loads(_b64url_decode(body_b64))
        user_id, nonce, exp = body["u"], body["n"], int(body["exp"])
    except (ValueError, KeyError, TypeError) as err:
        raise ValueError("verify_state: bad payload") from err

    now = int(time.time()) if now_seconds is None else now_seconds
    if now > exp + clock_skew_seconds:
        raise ValueError("verify_state: state expired")

    return LoginState(user_id=user_id, nonce=nonce, exp=exp)


def broker_secret() -> str:
    return os.environ.get(BROKER_SECRET_ENV, "")
