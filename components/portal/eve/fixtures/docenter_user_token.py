"""Python twin of agent/lib/docenter-user-token.ts (Phase 2 fixture).

Byte-for-byte compatible with the TypeScript signer the portal uses to mint the
``X-DOCenter-User`` header. Phase 2 uses it only to *verify* captured headers
offline; Phase 3 will promote this module into ``docenter_mcp/user_token.py`` so
the MCP's ``_AuthGate`` can enforce the signature (R2).

Wire format (v1), 4 dot-separated ASCII parts::

    v1 . base64url(userId) . exp . base64url(HMAC_SHA256(secret, payload))
                                   payload = "v1." + base64url(userId) + "." + exp

  - base64url: RFC 4648 section 5, no padding
  - exp: token expiry as unix seconds (decimal)
  - HMAC key = DOCENTER_USER_TOKEN_SECRET (utf-8)
"""

from __future__ import annotations

import base64
import hmac
import time
from dataclasses import dataclass
from hashlib import sha256

VERSION = "v1"
DEFAULT_TTL_SECONDS = 300


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def _sign(payload: str, secret: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), sha256).digest()
    return _b64url_encode(mac)


def mint_docenter_user_token(
    user_id: str,
    secret: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now_seconds: int | None = None,
) -> str:
    if not user_id:
        raise ValueError("mint_docenter_user_token: user_id is empty")
    if not secret:
        raise ValueError("mint_docenter_user_token: secret is empty")
    now = int(time.time()) if now_seconds is None else now_seconds
    exp = now + ttl_seconds
    payload = f"{VERSION}.{_b64url_encode(user_id.encode('utf-8'))}.{exp}"
    return f"{payload}.{_sign(payload, secret)}"


@dataclass(frozen=True)
class VerifiedDocenterUserToken:
    user_id: str
    exp: int


def verify_docenter_user_token(
    token: str,
    secret: str,
    now_seconds: int | None = None,
    clock_skew_seconds: int = 30,
) -> VerifiedDocenterUserToken:
    parts = token.split(".")
    if len(parts) != 4:
        raise ValueError("verify_docenter_user_token: malformed token")
    version, user_id_b64, exp_str, sig = parts
    if version != VERSION:
        raise ValueError(f"verify_docenter_user_token: unsupported version {version}")

    payload = f"{version}.{user_id_b64}.{exp_str}"
    expected = _sign(payload, secret)
    if not hmac.compare_digest(expected, sig):
        raise ValueError("verify_docenter_user_token: bad signature")

    try:
        exp = int(exp_str)
    except ValueError as err:
        raise ValueError("verify_docenter_user_token: bad exp") from err
    now = int(time.time()) if now_seconds is None else now_seconds
    if now > exp + clock_skew_seconds:
        raise ValueError("verify_docenter_user_token: token expired")

    return VerifiedDocenterUserToken(
        user_id=_b64url_decode(user_id_b64).decode("utf-8"),
        exp=exp,
    )


if __name__ == "__main__":
    import argparse
    import os
    import sys

    ap = argparse.ArgumentParser(description="Verify an X-DOCenter-User token offline.")
    ap.add_argument("token")
    ap.add_argument("--secret", default=os.environ.get("DOCENTER_USER_TOKEN_SECRET", ""))
    args = ap.parse_args()
    if not args.secret:
        print("error: pass --secret or set DOCENTER_USER_TOKEN_SECRET", file=sys.stderr)
        raise SystemExit(2)
    try:
        result = verify_docenter_user_token(args.token, args.secret)
    except ValueError as err:
        print(f"INVALID: {err}", file=sys.stderr)
        raise SystemExit(1)
    print(f"VALID user_id={result.user_id!r} exp={result.exp}")
