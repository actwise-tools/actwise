"""Connection resolution for ActWise Data.

Precedence (highest wins): explicit CLI flags > environment
(``ACTONE_DB_URL`` / ``ACTONE_DB_*``) > named profile in ``actone-data.yaml`` >
built-in ``local`` default. The built-in ``local`` profile mirrors the
``actone_local`` Docker DB defaults, so a laptop with ``actone-local db-up`` needs
zero configuration.

Passwords are never read from the profile YAML. Per-profile passwords come from
the gitignored ``actone-data.secrets.yaml`` (``{profile: password}``) or a
per-profile env var ``ACTONE_DB_PASSWORD__<PROFILE>``; a global
``ACTONE_DB_PASSWORD`` is the last-resort fallback. Each named profile is an
"environment"; ``list_profiles`` returns their metadata (never passwords).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from actwise.paths import find_config

DEFAULT_PROFILE_PATH = find_config("actone-data.yaml")
# Per-profile passwords live here (gitignored); never in the profile YAML.
DEFAULT_SECRETS_PATH = find_config("actone-data.secrets.yaml")

# Built-in "local" profile == the actone_local Docker DB defaults (see
# actone_local/config.py:DbConfig). Zero-config local use.
LOCAL_DEFAULTS: dict = {
    "host": "localhost",
    "port": 5432,
    "name": "actone",
    "user": "actone",
    "password": "actone",
    "schema": "actone",
}

DEFAULT_TIMEOUT_MS = 15000
DEFAULT_CONNECT_TIMEOUT_S = 10
APPLICATION_NAME = "actone-data"

# Bundled documentation corpus version. Used as the version fallback when the
# live DB carries no stamp in acm_md_versions, and as the default schema-pack
# target (overridable via --doc-version at pack build).
DEFAULT_DOC_VERSION = "10.2"

_DISCRETE = ("host", "port", "name", "user", "password", "schema")
_ENV_MAP = {
    "host": "ACTONE_DB_HOST",
    "port": "ACTONE_DB_PORT",
    "name": "ACTONE_DB_NAME",
    "user": "ACTONE_DB_USER",
    "password": "ACTONE_DB_PASSWORD",
    "schema": "ACTONE_DB_SCHEMA",
}


@dataclass
class ConnConfig:
    host: str = "localhost"
    port: int = 5432
    name: str = "actone"
    user: str = "actone"
    password: str = "actone"
    schema: str = "actone"
    dsn: str | None = None  # full DSN wins over the discrete fields
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    connect_timeout_s: int = DEFAULT_CONNECT_TIMEOUT_S
    application_name: str = APPLICATION_NAME

    @property
    def target(self) -> str:
        """Human-readable connection target (never includes the password)."""
        return "dsn" if self.dsn else f"{self.host}:{self.port}/{self.name}"


def _load_profiles(path: Path | None = None) -> dict:
    path = path or DEFAULT_PROFILE_PATH
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return raw.get("profiles", raw) or {}


def _load_secrets(path: Path | None = None) -> dict:
    """Per-profile passwords: ``{profile: password}`` or ``{profile: {password: ...}}``."""
    path = path or DEFAULT_SECRETS_PATH
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data = raw.get("secrets", raw.get("profiles", raw)) or {}
    out: dict[str, str] = {}
    for name, val in data.items():
        if isinstance(val, dict):
            if val.get("password") is not None:
                out[name] = str(val["password"])
        elif val is not None:
            out[name] = str(val)
    return out


def _profile_env_key(profile: str) -> str:
    """Per-profile password env var, e.g. profile ``prod-eu`` -> ACTONE_DB_PASSWORD__PROD_EU."""
    slug = re.sub(r"[^A-Z0-9]+", "_", (profile or "local").upper()).strip("_")
    return f"ACTONE_DB_PASSWORD__{slug}"


def _resolve_password(
    profile: str | None,
    profile_pw: str | None,
    flag_pw: str | None,
    secrets_path: Path | None = None,
) -> str:
    """Password precedence (highest first): flag > per-profile env > secrets file >
    global ``ACTONE_DB_PASSWORD`` > profile YAML > built-in default."""
    if flag_pw is not None:
        return flag_pw
    name = profile or "local"
    per_profile = os.getenv(_profile_env_key(name))
    if per_profile:
        return per_profile
    secrets = _load_secrets(secrets_path)
    if secrets.get(name) is not None:
        return secrets[name]
    if os.getenv("ACTONE_DB_PASSWORD"):
        return os.environ["ACTONE_DB_PASSWORD"]
    if profile_pw is not None:
        return profile_pw
    return LOCAL_DEFAULTS["password"]


def list_profiles(path: Path | None = None, secrets_path: Path | None = None) -> list[dict]:
    """Configured environments (metadata only — **never passwords**).

    Always includes the built-in ``local`` profile. ``password_configured`` reports
    whether a password source exists, without revealing it.
    """
    profiles = _load_profiles(path)
    default = os.getenv("ACTONE_DATA_PROFILE") or "local"
    names = list(profiles.keys())
    if "local" not in names:
        names.insert(0, "local")

    out: list[dict] = []
    for name in names:
        prof = profiles.get(name) or {}
        merged = dict(LOCAL_DEFAULTS)
        for key in _DISCRETE:
            if prof.get(key) is not None:
                merged[key] = prof[key]
        pw_source = (
            bool(os.getenv(_profile_env_key(name)))
            or _load_secrets(secrets_path).get(name) is not None
            or bool(os.getenv("ACTONE_DB_PASSWORD"))
            or prof.get("password") is not None
            or name == "local"  # local ships a default password
        )
        out.append({
            "name": name,
            "host": merged["host"],
            "port": int(merged["port"]),
            "database": merged["name"],
            "user": merged["user"],
            "schema": merged["schema"],
            "dsn": bool(prof.get("dsn")),
            "password_configured": pw_source,
            "is_default": name == default,
        })
    return out


def resolve(profile: str | None = "local", path: Path | None = None, **overrides) -> ConnConfig:
    """Merge default -> profile -> env -> flags into a ConnConfig.

    ``overrides`` are the CLI flags (any of host/port/name/user/password/schema/dsn);
    ``None`` values are ignored so unset flags don't clobber lower-precedence sources.
    """
    values = dict(LOCAL_DEFAULTS)
    dsn = None
    timeout_ms = DEFAULT_TIMEOUT_MS
    profile_pw: str | None = None

    # 1. named profile (the built-in "local"/None uses defaults as-is)
    profiles = _load_profiles(path)
    if profile and profile != "local":
        if profile not in profiles:
            known = ", ".join(sorted(profiles)) or "(none)"
            raise KeyError(f"unknown profile {profile!r}; defined profiles: {known}")
        prof = profiles[profile] or {}
        for key in _DISCRETE:
            if prof.get(key) is not None:
                values[key] = prof[key]
        profile_pw = prof.get("password")
        if prof.get("dsn"):
            dsn = prof["dsn"]
    elif profile is None and profiles.get("local"):
        for key in _DISCRETE:
            if profiles["local"].get(key) is not None:
                values[key] = profiles["local"][key]
        profile_pw = profiles["local"].get("password")

    # 2. environment (password handled separately below)
    if os.getenv("ACTONE_DB_URL"):
        dsn = os.environ["ACTONE_DB_URL"]
    for key, env in _ENV_MAP.items():
        if key == "password":
            continue
        if os.getenv(env):
            values[key] = os.environ[env]
    if os.getenv("ACTONE_DATA_TIMEOUT_MS"):
        timeout_ms = int(os.environ["ACTONE_DATA_TIMEOUT_MS"])

    # 3. explicit flags win (password handled separately below)
    if overrides.get("dsn"):
        dsn = overrides["dsn"]
    for key in _DISCRETE:
        if key == "password":
            continue
        if overrides.get(key) is not None:
            values[key] = overrides[key]

    # 4. password: per-profile secrets/env, resolved by precedence
    values["password"] = _resolve_password(profile, profile_pw, overrides.get("password"))

    values["port"] = int(values["port"])
    return ConnConfig(dsn=dsn, timeout_ms=timeout_ms, **values)
