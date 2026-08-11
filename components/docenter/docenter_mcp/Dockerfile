# ActWise remote DOCenter MCP — portable image.
# Mirrors NICE CoreAI's runtime (FastMCP + uvicorn) so promotion is an image handoff.
#
# Build (from repo root):
#   docker build -f components/docenter/docenter_mcp/Dockerfile -t actwise-docenter-mcp .
#
# Run locally (inject the portal cookie as an env var; set an API key for shared use):
#   docker run --rm -p 8765:8765 \
#     -e DOCENTER_PROXY_API_KEY=<your-api-key> \
#     -e DOCENTER_COOKIES_JSON="$(cat browser-profile/session-cookies.json)" \
#     actwise-docenter-mcp
#   # endpoint: http://localhost:8765/mcp   health: http://localhost:8765/healthz
FROM python:3.12-slim

WORKDIR /app

# Pull the latest Debian security patches for the base OS packages (perl, glibc,
# sqlite3, etc.) at build time. These OS-base CVEs are not in our Python code;
# rebuild the image periodically (e.g. weekly) so freshly-published fixes land.
RUN apt-get update \
    && apt-get -y upgrade \
    && rm -rf /var/lib/apt/lists/*

# Install the whole actwise distribution (pyproject-driven) — pulls docenter.cli's
# runtime deps (typer, rich, beautifulsoup4, pyyaml, python-dotenv, msal, requests,
# mcp) plus the server extras (uvicorn, starlette, html2text).
# Playwright ships as a dep but is ONLY used by `docenter auth login` (never at
# runtime), so we deliberately do NOT run `playwright install` (no browser
# binaries) — keeps the image small.
# The [aws] extra adds boto3 so the per-user cookie store can use its S3 backend
# (DOCENTER_USER_STORE_S3_BUCKET); harmless when unset (filesystem default).
COPY pyproject.toml README.md /app/
COPY components/ /app/components/
RUN pip install --no-cache-dir "/app[aws]"

# Product catalog for get_catalog / latest-version fallback (NOT secret, ~1 MB).
# raw_docs/ (352 MB) is deliberately NOT copied — the live server queries the
# portal and never needs the offline corpus.
COPY docs/catalog.yaml /app/docs/catalog.yaml

# The portal cookie is the ONLY secret and is injected at run time as
# DOCENTER_COOKIES_JSON (see entrypoint.sh) — never baked into the image.

ENV DOCENTER_CATALOG_FILE=/app/docs/catalog.yaml \
    DOCENTER_MCP_HOST=0.0.0.0 \
    DOCENTER_MCP_PORT=8765 \
    PYTHONUNBUFFERED=1

EXPOSE 8765

# entrypoint.sh materialises the injected cookie to a file, then execs uvicorn
# (stateless_http app — identical runtime to NICE CoreAI, so promotion is an image handoff).
COPY components/docenter/docenter_mcp/entrypoint.sh /app/entrypoint.sh
# Normalize CRLF -> LF so the image starts even when a Windows checkout (git
# autocrlf) introduced carriage returns into the shebang; then make executable.
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
