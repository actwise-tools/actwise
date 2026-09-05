"""Password door — browser-free login for non-federated (password) DOCenter accounts.

Customers/partners who registered with an email+password directly on Zoomin (NOT
NICE-Entra SSO) authenticate against the Zoomin login API — no browser, no Entra,
no Conditional Access. This module exchanges their credentials for their own
``_SESSION`` via ``docenter.cli.http_login`` and writes it to the SAME Phase-3
per-user store the SSO door uses, so the MCP serves both identically.

R3 isolation: ``http_login`` is called with ``save=False`` so it never writes the
shared cookie file — only the per-user store is written here.
"""

from __future__ import annotations

from dataclasses import dataclass

import docenter.cli as _cli
from docenter.cli import requests_cookies_to_payload
from docenter_mcp.user_store import save_user_cookie_data


class PasswordLoginError(RuntimeError):
    """The credentials were rejected or the portal login otherwise failed."""


@dataclass(frozen=True)
class PasswordLoginResult:
    user_id: str
    expires: int  # unix secs of the _SESSION cookie, or -1


def password_login(user_id: str, email: str, password: str) -> PasswordLoginResult:
    """Log a password account in via the HTTP API and store its cookie for ``user_id``.

    ``user_id`` is the identity the portal keys the per-user store on (the verified
    ``X-DOCenter-User`` subject); ``email``/``password`` are the DOCenter password
    account's own credentials. Raises ``PasswordLoginError`` on failure."""
    try:
        session = _cli.http_login(email, password, save=False)
    except Exception as exc:  # noqa: BLE001 — normalize to one door error type
        raise PasswordLoginError(str(exc)) from exc

    payload = requests_cookies_to_payload(session)
    save_user_cookie_data(user_id, payload)

    expires = -1
    for c in payload["data"]["cookies"]:
        if c["name"] == "_SESSION":
            expires = int(c.get("expires", -1) or -1)
            break
    return PasswordLoginResult(user_id=user_id, expires=expires)
