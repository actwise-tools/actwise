#!/bin/sh
# ActWise DOCenter MCP — container entrypoint.
#
# Secret stores (AWS App Runner / ECS / Azure Container Apps) inject the portal
# session cookie as an ENV VAR, but docenter.load_session() reads it from a FILE
# (DOCENTER_COOKIES_FILE). This shim materialises the injected JSON to a file at
# startup, then hands off to uvicorn. No secrets are baked into the image.
set -e

if [ -n "${DOCENTER_COOKIES_JSON:-}" ]; then
  printf '%s' "$DOCENTER_COOKIES_JSON" > /tmp/session-cookies.json
  export DOCENTER_COOKIES_FILE=/tmp/session-cookies.json
fi

exec python -m uvicorn docenter_mcp.server:app \
  --host "${DOCENTER_MCP_HOST:-0.0.0.0}" \
  --port "${DOCENTER_MCP_PORT:-8765}"
