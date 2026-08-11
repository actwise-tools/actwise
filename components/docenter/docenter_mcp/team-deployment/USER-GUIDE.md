# DOCenter MCP — user guide

Connect your MCP client to the deployed DOCenter MCP and search the **live** NICE
Actimize documentation portal from inside your AI assistant. Every result comes back
with a **citation URL** so you can verify the source.

You need two things from whoever deployed the service:

1. the service **URL** (e.g. `https://<your-service-host>`), and
2. the **API key** value (the `X-API-Key`) — share this over a secure channel.

The MCP endpoint is `<url>/mcp`; the health probe is `<url>/healthz`.

---

## 1. Connect your client

### GitHub Copilot CLI — `~/.copilot/mcp-config.json`

```jsonc
{ "mcpServers": { "DOCenterLive": {
    "type": "http",
    "url": "https://<your-service-host>/mcp",
    "headers": { "X-API-Key": "<the-api-key>" }
} } }
```

### VS Code — `.vscode/mcp.json`

```jsonc
{ "servers": { "DOCenterLive": {
    "type": "http",
    "url": "https://<your-service-host>/mcp",
    "headers": { "X-API-Key": "<the-api-key>" }
} } }
```

### Claude Code / other MCP clients

Use the same three fields: **type** `http`, **url** `https://<your-service-host>/mcp`,
and a header **`X-API-Key`** with the shared key.

### Copilot Studio → Add MCP server

| Field | Value |
|---|---|
| Server URL | `https://<your-service-host>/mcp` |
| Authentication | **API key** |
| Parameter type | **Header** |
| Header name | `X-API-Key` |
| Key value | the shared API key |

> Copilot Studio requires the endpoint to be **publicly reachable** over HTTPS.

After adding the server, restart/reload your client so it discovers the tools.

---

## 2. Verify the connection

```bash
# Health (no auth needed) — should return 200 with a JSON status.
curl -fsS https://<your-service-host>/healthz
# -> {"status":"ok","server":"actwise-docenter-live"}
```

Then, in your assistant, ask a documentation question (e.g. *"search the Actimize docs
for DART"*). If tools are wired correctly it will call `search_docs` and return ranked
pages with `portal_url` links.

---

## 3. The tools (all read-only)

| Tool | Use it to… |
|---|---|
| `search_docs(query, product?, doc_version?, guide?, bundle?, max_results?, page?)` | Search the live portal → ranked pages with title, snippet, version, and a `portal_url` citation. Use **keyword** queries (one concept), narrow with `product`/`doc_version` rather than long sentences. |
| `list_docs(product, version?, doc_type?)` | List a product's documentation **bundles**, optionally filtered by version / doc type. |
| `find_bundles(query, product?, doc_version?, max_results?)` | Discover **which bundles** answer a query, so you can pick a `product`/`doc_version`/`bundle` to narrow a follow-up `search_docs`. |
| `get_catalog(product?)` | Get the authoritative **product ↔ slug ↔ version** map to disambiguate a product name or pick the right slug (no portal round-trip). |
| `get_page(url, max_chars?)` | Fetch the **full page text** (HTML → Markdown) behind a search result's `portal_url` — read beyond the snippet. |
| `get_toc(bundle, title_filter?, max_pages?)` | Get a bundle's **table of contents** (real page titles + URLs) to browse a guide or find the newest release page. |

Full parameter and return reference: [`../TOOLS.md`](../TOOLS.md).

---

## 4. Tips for good results

- **Keyword, not prose.** `search_docs` ranks by keyword match, not meaning. Prefer
  `"conditional step change plugin"` over *"how do I change a step conditionally"*.
- **Narrow with facets, not longer queries.** Add `product` (e.g. `actone`, `ifm`,
  `sam`) and `doc_version` (e.g. `"10.1"`) to focus. Resolve product names with
  `get_catalog`.
- **Omit `doc_version` for the latest.** Leaving it out auto-defaults to the product's
  newest version.
- **Drill down:** `find_bundles` → pick a `bundle` → `search_docs(bundle=…)` or
  `get_toc(bundle)` → `get_page(url)` for the full text.
- **Always cite.** Every result includes a `portal_url` — use it to link back to the
  official page.

---

## 5. Troubleshooting

| Symptom | Fix |
|---|---|
| Client shows no DOCenter tools | Check the `url` ends in `/mcp` and the `X-API-Key` header is set; reload the client. |
| `401 Unauthorized` | The API key is wrong or missing — confirm the exact value (no extra spaces) with whoever deployed it. |
| `/healthz` fails | The service is down or the URL is wrong — contact the deployer. |
| A query returns nothing | Try fewer keywords, drop the `guide` filter (a non-matching guide silently empties results), or omit `doc_version`. |
| Results look stale | They aren't cached — the server queries the **live** portal every call. If a page 404s, it may have moved to a newer version bundle. |
