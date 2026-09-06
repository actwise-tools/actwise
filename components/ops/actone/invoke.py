#!/usr/bin/env python
"""
invoke.py — turn a registry operation + caller params into a live ActOne request.

Read/write gate: operations classified `read` (GET/HEAD) always run. Writes are
refused unless the caller opts in. The policy is per-environment and default-deny
(see ``actone.ops_config.writes_allowed``): a named environment permits writes only
when its ``actone-ops.yaml`` profile sets ``allow_writes: true``; the built-in
``default`` environment is governed by the global ``ACTONE_ALLOW_WRITES`` env var.
The CLI ``--allow-write`` flag is an additional per-invocation human override. The
gate lives here so both the CLI and MCP server inherit it.

Params model (flat dict):
  - path/query/header params are passed by their spec name
  - a request body is passed under the reserved key "body" (a dict)
"""
import re

from actone.client import ActOneClient
from actone.registry import load_registry

_PATH_VAR = re.compile(r"\{([^}]+)\}")


def writes_enabled(env=None):
    """True when live writes are permitted for the target environment.

    Delegates to ``actone.ops_config.writes_allowed`` so the policy is
    per-environment and config-driven (default-deny): a named environment allows
    writes only when its profile in ``actone-ops.yaml`` sets ``allow_writes: true``;
    the built-in ``default`` environment is governed by the global
    ``ACTONE_ALLOW_WRITES`` env var. That global var also doubles as an emergency
    force-all-off kill switch. Kept here so the CLI and MCP server share one gate;
    the model/agent cannot lift it."""
    from actone.ops_config import writes_allowed
    return writes_allowed(env)


class InvokeError(Exception):
    pass


def _build(op, params):
    """Resolve path, split params into query/header, extract body. Returns parts."""
    params = dict(params or {})
    body = params.pop("body", None)

    by_loc = {}
    for p in op["params"]:
        by_loc.setdefault(p["in"], {})[p["name"]] = p

    # path params
    path = op["path"]
    missing = []
    for var in _PATH_VAR.findall(path):
        if var in params:
            path = path.replace("{%s}" % var, str(params.pop(var)))
        else:
            missing.append(var)
    if missing:
        raise InvokeError("missing required path params: %s" % ", ".join(missing))

    query, headers = {}, {}
    for name, val in params.items():
        loc = next((p["in"] for p in op["params"] if p["name"] == name), "query")
        if loc == "header":
            headers[name] = val
        else:
            query[name] = val

    if body is None and op.get("requestBody") and op["requestBody"].get("required"):
        raise InvokeError(
            "operation requires a request body; pass it under 'body' "
            "(example available via describe)")
    return op["method"], path, query, body, headers


def _summarize(result, max_chars=4000):
    body = result.get("body")
    if isinstance(body, str) and len(body) > max_chars:
        body = body[:max_chars] + "... [truncated]"
    return {
        "status": result.get("status"),
        "ok": result.get("ok"),
        "method": result.get("method"),
        "url": result.get("url"),
        "content_type": result.get("content_type"),
        "error": result.get("error"),
        "body": body,
    }


def precheck(registry, op_id, allow_write=False):
    """Validate op existence + read/write gate WITHOUT touching the network.

    Returns the op dict, or raises InvokeError. Call this before logging in so
    unknown/gated operations fail fast and offline."""
    op = registry.ops.get(op_id)
    if not op:
        suggest = [o["operationId"] for o in registry.search(op_id, limit=5)]
        raise InvokeError(
            "unknown operationId %r%s" % (
                op_id, (" — did you mean: " + ", ".join(suggest)) if suggest else ""))
    if not op["read"] and not allow_write:
        raise InvokeError(
            "operation %r is a WRITE (%s %s) but writes are disabled for the "
            "target environment. Enable it by setting `allow_writes: true` for "
            "that environment in actone-ops.yaml (or ACTONE_ALLOW_WRITES=true for "
            "the built-in default environment)." % (op_id, op["method"], op["path"]))
    return op


def invoke(registry, client, op_id, params=None, allow_write=False):
    """Execute op_id against the client. Returns a summarized result dict."""
    op = precheck(registry, op_id, allow_write)
    method, path, query, body, headers = _build(op, params)
    result = client.request(method, path, query=query, body=body, headers=headers or None)
    return _summarize(result)


def make_client(base_url=None, user=None, password=None, env=None):
    """Build an ActOneClient for a named environment (or explicit args / .env).

    Resolution is delegated to ``actone.ops_config`` so the CLI (``--env``) and the
    MCP server (``env`` tool argument) share one precedence: explicit args > process
    env > named environment in ``actone-ops.yaml`` > built-in ``default`` (the
    ``<workdir>/.env`` instance). ``env=None`` selects the ``default`` environment,
    preserving the original single-env behavior.
    """
    from actone.ops_config import resolve, OpsConfigError
    try:
        cfg = resolve(env, url=base_url, user=user, password=password)
    except OpsConfigError as e:
        raise InvokeError(str(e))
    return ActOneClient(cfg.url, cfg.user, cfg.password, context_root=cfg.context_root)


def open_session(spec_path=None, base_url=None, user=None, password=None, login=True, env=None):
    """Convenience: (registry, client) ready for search/describe/call."""
    registry = load_registry(spec_path)
    client = make_client(base_url, user, password, env=env)
    if login:
        client.login()
        client.detect_version()
    return registry, client
