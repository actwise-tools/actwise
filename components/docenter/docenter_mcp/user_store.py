"""Per-user DOCenter cookie store (Phase 3, R3/R6).

Maps an authenticated portal user id (the verified ``X-DOCenter-User`` subject)
to that user's own portal ``_SESSION`` cookie — kept **completely separate** from
the shared ``browser-profile/session-cookies.json`` the Copilot agent uses. This
isolation is the R3 guarantee: nothing here reads or writes the shared cookie
file, and nothing in the shared path reads or writes this store.

Two interchangeable backends, selected purely by environment (no code change in
any consumer — the MCP reads, the broker/password door writes):

* **filesystem** (default) — one file per user::

      <DOCENTER_USER_STORE_DIR>/<sha256(user_id)>.json

* **S3** — enabled when ``DOCENTER_USER_STORE_S3_BUCKET`` is set (required so the
  AWS App Runner MCP and the broker can share one store across instances)::

      s3://<bucket>/<DOCENTER_USER_STORE_S3_PREFIX>/<sha256(user_id)>.json

The stored JSON is the exact same ``{"data": {"cookies": [...]}}`` shape that
``docenter.cli.build_session_from_cookies`` consumes, so a seeded file (Phase 3)
and a broker-written object (Phase 4) are byte-identical across both backends.

Only signature-verified user ids ever reach this module (the ``_AuthGate``
enforces the HMAC first), but the user id is always hashed so an arbitrary email
/ path segment can never influence the on-disk path or the S3 object key.
"""

from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path

# Test seam: when set to a zero-arg callable, it is used instead of
# ``boto3.client("s3")`` so the S3 backend can be exercised fully offline
# (see ``_store_proof.py``). Mirror boto3: the returned client must expose
# ``get_object``/``put_object``/``delete_object`` and ``exceptions.NoSuchKey``.
S3_CLIENT_FACTORY = None


def _decode_json(raw: bytes) -> dict:
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8"
    return json.loads(raw.decode(encoding))


# ── backend selection ────────────────────────────────────────────────────────
def _s3_bucket() -> str | None:
    """The S3 bucket when the S3 backend is active, else ``None`` (filesystem)."""
    bucket = os.environ.get("DOCENTER_USER_STORE_S3_BUCKET", "").strip()
    return bucket or None


# ── filesystem backend ───────────────────────────────────────────────────────
def user_store_dir() -> Path:
    """Directory holding per-user cookie files (filesystem backend).

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


def _fs_load(user_id: str) -> dict | None:
    path = _user_file(user_id)
    if not path.exists():
        return None
    return _decode_json(path.read_bytes())


def _fs_save(user_id: str, data: dict) -> str:
    path = _user_file(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return str(path)


def _fs_drop(user_id: str) -> None:
    path = _user_file(user_id)
    if path.exists():
        path.unlink()


# ── S3 backend ───────────────────────────────────────────────────────────────
def _s3_client():
    if S3_CLIENT_FACTORY is not None:
        return S3_CLIENT_FACTORY()
    import boto3  # lazy: only imported when the S3 backend is actually used

    return boto3.client("s3")


def _s3_key(user_id: str) -> str:
    prefix = os.environ.get("DOCENTER_USER_STORE_S3_PREFIX", "docenter-users").strip("/")
    key = sha256(user_id.encode("utf-8")).hexdigest()
    return f"{prefix}/{key}.json" if prefix else f"{key}.json"


def _s3_load(user_id: str, bucket: str) -> dict | None:
    client = _s3_client()
    try:
        obj = client.get_object(Bucket=bucket, Key=_s3_key(user_id))
    except client.exceptions.NoSuchKey:
        return None
    return _decode_json(obj["Body"].read())


def _s3_save(user_id: str, data: dict, bucket: str) -> str:
    client = _s3_client()
    key = _s3_key(user_id)
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(data, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    return f"s3://{bucket}/{key}"


def _s3_drop(user_id: str, bucket: str) -> None:
    client = _s3_client()
    client.delete_object(Bucket=bucket, Key=_s3_key(user_id))


# ── public API (backend-agnostic) ────────────────────────────────────────────
def load_user_cookie_data(user_id: str) -> dict | None:
    """Return the parsed cookie payload for ``user_id`` or ``None`` if unseeded."""
    bucket = _s3_bucket()
    if bucket:
        return _s3_load(user_id, bucket)
    return _fs_load(user_id)


def save_user_cookie_data(user_id: str, data: dict) -> str:
    """Persist a user's cookie payload (seeding in Phase 3; broker in Phase 4).

    Returns the backend location (a filesystem path or an ``s3://`` URI)."""
    bucket = _s3_bucket()
    if bucket:
        return _s3_save(user_id, data, bucket)
    return _fs_save(user_id, data)


def drop_user_cookie_data(user_id: str) -> None:
    """Remove a user's stored cookie (e.g. after an unrecoverable 403)."""
    bucket = _s3_bucket()
    if bucket:
        _s3_drop(user_id, bucket)
        return
    _fs_drop(user_id)
