# docenter-mcp

> Re-exposes the **live** NICE Actimize documentation portal as MCP tools —
> version-precise search and full-page fetch, always with citation URLs.

## Goal

Let an agent answer NICE Actimize product questions from the *live* portal
(`docs.niceactimize.com`, Zoomin) rather than a stale local index. It runs a
faceted, version-aware search, discovers the right bundles, and returns full page
text as Markdown so answers can quote and cite the source. All tools are
**read-only** — the server never mutates the portal or any live system.

## How it fits

- **Bucket:** [docenter](../buckets/docenter.md).
- **Shares code with:** the [`docenter`](../cli/docenter.md) CLI — the MCP tools
  drive the same proven portal code path (`search`, `list-docs`, catalog), so the
  server is always as fresh as the CLI.
- **Consumed by:** the **ActWise Docs** Copilot Studio agent
  ([agent page](../agents/docs.md)), which is grounded on this server
  over a self-hosted MCP endpoint (managed public HTTPS, no VPN/tunnel). Local
  IDE agents (VS Code, Claude Code, the GitHub Copilot CLI) can register it too.

## Tools exposed

Enumerated from `components/docenter/docenter_mcp/server.py` (six `@mcp.tool`
registrations) and its published contract in `docenter_mcp/TOOLS.md`.

| Tool | What it does |
|------|--------------|
| `search_docs` | Faceted live search → ranked pages with citation `portal_url`s. Auto-defaults to the product's newest version and falls back/broadens when a version scope is thin. |
| `list_docs` | List a product's doc bundles via live discovery, filterable by version / doc type (newest-first). |
| `find_bundles` | Run a live search and aggregate the distinct bundles among hits, ranked by hit count — answers "where does this live?" before a precise `search_docs`. |
| `get_catalog` | The authoritative product↔slug↔version map (committed catalog, no portal round-trip) to disambiguate a product / pick a `product` slug. |
| `get_page` | Fetch a result's **full page text** as Markdown (read beyond the snippet) from a `portal_url`. |
| `get_toc` | A bundle's table of contents — every page title + URL — to browse a guide (e.g. find the newest release page) without searching. |

## Transport & run

**HTTP (Streamable HTTP, `stateless_http=True`).** Serves `POST /mcp` with a
`GET /healthz` liveness check; MCP protocol `2025-06-18`, server name
`actwise-docenter-live`. Launch it as the console script from `pyproject.toml`:

```powershell
docenter-mcp
# or, via ASGI:
python -m uvicorn docenter_mcp.server:app --port 8765
```

The server is **self-hosted**. When `DOCENTER_PROXY_API_KEY` is set it requires an
`X-API-Key` header (mandatory for any shared/tunnelled/cloud deployment); the
ActWise Docs agent talks to it through a self-hosted, key-gated MCP endpoint.

## Safety

Strictly **read-only** — the tools search and fetch documentation only; they
never touch a live ActOne system, run queries, or perform operations. Portal
session errors surface as tool errors (cookie missing/expired), and the server
self-heals a 403 by re-logging in with `.env` credentials.

## See also

- CLI: [`docenter`](../cli/docenter.md)
- Bucket: [docenter](../buckets/docenter.md)
- Sibling server: [`actimize-docs-mcp`](actimize-docs-mcp.md) (offline BM25)
- Agent: [ActWise Docs](../agents/docs.md)
