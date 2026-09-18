#!/bin/sh
# ActWise DOCenter MCP — container entrypoint.
#
# Secret stores (AWS App Runner / ECS / Azure Container Apps) inject the portal
# session cookie as an ENV VAR, but docenter.load_session() reads it from a FILE
# (DOCENTER_COOKIES_FILE). This shim materialises the injected JSON to a file at
# startup, then hands off to uvicorn. No secrets are baked into the image.
set -e

# Point the cookie store at a writable path in all cases. When a cookie is injected we
# materialise it here; when it isn't (creds-only cold start), the server mints one to
# this same path via browser-free HTTP login, and self-heal rewrites it here too.
export DOCENTER_COOKIES_FILE="${DOCENTER_COOKIES_FILE:-/tmp/session-cookies.json}"
if [ -n "${DOCENTER_COOKIES_JSON:-}" ]; then
  printf '%s' "$DOCENTER_COOKIES_JSON" > "$DOCENTER_COOKIES_FILE"
fi

# Bind port. Guard against Kubernetes service-link injection: a Service named
# "docenter-mcp" makes k8s set DOCENTER_MCP_PORT=tcp://<ip>:8765 (non-empty, so the
# :-default won't apply). If the value isn't a plain integer, fall back to 8765.
DOCENTER_MCP_PORT="${DOCENTER_MCP_PORT:-8765}"
case "$DOCENTER_MCP_PORT" in
  ''|*[!0-9]*) DOCENTER_MCP_PORT=8765 ;;
esac

exec python -m uvicorn docenter_mcp.server:app \
  --host "${DOCENTER_MCP_HOST:-0.0.0.0}" \
  --port "${DOCENTER_MCP_PORT}"
