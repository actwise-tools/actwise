"""Login capture — poll a browser context for the DOCenter success signal and
write the captured ``_SESSION`` to the Phase-3 per-user store.

Backend-agnostic: a backend (self-hosted Playwright or Browserbase) supplies a
Playwright ``context`` the user is driving; this module owns the success
detection (reusing ``docenter.cli.zoomin_login_complete``) and the store write
(``docenter_mcp.user_store.save_user_cookie_data``), so there is exactly one
capture path (avoids drift D1).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from docenter.cli import cookies_to_payload, zoomin_login_complete
from docenter_mcp.user_store import save_user_cookie_data

PORTAL_LOGIN_URL = "https://docs.niceactimize.com/auth/login"
DEFAULT_TIMEOUT_S = 300
DEFAULT_POLL_S = 2


class LoginTimeout(RuntimeError):
    """The user did not complete login before the deadline."""


@dataclass(frozen=True)
class CaptureResult:
    user_id: str
    expires: int  # unix secs of the _SESSION cookie, or -1


def poll_capture(
    context,
    user_id: str,
    *,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    poll_s: int = DEFAULT_POLL_S,
    now_fn=time.time,
    sleep_fn=time.sleep,
) -> CaptureResult:
    """Poll ``context`` for the login success signal, then persist the user's cookies.

    Returns a ``CaptureResult`` on success; raises ``LoginTimeout`` otherwise. The
    captured payload is written ONLY to the per-user store — never the shared
    cookie file (R3)."""
    deadline = now_fn() + timeout_s
    while now_fn() < deadline:
        cookies = context.cookies()
        found = zoomin_login_complete(cookies)
        if found:
            save_user_cookie_data(user_id, cookies_to_payload(cookies))
            return CaptureResult(user_id=user_id, expires=int(found.get("expires", -1) or -1))
        sleep_fn(poll_s)
    raise LoginTimeout(f"login not completed for user '{user_id}' within {timeout_s}s")
