# DOCenter (components/docenter)

Search, extract, and publish the live NICE Actimize documentation portal. Packages: `docenter`, `docenter_mcp`, `extractor`, `mcp_server`, `copilot_proxy`, `sharepoint`. CLIs: `docenter`. MCP: `docenter-mcp` (live portal, HTTP), `actimize-docs-mcp` (local BM25, stdio). Skill(s): `skills/actimize-docenter`.

## Overview

DOCenter is the **documentation** pillar of ActWise — component **C-D(oc)** in the
[ecosystem blueprint](../../docs/2026-06-25-actwise-ecosystem-blueprint.md). It wraps the
Zoomin portal (`docs.niceactimize.com`): the `docenter` CLI searches/downloads/syncs
bundles, `extractor` converts `topic_html`→Markdown under `raw_docs/`, `mcp_server` serves
a local BM25 index, `docenter_mcp` re-exposes the *live* portal as MCP tools, and
`copilot_proxy` grounds a Copilot Studio agent on the portal without ingesting the corpus.
See the [portal overview](../../docs/components/docenter/docenter-portal-overview.md).

## Quick start

```powershell
uv tool install "git+ssh://git@github.com/vinayguda/actwise.git"   # puts docenter on PATH
docenter auth login                       # Zoomin SSO (browser); refresh ~monthly
docenter search "policy manager DART" --product actone --max 5
docenter list-docs actone --type "Release Notes"
```

## CLI reference

Run `docenter <command> --help` for flags.

| Command | Purpose |
|---------|---------|
| `search` | Search the live portal (or `--local` BM25 corpus); faceted by product/version/guide. |
| `list-categories` / `list-products` | Browse the catalog by category / product key. |
| `list-docs` | List a product's doc bundles (live discovery), by version / doc type. |
| `download` | Download bundles as Markdown or PDF into `raw_docs/`. |
| `sync` | Re-extract only bundles that changed on the portal since the last run. |
| `auth` | Manage Zoomin portal (and SharePoint) authentication. |
| `catalog` | Rebuild / inspect the local `docs/catalog.yaml` product catalog. |
| `wiki` | Generate a deterministic, cross-linked wiki from `raw_docs/`. |
| `index` | Generate the catalog taxonomy index (category → product → bundle). |
| `sharepoint` | Upload the extracted corpus to SharePoint. |
| `skill` | Maintain the `actimize-docenter` skill file. |

## MCP server

Two servers ship in this bucket.

| Server | Tool | Purpose |
|--------|------|---------|
| `docenter-mcp` (HTTP) | `search_docs`, `list_docs`, `find_bundles`, `get_catalog`, `get_page`, `get_toc` | Live, version-precise portal search + page fetch, with citation URLs. |
| `actimize-docs-mcp` (stdio) | `search_actimize_docs` | Offline BM25 search over the extracted `raw_docs/` corpus. |

Full contract: [`docenter_mcp/TOOLS.md`](docenter_mcp/TOOLS.md).

**How to run.** stdio: `actimize-docs-mcp`. HTTP: `python -m uvicorn docenter_mcp.server:app --port 8765`
(endpoint `/mcp`, health `/healthz`).

```jsonc
// VS Code — .vscode/mcp.json  ("servers": { … })
{ "actimize-docs": { "type": "stdio", "command": "actimize-docs-mcp" },
  "DOCenter": { "type": "http", "url": "http://localhost:8765/mcp" } }

// Claude Code — .mcp.json  ("mcpServers": { … })
{ "actimize-docs": { "type": "stdio", "command": "actimize-docs-mcp" },
  "DOCenter": { "type": "http", "url": "http://localhost:8765/mcp" } }
```

## Skill

[`skills/actimize-docenter/SKILL.md`](../../skills/actimize-docenter/SKILL.md) drives the
`docenter` CLI for product-documentation Q&A (features, config, integrations, release notes).
Teammates install it with `uv tool install "git+ssh://git@github.com/vinayguda/actwise.git"`.
An agent should trigger it whenever the user asks "does Actimize support X?", "how do I
configure Y in Z?", or wants release notes / a doc bundle.

## Configuration

Config search order: `$ACTWISE_CONFIG_DIR` → cwd → `~/.actwise` → dev repo root.

| File / env var | Purpose | Location |
|----------------|---------|----------|
| `.env` (`DOCENTER_PORTAL_URL`, `DOCENTER_API_URL`, `DOCENTER_EMAIL`, `DOCENTER_PASSWORD`) | Portal endpoints + creds for HTTP re-login | repo root (see `.env.example`) |
| `browser-profile/session-cookies.json` | Zoomin `_SESSION` cookie | repo root (gitignored) |
| `docs/catalog.yaml` + `raw_docs/index/` | Product catalog + local search index | repo |
| `DOCENTER_PROXY_API_KEY`, `DOCENTER_MCP_HOST/PORT`, `DOCENTER_MCP_MAX_RESULTS` | `docenter-mcp` server knobs | env |

## Auth

Portal access uses a Zoomin `_SESSION` cookie in `browser-profile/session-cookies.json`,
minted by `docenter auth login` (browser SSO; ~monthly MFA re-login) or `docenter auth login
--http` (password accounts, browser-free). `docenter-mcp` auto self-heals a 403 by re-logging
in with `DOCENTER_EMAIL`/`DOCENTER_PASSWORD` from `.env`. SharePoint uploads need a separate
`docenter auth sharepoint login`. **Never commit** `.env` or `browser-profile/`; rotate the
portal password in Zoomin and refresh the cookie.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Access denied (403)` | Run `docenter auth login` (or `--http`) to refresh the cookie. |
| `docenter: command not found` | `uv tool install "git+ssh://git@github.com/vinayguda/actwise.git"` (or `uvx --from … docenter`). |
| `No such option: --version` on `search` | The search flag is `--doc-version`, not `--version`. |
| No results | Online `search` auto-retries the spelling suggestion; broaden or drop rare/abbreviated tokens. |
| `docenter-mcp` returns `unauthorized` (401) | `DOCENTER_PROXY_API_KEY` is set — send the `X-API-Key` header. |
| `--local` search empty | Corpus not downloaded — run `docenter download`/`sync` for the product first. |

## Design docs & further reading

- [docenter MCP README](docenter_mcp/README.md) · [TOOLS.md](docenter_mcp/TOOLS.md)
- [copilot_proxy README](copilot_proxy/README.md) (Copilot Studio grounding, Option D)
- [`../../docs/components/docenter/`](../../docs/components/docenter/) — CLI design, portal analysis, corpus storage decision, MCP search/scaling/auth notes
- [`../../docs/runbooks/2026-07-11-docenter-mcp-aws-deployment-runbook.md`](../../docs/runbooks/2026-07-11-docenter-mcp-aws-deployment-runbook.md)
