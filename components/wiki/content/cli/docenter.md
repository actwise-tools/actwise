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

> For every argument and option of every sub-command, see the [full CLI reference](full-reference.md#docenter).

Several top-level commands are **groups** with their own sub-commands:

**`auth`** — Manage authentication with the Zoomin doc portal.

| Sub-command | Description |
| --- | --- |
| `auth login` | Login to the Zoomin doc portal via browser SSO (default). |
| `auth status` | Show current Zoomin authentication status and session expiry. |
| `auth logout` | Remove saved Zoomin session cookies. |
| `auth sharepoint login` | Open a browser for SharePoint SSO login and save session cookies. |
| `auth sharepoint status` | Show current SharePoint authentication status. |
| `auth sharepoint logout` | Remove saved SharePoint session cookies. |

**`sharepoint`** — Upload documents to SharePoint.

| Sub-command | Description |
| --- | --- |
| `sharepoint upload` | Upload extracted docs to SharePoint. |

**`catalog`** — Manage the local `docs/catalog.yaml` product catalog.

| Sub-command | Description |
| --- | --- |
| `catalog refresh` | Rebuild `docs/catalog.yaml` from the live Zoomin API. |
| `catalog status` | Show local catalog metadata: when it was last refreshed and totals. |

**`skill`** — Maintain the `actimize-docenter` AI skill file.

| Sub-command | Description |
| --- | --- |
| `skill sync-reference` | Regenerate the Product Keys Reference table in the skill from the live catalog. |

**`wiki`** — Generate a deterministic, cross-linked documentation wiki from `raw_docs/`.

| Sub-command | Description |
| --- | --- |
| `wiki build` | Generate a navigable, citation-backed wiki under `wiki/` — purely from `raw_docs/`. |

**`index`** — Generate the catalog taxonomy index (category → product → bundle).

| Sub-command | Description |
| --- | --- |
| `index build` | Emit `raw_docs/index/` from the catalog — the taxonomy as data, not folders. |
| `index status` | Show whether `raw_docs/index/` exists and summarize its contents. |

### Key options

The flags below are the most useful ones for the flagship commands (taken verbatim from `--help`).

**`search`** — [`docenter search`](full-reference.md#docenter-search)

| Option | Meaning |
| --- | --- |
| `--local` | Search the local extracted corpus (`raw_docs/`) instead of the live portal — no auth needed. |
| `--product` | Filter by product key/name, e.g. `actone`, `ifm`, `sam`. |
| `--doc-version` | Filter by doc version, e.g. `10.1`. |
| `--guide` | Filter by guide type, e.g. `implementer` (online: post-filtered on bundle name). |
| `--max`, `-n` | Max results to display (default 10). |
| `--json` | Output machine-readable JSON instead of a table. |

**`download`** — [`docenter download`](full-reference.md#docenter-download)

| Option | Meaning |
| --- | --- |
| `--format`, `-f` | Format: `md` or `pdf` (required). |
| `--version`, `-v` | Limit to a specific version, e.g. `10.1`. |
| `--bundle`, `-b` | Limit to a specific bundle name (partial match). |
| `--dry-run` | Show what would be downloaded without running. |

**`sync`** — [`docenter sync`](full-reference.md#docenter-sync)

| Option | Meaning |
| --- | --- |
| `--product`, `-p` | Sync one product (slug or alias). |
| `--category`, `-c` | Sync all products in a category (e.g. `aml`, `plt`, `ifm`). |
| `--since-last` | Only bundles updated since the last sync (`state.last_sync`). |
| `--dry-run` | Show the change set without downloading. |
| `--force` | Re-extract in-scope bundles regardless of timestamp. |
| `--include-new` | Also download in-scope bundles not present locally (backfill). |

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
