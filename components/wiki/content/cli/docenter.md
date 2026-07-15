# `docenter`

> Browse, search, download, and sync the NICE Actimize documentation portal from the
> command line.

## Goal

Make the official NICE Actimize docs (`docs.niceactimize.com`, a Zoomin portal)
**scriptable**: find the right page fast, pull whole bundles to Markdown or PDF for
offline/grounding use, and keep a local corpus in sync — all with **your own** portal
session and **citations** back to the source.

## How it fits

`docenter` is the CLI core of the [docenter bucket](../buckets/docenter.md). The same
logic is exposed as two MCP servers — [`docenter-mcp`](../mcp/docenter-mcp.md) (HTTP)
and [`actimize-docs-mcp`](../mcp/actimize-docs-mcp.md) (stdio, local corpus search) —
and driven by an AI agent through the [actimize-docenter](../skills/actimize-docenter.md)
skill. It's what grounds the [ActWise Docs](../agents/docs.md) Copilot Studio agent.

## Install / enable

Installed with the `actwise` distribution ([Install](../install.md)). First-run
setup for the docs portal:

```powershell
docenter auth login      # browser SSO; cookie saved locally
docenter auth status
```

The product catalog is fetched on first use to `~/.docenter/catalog.yaml` — **no NICE
data is bundled**.

## Command reference

| Command | Description |
| --- | --- |
| `list-categories` | List all product categories from the local catalog, with product/bundle counts. |
| `list-products` | List all products from the local catalog, grouped by category. |
| `list-docs` | List doc bundles for a product, grouped by version and doc type. |
| `download` | Download doc bundles as Markdown or PDF. |
| `sync` | Re-extract only the bundles that changed on the portal since the last sync. |
| `search` | Search the docs — the live portal by default, or the local corpus with `--local`. |
| `auth` | Manage authentication with the Zoomin doc portal. |
| `sharepoint` | Upload documents to SharePoint. |
| `catalog` | Manage the local `docs/catalog.yaml` product catalog. |
| `skill` | Maintain the `actimize-docenter` AI skill file. |
| `wiki` | Generate a deterministic, cross-linked documentation wiki from `raw_docs/`. |
| `index` | Generate the catalog taxonomy index (category → product → bundle). |

Run `docenter <command> --help` for the flags of any command.

## Walkthrough

```powershell
# 1. Search the live portal (returns titles + source URLs)
docenter search "blotter configuration" --product actone

# 2. Pull a whole bundle to Markdown for offline grounding
docenter download actone --format md --version 10.2 --bundle "Actimize_ActOne_10.2_Installation_Guide"

# 3. Search your local corpus offline
docenter search "SAML authentication" --local
```

## Under the hood

- Talks to the portal's **Zoomin REST API** using the cookie saved by `auth login`.
- `download` converts `topic_html` to Markdown and writes versioned files under
  `raw_docs/actone/v{version}/{bundle}/…`, preserving YAML front matter (`version`,
  `guide_type`, `page_title`, `source_url`) that the local search MCP depends on.
- `wiki` renders that corpus into a deterministic cross-linked site (this is the
  repo-root `wiki/` of **product** docs — distinct from this ActWise wiki).

## See also

- Bucket: [docenter](../buckets/docenter.md)
- MCP: [docenter-mcp](../mcp/docenter-mcp.md) · [actimize-docs-mcp](../mcp/actimize-docs-mcp.md)
- Skill: [actimize-docenter](../skills/actimize-docenter.md)
- Agent: [ActWise Docs](../agents/docs.md)
