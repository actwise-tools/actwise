"""ActWise portal backend — static host + Direct Line token broker.

One small FastAPI app that:
  * serves the static portal (../web) at /,
  * exposes GET /healthz for container health checks,
  * exposes POST /api/directline/token, exchanging a server-held Copilot Studio
    Direct Line secret for a short-lived Direct Line token so the secret never
    reaches the browser.

Config is 12-factor (env vars only) so the same image runs on AWS App Runner,
ECS/Fargate, Azure Container Apps, Cloud Run, or a plain `docker run`:

  DIRECTLINE_SECRET     (required)  Copilot Studio Web channel security secret.
  DIRECTLINE_ENDPOINT   (optional)  Regional Direct Line base, default the EU
                                    host the ActWise-Main1-Dev channel lives on.
  PORTAL_WEB_DIR        (optional)  Path to static assets, default ../web.
  PORTAL_PORT           (optional)  Listen port, default 8080.
  ENTRA_TENANT_ID       (optional)  If set with ENTRA_API_AUDIENCE, the token
  ENTRA_API_AUDIENCE    (optional)  endpoint requires a valid Entra access token
                                    (Bearer) and validates it against Entra JWKS.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# Use the OS trust store so requests work behind corporate TLS-inspection proxies
# (whose root CA is trusted by the machine but not by httpx's bundled certifi).
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001 - truststore is best-effort; fall back to certifi
    pass

# Regional Direct Line base for the ActWise-Main1-Dev channel (verified: the
# global host returns 403; the EU host mints tokens with conversationId "*-eu").
DEFAULT_DIRECTLINE_ENDPOINT = "https://europe.directline.botframework.com/v3/directline"

DIRECTLINE_SECRET = os.environ.get("DIRECTLINE_SECRET", "").strip()
DIRECTLINE_ENDPOINT = os.environ.get(
    "DIRECTLINE_ENDPOINT", DEFAULT_DIRECTLINE_ENDPOINT
).rstrip("/")
WEB_DIR = Path(
    os.environ.get("PORTAL_WEB_DIR", str(Path(__file__).resolve().parent.parent / "web"))
).resolve()

ENTRA_TENANT_ID = os.environ.get("ENTRA_TENANT_ID", "").strip()
ENTRA_API_AUDIENCE = os.environ.get("ENTRA_API_AUDIENCE", "").strip()
_ENTRA_ENABLED = bool(ENTRA_TENANT_ID and ENTRA_API_AUDIENCE)

app = FastAPI(title="ActWise portal", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict:
    return {
        "status": "ok",
        "directline_configured": bool(DIRECTLINE_SECRET),
        "directline_endpoint": DIRECTLINE_ENDPOINT,
        "entra_gate": _ENTRA_ENABLED,
    }


async def _require_entra_user(request: Request) -> None:
    """Validate the caller's Entra access token when the gate is enabled.

    No-op unless ENTRA_TENANT_ID and ENTRA_API_AUDIENCE are both set, so local
    dev works without an app registration while production can enforce SSO.
    """
    if not _ENTRA_ENABLED:
        return

    import jwt  # PyJWT[crypto]; imported lazily so it's only needed when gating
    from jwt import PyJWKClient

    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = auth.split(" ", 1)[1].strip()

    jwks_url = f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/discovery/v2.0/keys"
    issuer = f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/v2.0"
    try:
        signing_key = PyJWKClient(jwks_url).get_signing_key_from_jwt(token).key
        jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=ENTRA_API_AUDIENCE,
            issuer=issuer,
        )
    except Exception as exc:  # noqa: BLE001 - surface any validation failure as 401
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}") from exc


@app.post("/api/directline/token")
async def directline_token(request: Request) -> JSONResponse:
    if not DIRECTLINE_SECRET:
        raise HTTPException(status_code=503, detail="DIRECTLINE_SECRET not configured")

    await _require_entra_user(request)

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"{DIRECTLINE_ENDPOINT}/tokens/generate",
            headers={"Authorization": f"Bearer {DIRECTLINE_SECRET}"},
            json={},
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Direct Line token generation failed ({resp.status_code})",
        )

    data = resp.json()
    # Hand the client everything WebChat needs, including the regional domain.
    return JSONResponse(
        {
            "token": data["token"],
            "conversationId": data.get("conversationId"),
            "expires_in": data.get("expires_in"),
            "domain": DIRECTLINE_ENDPOINT,
        }
    )


# Static portal last so /healthz and /api/* win; html=True serves index.html at /.
if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


def main() -> None:
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORTAL_PORT", "8080")),
    )


if __name__ == "__main__":
    main()
