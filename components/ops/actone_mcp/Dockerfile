# ActWise ActOne-Ops MCP — portable image (FastMCP + uvicorn, Streamable HTTP).
#
# Build (from repo root):
#   docker build -f actone_mcp/Dockerfile -t actwise-actone-ops .
#
# Run locally (inject ActOne creds as env vars; set an API key for shared use):
#   docker run --rm -p 8765:8765 --env-file .env \
#     -e ACTONE_PROXY_API_KEY=poc-actone-key-local \
#     actwise-actone-ops
#   # endpoint: http://localhost:8765/mcp   health: http://localhost:8765/healthz
#
# NOTE ON NETWORK REACHABILITY: invoke_op / version connect to the live ActOne at
# ACTONE_URL. The container can only reach it if the host/network can (e.g. a
# private 10.x lab IP needs the container to run on that network / VPN, or the
# service to be deployed inside the same VPC as ActOne). Offline discovery
# (search_ops / list_ops / describe_op / list_tags) works with no network.
FROM python:3.12-slim

WORKDIR /app

# Runtime deps only (no typer/rich/requests — the server path imports just
# actone.registry (PyYAML) + actone.invoke (stdlib) + the MCP/HTTP stack).
COPY actone_mcp/requirements.txt /app/actone_mcp/requirements.txt
RUN pip install --no-cache-dir -r /app/actone_mcp/requirements.txt

# The actone package (registry, invoke, client, paths) + its bundled OpenAPI spec
# under actone/data/ ship in the image so offline discovery works with no volume.
COPY actone/ /app/actone/
COPY actone_mcp/ /app/actone_mcp/

# Credentials are injected at run time as env vars (ACTONE_URL / ACTONE_USER /
# ACTONE_PASSWORD / ACTONE_CONTEXT_ROOT) — never baked into the image.
ENV ACTONE_MCP_HOST=0.0.0.0 \
    ACTONE_MCP_PORT=8765 \
    PYTHONUNBUFFERED=1

EXPOSE 8765

CMD ["sh", "-c", "python -m uvicorn actone_mcp.server:app --host ${ACTONE_MCP_HOST:-0.0.0.0} --port ${ACTONE_MCP_PORT:-8765}"]
