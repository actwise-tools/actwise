"""Per-user DOCenter cookie store (Phase 3, R3/R6).

Maps an authenticated portal user id (the verified ``X-DOCenter-User`` subject)
to that user's own portal ``_SESSION`` cookie — kept **completely separate** from
the shared ``browser-profile/session-cookies.json`` the Copilot agent uses. This
isolation is the R3 guarantee: nothing here reads or writes the shared cookie
file, and nothing in the shared path reads or writes this store.

Layout::

    <DOCENTER_USER_STORE_DIR>/<sha256(user_id)>.json

The stored JSON is the exact same ``{"data": {"cookies": [...]}}`` shape that
``docenter.cli.build_session_from_cookies`` consumes, so a seeded file (Phase 3)
and a broker-written file (Phase 4) are byte-identical.

Only signature-verified user ids ever reach this module (the ``_AuthGate``
enforces the HMAC first), but filenames are still hashed so an arbitrary email /
path segment can never influence the on-disk path.
"""

from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path


def user_store_dir() -> Path:
    """Directory holding per-user cookie files.

    ``DOCENTER_USER_STORE_DIR`` overrides; default lives under the docenter user
    home (``~/.docenter/docenter-users``), never inside the repo."""
    override = os.environ.get("DOCENTER_USER_STORE_DIR")
    if override:
        return Path(override).expanduser()
    home = Path(os.environ.get("DOCENTER_HOME", str(Path.home() / ".docenter")))
    return home / "docenter-users"


def _user_file(user_id: str) -> Path:
    key = sha256(user_id.encode("utf-8")).hexdigest()
    return user_store_dir() / f"{key}.json"


def load_user_cookie_data(user_id: str) -> dict | None:
    """Return the parsed cookie payload for ``user_id`` or ``None`` if unseeded."""
    path = _user_file(user_id)
    if not path.exists():
        return None
    raw = path.read_bytes()
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8"
    return json.loads(raw.decode(encoding))


def save_user_cookie_data(user_id: str, data: dict) -> Path:
    """Persist a user's cookie payload (seeding in Phase 3; broker in Phase 4)."""
    path = _user_file(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def drop_user_cookie_data(user_id: str) -> None:
    """Remove a user's stored cookie (e.g. after an unrecoverable 403)."""
    path = _user_file(user_id)
    if path.exists():
        path.unlink()
