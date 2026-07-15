# ActWise Data MCP — portable image (FastMCP + uvicorn, Streamable HTTP).
#
# Build (from repo root):
#   docker build -f actone_data_mcp/Dockerfile -t actwise-actone-data .
#
# Run (inject DB creds as env vars; set an API key for shared use):
#   docker run --rm -p 8766:8766 --env-file .env \
#     -e ACTONE_DATA_PROXY_API_KEY=poc-actone-data-key-local \
#     actwise-actone-data
#   # endpoint: http://localhost:8766/mcp   health: http://localhost:8766/healthz
#
# NOTE ON NETWORK REACHABILITY: validate_sql / run_query connect to the live
# PostgreSQL at ACTONE_DB_HOST. The container can only reach it if the
# host/network can (a private lab DB needs the container on that network / VPN,
# or the service deployed in the same VPC). The grounding tools
# (get_schema_summary / list_views / describe_view) work offline from the bundled
# schema pack with no DB connection.
FROM python:3.12-slim

WORKDIR /app

# Runtime deps only (the server path imports actone_data.{config,db,guardrails,
# audit,schema_pack,docs_enrich} + the MCP/HTTP stack — no typer/rich).
COPY actone_data_mcp/requirements.txt /app/actone_data_mcp/requirements.txt
RUN pip install --no-cache-dir -r /app/actone_data_mcp/requirements.txt

# The actone_data package + its bundled schema pack (actone_data/data/) ship in
# the image so the grounding tools work with no volume.
COPY actone_data/ /app/actone_data/
COPY actone_data_mcp/ /app/actone_data_mcp/

# DB credentials are injected at run time as env vars (ACTONE_DB_HOST /
# ACTONE_DB_NAME / ACTONE_DB_USER / ACTONE_DB_PASSWORD / ACTONE_DB_SCHEMA) —
# never baked into the image.
ENV ACTONE_DATA_MCP_HOST=0.0.0.0 \
    ACTONE_DATA_MCP_PORT=8766 \
    PYTHONUNBUFFERED=1

EXPOSE 8766

CMD ["sh", "-c", "python -m uvicorn actone_data_mcp.server:app --host ${ACTONE_DATA_MCP_HOST:-0.0.0.0} --port ${ACTONE_DATA_MCP_PORT:-8766}"]
