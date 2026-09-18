"""Environment resolution for the ActOne Ops agent (REST/Extend endpoint).

Mirrors ``actone_data/config.py`` but targets a **runtime ActOne REST instance**
(URL + user + password + optional context root) instead of a Postgres DB. Each
named environment under ``actone-ops.yaml`` is one ActOne instance the ops CLI
(``actone ops --env <name>``) and the ops MCP server (``env`` tool argument,
surfaced by ``list_environments``) can target.

Precedence (highest wins): explicit CLI flags (``--url/--user/--password``) >
process env (``ACTONE_URL`` / ``ACTONE_USER`` / ``ACTONE_CONTEXT_ROOT``) > named
environment in ``actone-ops.yaml`` > built-in ``default`` environment (the
``<workdir>/.env`` values — keeps the original single-env behavior working).

Passwords are never read from the profile YAML. Per-env passwords come from the
gitignored ``actone-ops.secrets.yaml`` (``{env: password}``) or a per-env env var
``ACTONE_PASSWORD__<ENV>``; a global ``ACTONE_PASSWORD`` is the last-resort
fallback. ``list_environments`` returns each environment's metadata (never the
password).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from actone.client import load_env
from actwise.paths import find_config

DEFAULT_PROFILE_PATH = find_config("actone-ops.yaml")
# Per-env passwords live here (gitignored); never in the profile YAML.
DEFAULT_SECRETS_PATH = find_config("actone-ops.secrets.yaml")

# The built-in environment name. It resolves url/user/password from the process
# env and <workdir>/.env exactly as the original single-env ops agent did, so a
# machine with a .env keeps working with zero config.
DEFAULT_ENV = "default"

_TRUTHY = {"1", "true", "yes", "on"}

_DISCRETE = ("url", "user", "context_root")  # password handled separately
_ENV_MAP = {
    "url": "ACTONE_URL",
    "user": "ACTONE_USER",
    "context_root": "ACTONE_CONTEXT_ROOT",
}


class OpsConfigError(Exception):
    """Environment could not be resolved (unknown name or missing credentials)."""


@dataclass
class OpsConfig:
    name: str
    url: str
    user: str
    password: str
    context_root: str | None = None
    requires_vpn: bool = False
    allow_writes: bool = False
    notes: str | None = None

    @property
    def target(self) -> str:
        """Human-readable target (never includes the password)."""
        ctx = ("/" + self.context_root.strip("/")) if self.context_root else ""
        return f"{self.url.rstrip('/')}{ctx}"


def _load_profiles(path: Path | None = None) -> dict:
    path = path or DEFAULT_PROFILE_PATH
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return raw.get("profiles", raw) or {}


def writes_allowed(env: str | None = None, path: Path | None = None) -> bool:
    """Whether live writes are permitted for a named environment.

    Per-environment, config-driven, default-deny: a named environment allows
    writes only when its profile in ``actone-ops.yaml`` sets ``allow_writes: true``.
    The built-in ``default`` environment (no profile) is driven by the global
    ``ACTONE_ALLOW_WRITES`` env var instead.

    ``ACTONE_ALLOW_WRITES`` also acts as an emergency master **kill switch**: if it
    is set to an explicit falsey value (0/false/no/off), ALL writes are forced off
    regardless of any profile flag. A truthy global value never force-enables a
    named environment — those are governed solely by their profile flag.
    """
    raw = (os.environ.get("ACTONE_ALLOW_WRITES") or "").strip().lower()
    if raw and raw not in _TRUTHY:
        return False  # explicit falsey global = force all writes off
    env = env or os.getenv("ACTONE_OPS_ENV") or DEFAULT_ENV
    if env == DEFAULT_ENV:
        return raw in _TRUTHY  # built-in default env: global flag only
    prof = _load_profiles(path).get(env) or {}
    return bool(prof.get("allow_writes", False))


def _load_secrets(path: Path | None = None) -> dict:
    """Per-env passwords: ``{env: password}`` or ``{env: {password: ...}}``."""
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


def _env_pw_key(env: str) -> str:
    """Per-env password env var, e.g. env ``qas-dev`` -> ACTONE_PASSWORD__QAS_DEV."""
    slug = re.sub(r"[^A-Z0-9]+", "_", (env or DEFAULT_ENV).upper()).strip("_")
    return f"ACTONE_PASSWORD__{slug}"


def _resolve_password(
    env: str,
    profile_pw: str | None,
    flag_pw: str | None,
    secrets_path: Path | None = None,
) -> str | None:
    """Password precedence (highest first): flag > per-env env > secrets file >
    global ``ACTONE_PASSWORD`` > profile/.env value."""
    if flag_pw is not None:
        return flag_pw
    name = env or DEFAULT_ENV
    per_env = os.getenv(_env_pw_key(name))
    if per_env:
        return per_env
    secrets = _load_secrets(secrets_path)
    if secrets.get(name) is not None:
        return secrets[name]
    if os.getenv("ACTONE_PASSWORD"):
        return os.environ["ACTONE_PASSWORD"]
    return profile_pw


def list_environments(path: Path | None = None, secrets_path: Path | None = None) -> list[dict]:
    """Configured ActOne ops environments (metadata only — **never passwords**).

    Always includes the built-in ``default`` environment (the ``<workdir>/.env``
    instance). ``password_configured`` reports whether a password source exists
    without revealing it.
    """
    profiles = _load_profiles(path)
    default = os.getenv("ACTONE_OPS_ENV") or DEFAULT_ENV
    names = list(profiles.keys())
    if DEFAULT_ENV not in names:
        names.insert(0, DEFAULT_ENV)

    fileenv = load_env()
    out: list[dict] = []
    for name in names:
        if name == DEFAULT_ENV:
            url = os.getenv("ACTONE_URL") or fileenv.get("ACTONE_URL") or fileenv.get("BASE_URL")
            user = os.getenv("ACTONE_USER") or fileenv.get("ACTONE_USER") or fileenv.get("USERNAME")
            ctx = os.getenv("ACTONE_CONTEXT_ROOT") or fileenv.get("ACTONE_CONTEXT_ROOT")
            profile_pw = fileenv.get("ACTONE_PASSWORD") or fileenv.get("PASSWORD")
            requires_vpn = False
            notes = "built-in: reads <workdir>/.env + process env"
        else:
            prof = profiles.get(name) or {}
            url = prof.get("url")
            user = prof.get("user")
            ctx = prof.get("context_root")
            profile_pw = prof.get("password")
            requires_vpn = bool(prof.get("requires_vpn"))
            notes = prof.get("notes")
        pw_source = (
            bool(os.getenv(_env_pw_key(name)))
            or _load_secrets(secrets_path).get(name) is not None
            or bool(os.getenv("ACTONE_PASSWORD"))
            or profile_pw is not None
        )
        out.append({
            "name": name,
            "url": url,
            "user": user,
            "context_root": ctx,
            "requires_vpn": requires_vpn,
            "allow_writes": writes_allowed(name, path),
            "notes": notes,
            "password_configured": pw_source,
            "is_default": name == default,
        })
    return out


def resolve(env: str | None = None, path: Path | None = None, **overrides) -> OpsConfig:
    """Merge default/.env -> named environment -> process env -> flags into an OpsConfig.

    ``env`` selects a named environment from ``actone-ops.yaml``; ``None`` (or
    ``default``) uses the ``<workdir>/.env`` instance. ``overrides`` are CLI flags
    (url/user/password/context_root); ``None`` values are ignored.
    """
    env = env or os.getenv("ACTONE_OPS_ENV") or DEFAULT_ENV
    profiles = _load_profiles(path)

    values: dict[str, str | None] = {"url": None, "user": None, "context_root": None}
    profile_pw: str | None = None
    requires_vpn = False
    notes: str | None = None

    if env != DEFAULT_ENV:
        if env not in profiles:
            known = ", ".join(sorted(profiles)) or "(none)"
            raise OpsConfigError(f"unknown environment {env!r}; defined: {known}")
        prof = profiles[env] or {}
        for key in _DISCRETE:
            if prof.get(key) is not None:
                values[key] = prof[key]
        profile_pw = prof.get("password")
        requires_vpn = bool(prof.get("requires_vpn"))
        notes = prof.get("notes")
    else:
        # built-in default: <workdir>/.env values (process env applied below wins)
        fileenv = load_env()
        values["url"] = fileenv.get("ACTONE_URL") or fileenv.get("BASE_URL")
        values["user"] = fileenv.get("ACTONE_USER") or fileenv.get("USERNAME")
        values["context_root"] = fileenv.get("ACTONE_CONTEXT_ROOT")
        profile_pw = fileenv.get("ACTONE_PASSWORD") or fileenv.get("PASSWORD")

    # process env overrides (global ACTONE_URL / ACTONE_USER / ACTONE_CONTEXT_ROOT)
    for key, env_var in _ENV_MAP.items():
        if os.getenv(env_var):
            values[key] = os.environ[env_var]

    # explicit flags win
    for key in _DISCRETE:
        if overrides.get(key) is not None:
            values[key] = overrides[key]

    password = _resolve_password(env, profile_pw, overrides.get("password"))

    if not (values["url"] and values["user"] and password):
        raise OpsConfigError(
            f"environment {env!r} is missing credentials: need url + user + "
            f"password (set them in actone-ops.yaml / actone-ops.secrets.yaml, "
            f"in <workdir>/.env, or pass --url/--user/--password)"
        )

    return OpsConfig(
        name=env,
        url=str(values["url"]),
        user=str(values["user"]),
        password=str(password),
        context_root=(str(values["context_root"]) if values["context_root"] else None),
        requires_vpn=requires_vpn,
        allow_writes=writes_allowed(env, path),
        notes=notes,
    )
