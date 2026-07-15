# ActWise portal — static site + Direct Line token broker in one small image.
# Mirrors components/docenter/docenter_mcp/Dockerfile so the same ECR + App Runner
# deploy pattern applies. Cloud-agnostic: runs on App Runner, ECS/Fargate, Azure
# Container Apps, Cloud Run, or `docker run`.
#
# Build (from repo root):
#   docker build -f components/portal/Dockerfile -t actwise-portal .
#
# Run locally (inject the Direct Line secret; never bake it into the image):
#   docker run --rm -p 8080:8080 \
#     -e DIRECTLINE_SECRET="<web-channel-security-secret>" \
#     actwise-portal
#   # portal: http://localhost:8080/   health: http://localhost:8080/healthz
FROM python:3.12-slim

WORKDIR /app

# Backend deps only (FastAPI + uvicorn + httpx, plus PyJWT for the optional
# Entra SSO gate). Copied first so the layer caches across static-asset edits.
COPY components/portal/server/requirements.txt /app/server/requirements.txt
RUN pip install --no-cache-dir -r /app/server/requirements.txt

# App code: the token broker and the static portal it serves.
COPY components/portal/server/ /app/server/
COPY components/portal/web/ /app/web/

# DIRECTLINE_SECRET is the only required secret and is injected at run time
# (App Runner RuntimeEnvironmentSecrets / `docker run -e`) — never in the image.
ENV PORTAL_WEB_DIR=/app/web \
    PORTAL_PORT=8080 \
    PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8080"]
