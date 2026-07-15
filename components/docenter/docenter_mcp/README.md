# ActWise remote DOCenter MCP

A remote **Streamable-HTTP MCP server** that exposes the **live NICE Actimize
documentation portal** as Model Context Protocol tools. It wraps the proven
`docenter` live-portal functions (the same code path `copilot_proxy` runs), so any
MCP client — GitHub Copilot CLI/VS Code, Claude Code, Copilot Studio — can search
the docs through one URL.

**Why it exists / strategy:** the goal is to host this in **NICE CoreAI** (which runs
internal MCP servers on FastMCP + uvicorn). This package uses the *identical* runtime,
so we can **prove it on a desktop now** and **port to CoreAI** as a container/image
handoff — no rewrite.

> Not to be confused with NICE's upstream `docenter-mcp-server` (a separate RAG
> service). This server does **live, version-precise portal
> search** and ships a **working `list_docs`** (the upstream one currently times out).

## Tools (lean, read-only)

| Tool | Purpose |
|------|---------|
| `search_docs(query, product?, doc_version?, guide?, bundle?, max_results?, page?, retry?)` | Faceted live search → ranked results (title, snippet, shortDesc, updated, version, `portal_url` citation), spelling correction, suggestions, `totalMatches`. |
| `list_docs(product, version?, doc_type?)` | Bundles for a product (live discovery), filtered by version / doc type. |
| `find_bundles(query, product?, doc_version?, max_results?)` | Which doc bundles answer a query — pick a `product`/`doc_version` (or a `bundle` for `search_docs`) to narrow a follow-up search. |
| `get_catalog(product?)` | Authoritative product↔slug↔version map — disambiguate a product / pick a slug (no portal round-trip). |
| `get_page(url, max_chars?)` | Full page text (HTML→Markdown) for a search result's `portal_url` — read beyond the snippet. |
| `get_toc(bundle, title_filter?, max_pages?)` | A bundle's table of contents (real page titles + URLs) — browse a guide, spot the newest release page, pick a page for `get_page`. |

**Full tool reference** — parameters, return shapes, examples, facet gotchas, and
client/raw-HTTP usage: **[TOOLS.md](./TOOLS.md)**.

## Prerequisites

1. A portal session cookie at `browser-profile/session-cookies.json`
   (`docenter auth login` to create/refresh; ~monthly MFA re-login). For password
   accounts, `docenter auth login --http` mints it browser-free, and the server
   **auto-refreshes** it on expiry — see [Session auto self-heal](#session-auto-self-heal).
2. The product catalog at `raw_docs/index/` (`docenter catalog refresh`).

## Run locally (desktop proof)

```powershell
# from the repo root
py -m pip install .
py -m uvicorn docenter_mcp.server:app --host 0.0.0.0 --port 8765
```

- MCP endpoint: `http://localhost:8765/mcp`
- Health probe:  `http://localhost:8765/healthz`

### Optional auth (recommended once shared/tunnelled)

```powershell
$env:DOCENTER_PROXY_API_KEY = "<your-api-key>"   # clients send header X-API-Key
```

When unset, the server runs open (fine for localhost-only proving).

## Share with the team (option 5 → desktop host)

Expose the local port over HTTPS with a quick tunnel, then have teammates point their
client at the tunnel URL.

```powershell
cloudflared tunnel --url http://localhost:8765
```

Client config (replace URL with the tunnel; add the header if you set a key):

```jsonc
// GitHub Copilot CLI — ~/.copilot/mcp-config.json
{ "mcpServers": { "DOCenterLive": { "type": "http", "url": "https://<tunnel>/mcp" } } }

// VS Code — .vscode/mcp.json (servers: { ... })
{ "DOCenterLive": { "type": "http", "url": "https://<tunnel>/mcp" } }
```

## Run as a container (porting dry-run)

```bash
docker build -f docenter_mcp/Dockerfile -t actwise-docenter-mcp .
docker run --rm -p 8765:8765 \
  -e DOCENTER_PROXY_API_KEY=<your-api-key> \
  -v "$PWD/browser-profile:/app/browser-profile:ro" \
  -v "$PWD/raw_docs/index:/app/raw_docs/index:ro" \
  actwise-docenter-mcp
```

## Deployed on AWS App Runner

The live instance runs on **AWS App Runner** (public HTTPS + `X-API-Key`, secrets from AWS
Secrets Manager, session auto self-heal on cookie expiry). Build/push/deploy is one command:

```powershell
pwsh docenter_mcp/deploy.ps1        # build -> ECR push -> update-service -> wait -> verify /healthz
```

Full resource inventory, manual fallback, self-heal verification, Copilot Studio wiring,
rollback, and the CI/CD path: **[docs/runbooks/2026-07-11-docenter-mcp-aws-deployment-runbook.md](../docs/runbooks/2026-07-11-docenter-mcp-aws-deployment-runbook.md)**.

## Porting to CoreAI

The image is the deliverable. CoreAI runs FastMCP + uvicorn behind a load balancer,
so promotion means:

1. Hand over this image (or the `docenter/` + `docenter_mcp/` source).
2. Provide the portal credential as a **service account / API key** (replaces the
   browser cookie — the durable-auth ask in flight with NICE). No client changes.
3. Front it with the CoreAI ingress + `X-API-Key` (already supported here).
4. `stateless_http=True` means it scales horizontally with no session affinity.

## Config / env vars

| Var | Default | Meaning |
|-----|---------|---------|
| `DOCENTER_PROXY_API_KEY` | _(unset)_ | Shared secret; when set, clients must send `X-API-Key`. |
| `DOCENTER_MCP_HOST` | `0.0.0.0` | Bind host. |
| `DOCENTER_MCP_PORT` | `8765` | Bind port. |
| `DOCENTER_MCP_MAX_RESULTS` | `50` | Per-call `max_results` ceiling for `search_docs` / `find_bundles`. |
| `DOCENTER_API_URL` | portal default | Override the Zoomin API base (inherited from `docenter`). |
| `DOCENTER_EMAIL` / `DOCENTER_PASSWORD` | _(unset)_ | Portal creds (from `.env`) used for browser-free auto re-login on 403. Password accounts only. |
| `DOCENTER_MCP_RELOGIN_COOLDOWN` | `60` | Min seconds between auto re-login attempts (throttle vs. portal lockout). |

## Session auto self-heal

The portal `_SESSION` cookie expires (~monthly). When a tool call gets a **403**, the
server attempts **one browser-free HTTP re-login** using `DOCENTER_EMAIL` /
`DOCENTER_PASSWORD` from the environment (primes `/auth/login`, POSTs to the Zoomin
login API, saves the fresh cookie to `browser-profile/session-cookies.json`), then
**retries the call once** — so a mid-conversation expiry heals transparently.

Guardrails:
- **Throttled** to one attempt per `DOCENTER_MCP_RELOGIN_COOLDOWN` (default 60s); concurrent
  403s reuse the last outcome — no login stampede (avoids portal bot-detection / lockout).
- If creds are unset or the re-login fails, the call surfaces the usual *"refresh with
  `docenter auth login`"* error instead.
- **Password accounts only** — SSO-only accounts can't re-login headless; use `docenter auth login`.
- Creds are never logged.

To mint/refresh the cookie manually without a browser: `docenter auth login --http`.
