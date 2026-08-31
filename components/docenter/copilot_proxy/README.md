# Copilot grounding proxy (POC)

A thin HTTPS API that exposes the `docenter` **live-portal search** so a Microsoft
Copilot Studio agent can ground answers on the NICE Actimize documentation portal
**without ingesting the corpus** — the "Option D" architecture from
`docs/components/docenter/2026-06-23-corpus-storage-layout-decision.md`.

```
Copilot Studio agent
  └─ OnKnowledgeRequested topic
       └─ custom connector (HTTP GET /search)  ──►  this proxy  ──►  docs portal
                                                     (holds the _SESSION cookie,
                                                      reuses docenter's hybrid
                                                      product/version/guide filters)
  ◄─ System.SearchResults { Title, Content, ContentLocation }
```

## What it does

- `GET /search` runs `docenter.cli.portal_search_core` (the same code path as
  `docenter search`): hybrid facet/`labelkeys` filtering for product/version, a
  `--guide` post-filter, and a one-shot spelling/synonym auto-retry.
- Maps each hit to Copilot's `System.SearchResults` shape:
  `{ Title, Content, ContentLocation }`, where `ContentLocation` is the canonical
  user-facing portal URL (the citation).
- `GET /healthz` — unauthenticated liveness probe.
- `GET /openapi.json` — OpenAPI 3.1 spec to import when creating the Copilot
  custom connector.

## Auth model (POC)

| Concern | POC behaviour |
|---------|---------------|
| Caller → proxy | Static shared secret in the `X-API-Key` header (env `DOCENTER_PROXY_API_KEY`). |
| Proxy → portal | The developer's own `_SESSION` cookie, loaded by `docenter.cli.load_session` from `browser-profile/session-cookies.json`. Refresh with `docenter auth login` (~monthly; MFA blocks fully-automated refresh). |
| Identity | The agent runs under **your** portal identity. POC only. |
| Production | Replace the cookie with a real service credential (OAuth client-credentials / API key) once the portal team confirms one — **no change to the Copilot side**. |

The portal cookie never leaves the proxy host; Copilot only ever sees the API key.

## Run it

```powershell
# 1. install the repo (provides docenter.cli) + proxy deps
pip install -e .

# 2. make sure a portal session exists
docenter auth login

# 3. set the shared secret and start the server
$env:DOCENTER_PROXY_API_KEY = "choose-a-long-random-string"
py -m uvicorn copilot_proxy.app:app --host 0.0.0.0 --port 8077
```

Smoke test:

```powershell
curl http://127.0.0.1:8077/healthz
curl -H "X-API-Key: $env:DOCENTER_PROXY_API_KEY" `
  "http://127.0.0.1:8077/search?q=Generic%20Batch%20Interface&product=ifm&doc_version=11.2&max=5"
```

### Expose over HTTPS (for Copilot)

Copilot Studio connectors require a public HTTPS endpoint. For the POC, front the
local server with a tunnel:

```powershell
# Azure dev tunnels
devtunnel host -p 8077 --allow-anonymous
# or ngrok
ngrok http 8077
```

Production: deploy to an Azure Container App / Function behind APIM, keep the
cookie/credential in Key Vault, and restrict the API key to the connector.

## Query parameters

| Param | Default | Notes |
|-------|---------|-------|
| `q` | (required) | The user's query. |
| `product` | – | Product key/name, e.g. `actone`, `ifm`, `sam`. |
| `doc_version` | – | Doc version, e.g. `10.1`, `11.2`. |
| `guide` | – | Guide type, e.g. `implementer`, `reference`. |
| `max` | `5` | 1–20. Keep small for the model's token budget. |
| `page` | `1` | Result page. |
| `retry` | `true` | Auto-retry the portal's `did_you_mean`/synonym when empty. |

Response:

```json
{
  "value": [
    { "Title": "Define a GBI Job",
      "Content": "Configure the Generic Batch Interface job ...",
      "ContentLocation": "https://docs.niceactimize.com/bundle/IFM/page/gbi.htm" }
  ],
  "originalQuery": "gbi",
  "correctedQuery": null,
  "suggestions": []
}
```

## Wire into Copilot Studio (Option D)

A generated copy of the spec is committed at **`copilot_proxy/openapi.json`** (typed
`SearchResponse`/`SearchResultItem`, `operationId: searchDocs`) so you can import it
without a running server. Regenerate it after any endpoint change:

```powershell
py -c "import json; from copilot_proxy.app import app; open('copilot_proxy/openapi.json','w',encoding='utf-8').write(json.dumps(app.openapi(), indent=2, ensure_ascii=False))"
```

The full step-by-step authoring blueprint is in
`docs/agents/2026-06-24-copilot-agent-authoring-blueprint.md`.

1. **Custom connector** — import `copilot_proxy/openapi.json` (or live `/openapi.json`);
   set the API-key (`X-API-Key`) security to the shared secret; point the host at the
   tunnel/APIM URL.
2. **`OnKnowledgeRequested` topic** (YAML-only — author/govern as YAML) — call the
   connector with `System.SearchQuery` plus product/version/guide extracted via
   Orchestrator-Generated Variables, then map the response `value[]` into
   `System.SearchResults` (`Title`, `Content`, `ContentLocation`).
3. Add a **Knowledge Hold Message** (latency), disable model knowledge for strict
   grounding, and a tool-call-leak guard. See the blueprint and decision doc for the
   full behaviour→pattern mapping.

## Tests

```powershell
py -m pytest tests/test_proxy.py -q
```

Offline — the portal search core is monkeypatched, so no network/auth/cookie is
needed.
