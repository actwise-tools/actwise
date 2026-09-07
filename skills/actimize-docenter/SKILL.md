---
name: actimize-docenter
description: Search, explore, download, and sync NICE Actimize product documentation via the docenter CLI. Use when the user asks about Actimize product features, configuration, integrations, release notes, or installation guides.
---

# Actimize DOCenter Skill

This skill helps you find and retrieve official NICE Actimize product documentation using the `docenter` CLI, which queries the live Actimize documentation portal (docs.niceactimize.com).

## When to use

Activate this skill when the user:
- Asks about configuration, installation, or features of any NICE Actimize product (ActOne, SAM, CDD, IFM, X-Sight, DataIQ, etc.)
- Wants to know what integrations or third-party services a product supports
- Asks about release notes, new features, or version differences
- Asks "does Actimize support X?" or "how do I configure Y in Z?"
- Wants to download or browse official Actimize documentation bundles

## Available CLI Commands

```
# Authentication
docenter auth login | status | logout          # Zoomin doc-portal SSO
docenter auth sharepoint login                  # SharePoint (for uploads)

# Live portal (needs Zoomin auth)
docenter search "<query>" [--max N] [--page N] [--json]
#   Online filters (hybrid): --product/--doc-version narrow server-side via the
#   portal's facet labelkeys; --guide post-filters on the bundle name.
docenter search "<query>" [--product KEY] [--doc-version V] [--guide TYPE] [--json]
docenter list-products [--category ID] [--json]
docenter list-categories [--json]
docenter list-docs <product-key> [--version V] [--type "Release Notes"] [--pages] [--no-discover] [--json]
docenter download <product-key> --format md|pdf [--version V] [--bundle NAME] [--dry-run]

# Keep the local corpus fresh (re-extract only what changed on the portal)
# Uses Updated-on timestamps + page-count guard to skip republish-only bumps
docenter sync [--product KEY | --category ID] [--bundle NAME] [--version V]
              [--since DATE | --since-last] [--format md|pdf]
              [--force] [--include-new] [--no-refresh] [--dry-run] [--json]

# Offline / generated knowledge (no auth needed, BM25-ranked, cached index)
# First search builds an index (~45s), subsequent searches load from cache (~2s)
docenter search "<query>" --local [--product KEY] [--doc-version V] [--guide TYPE] [--json]
docenter wiki build [--product KEY] [--json]   # navigable, citation-backed wiki under wiki/
docenter catalog refresh | status              # rebuild / inspect docs/catalog.yaml

# Publish the corpus to SharePoint (needs SharePoint auth)
docenter sharepoint upload <product-key> [--format md|pdf] [--version V] [--dest PATH] [--dry-run]
```

Add `--json` to `search`, `list-products`, `list-categories`, `list-docs`, `sync`, and
`wiki build` for machine-readable output instead of a Rich table.

## Choosing online vs. local

Both `search` (live portal) and `search --local` (offline BM25 index) answer the same kinds of
questions. Pick based on the need:

- **Online (default)** — latest content, full breadth (all configured products, even ones not
  downloaded), and **downloadable artifacts** (JSON schemas, sample files, PDFs). Needs Zoomin
  auth and network. Best for "what's new", broad discovery, or fetching a specific asset.
- **Local (`--local`)** — offline, deterministic, no auth, fast on a warm index. Recall is
  **limited to what's been downloaded** into `raw_docs/`, so run `docenter download`/`sync`
  first if a product is missing. Best for repeatable retrieval over a known corpus.
- **Deep "how does X work" questions** — search **online to locate the right bundle**, then read
  the **full page content** (local Markdown if downloaded, or `download` it) rather than relying
  on snippets alone.

## Installation & Invocation

This skill drives the `docenter` CLI. Run commands as `docenter <command>` when the
command is on `PATH`. If it is **not** installed, the most reliable way to run it on any
machine — **without worrying about the user's Python version** — is via [uv](https://docs.astral.sh/uv/),
which provisions its own Python and an isolated environment. This repo is currently
**private**, so use an authenticated git source (SSH key, or `gh auth setup-git` for HTTPS):

```bash
# One-time persistent install (puts `docenter` on PATH, uv-managed Python) — SSH:
uv tool install "git+ssh://git@github.com/vinayguda/actwise.git"

# — or — run ad-hoc with no install at all:
uvx --from "git+ssh://git@github.com/vinayguda/actwise.git" docenter <command> [args]

# HTTPS alternative (after `gh auth login` / `gh auth setup-git`):
uv tool install "git+https://github.com/vinayguda/actwise.git"
```

The product catalog is bundled in this (internal) package, so `search --local`, `list-*`, and
`catalog status` work offline immediately. (The future public package ships no catalog and
fetches it once on first use — see the repo's distribution plan.) Only `auth login` and PDF
export need a browser (run `playwright install chromium` once for those).

**Invocation rule for this skill:** prefer `docenter <command>`. If that fails with a
"command not found" error, fall back to
`uvx --from "git+ssh://git@github.com/vinayguda/actwise.git" docenter <command>`.

## Instructions

### 1. Check authentication first

Before any search or download, verify the session is valid:

```
docenter auth status
```

If the output says "expired" or "not authenticated", tell the user to run `docenter auth login` and complete the browser SSO flow before continuing. Do not proceed with searches until auth is confirmed.

### 2. Search the portal

For any question about Actimize products, start with a targeted search:

```
docenter search "<concise query>" --max 10
```

**Search query tips:**
- Use product-specific terms (e.g., "ActOne Policy Manager DART configuration")
- For integrations: include the third-party name (e.g., "LexisNexis Bridger Insight XG")
- For release notes: include version (e.g., "IFM 11.2 release notes")
- Avoid filler words — the portal uses keyword matching
- **One concept per query.** Local search is ranked-OR (matches any term, ranked by relevance),
  so don't stuff a redundant abbreviation next to its expansion — prefer "Generic Batch
  Interface" over "Generic Batch Interface GBI", which dilutes the ranking.
- **If results are thin, drop the rarest/abbreviated token and retry** (search "GBI" *or*
  "Generic Batch Interface", not both). Online responses also carry a `did_you_mean` suggestion —
  use it to reformulate.
- **Filter, don't lengthen.** Narrow scope with `--product`/`--doc-version`/`--guide` instead of
  padding the query with product/version words. Note the flag is `--doc-version` (not `--version`).

### 3. Interpret results

The search returns:
- **Title** — page title from the documentation (occasionally the *guide* title — check the
  URL/short description to tell similar hits apart)
- **Bundle / Product** — the documentation bundle (correlates to product + guide type)
- **Snippet** — relevant excerpt from the page
- **References** — direct URLs to docs.niceactimize.com

With `--json`, each result also carries `short_desc` (the page's short description — often
high-signal, e.g. a build number) and `updated` (the page's last-updated date) for recency
judgments.

Always cite the reference URLs in your answer so the user can navigate to the full documentation.

**Downloadable artifacts.** When a result URL ends in `.json`, `.xlsx`, `.xsd`, `.pdf`, or
`.zip`, it is a downloadable asset (schema, sample input file, interface map, guide PDF) — not an
HTML page. Surface these to the user explicitly; they are often the most useful result (e.g. a
JSON schema or sample file to share with a client).

### 4. Explore products and bundles

If the search doesn't yield enough detail, list available documentation bundles:

```
docenter list-categories            # product categories with product/bundle counts
docenter list-products              # all configured products and their keys
docenter list-products --category aml
docenter list-docs <key>            # all bundles for a product (e.g. actone, ifm, sam)
docenter list-docs actone --version 10.1 --type "Release Notes"
```

`list-docs` queries the Zoomin API live to discover **every** bundle (including Product Info,
Patch Release Notes, and Release Notifications). Add `--no-discover` for a fast config-only
list, or `--pages` to fetch the live page count per bundle. Use bundle names to narrow
follow-up searches or downloads.

### 5. Download documentation locally

To get full offline content for a product (optionally narrowed by version/bundle):

```
docenter download actone --format md --version 10.1 --dry-run   # preview only
docenter download actone --format md --version 10.1             # write Markdown to raw_docs/
docenter download actone --format pdf --bundle "Implementer"    # PDF export (needs Playwright)
```

`download` takes a **product key** (not a bundle name) and requires `--format md|pdf`.
Markdown lands under `raw_docs/` and is searchable offline via `docenter search --local` or the
MCP server (`search_actimize_docs`).

### 6. Keep the local corpus fresh

`sync` re-extracts only the bundles that changed on the portal since the last run. It compares
each bundle's portal "Updated on" timestamp against `docs/sync-state.json`, and for MD bundles
applies a **page-count guard** — if the timestamp advanced but the TOC page count is unchanged,
the bundle is treated as a republish and skipped. Use `--force` to bypass the guard.

**Catalog-first mode:** broad syncs (no `--product` flag) automatically refresh `catalog.yaml`
once upfront and then diff timestamps locally, instead of making per-product `/bundlelist` API
calls. This reduces a full 63-product sync from ~15 minutes of API calls to a single catalog
refresh (~2 min) plus fast local comparison. Single-product syncs (`--product X`) still hit the
live API for that one product. Use `--no-refresh` to skip the catalog refresh entirely and diff
against the committed `catalog.yaml`.

```
docenter sync --dry-run                       # show the change set, download nothing
docenter sync --product actone                # refresh one product's existing bundles (live API)
docenter sync --category aml --since-last      # only what changed since the last sync
docenter sync --product actone --include-new   # also backfill in-scope bundles not yet local
docenter sync --bundle "Release Notes" --force # re-extract matching bundles regardless of date
docenter sync --format pdf                     # sync PDFs instead of MD (writes to raw_docs_pdf/)
docenter sync --no-refresh --dry-run           # offline diff against committed catalog.yaml
```

The first run on an existing corpus adopts local bundles as baselines (records timestamps and
page counts in `docs/sync-state.json`) without re-downloading. By default `sync` only refreshes
bundles already present locally; add `--include-new` to backfill. Use `--since DATE` for an
explicit cutoff. A human-readable change feed is appended to `docs/sync-log.md` after each
real download.

### 7. Build derived knowledge and publish

```
docenter wiki build                 # regenerate the cross-linked wiki/ from raw_docs/ (no LLM, no network)
docenter wiki build --product actone
docenter catalog refresh            # rebuild docs/catalog.yaml from the live API
docenter catalog status             # when the catalog was last refreshed + totals
docenter auth sharepoint login      # then:
docenter sharepoint upload actone --version 10.1 --dest "Shared Documents/ActWise"
```

`wiki build` is a pure function of the corpus — re-running produces identical, citation-backed
output. `sharepoint upload` pushes the extracted docs to SharePoint and needs a separate
SharePoint sign-in (`docenter auth sharepoint login`).

### 8. Format your answer

Structure your response as:
1. **Direct answer** — answer the user's question using information from the search results
2. **Supporting details** — key excerpts or context from the snippets
3. **References** — numbered list of documentation URLs from the References section

Example:

> LexisNexis Bridger Insight XG is supported in **DataIQ Clarity** as an On-Demand search data source for sanctions, PEP, and watchlist screening. It was first introduced in the 2022 May 20 GA release.
>
> **References:**
> 1. [2022.05.20 Release](https://docs.niceactimize.com/bundle/Actimize_X-Sight_DataIQ_Clarity_2022_Release_Notes/page/Content/DataIQ/DataIQ_Clarity/Clarity_RN/2022.05.20.htm)
> 2. [DataIQ Clarity - 2023 Sep 15 GA Release Notification](https://docs.niceactimize.com/bundle/DataIQ_Clarity_-_2023_Sep_15_GA_Release_Notification/resource/DataIQ_Clarity_-_2023_Sep_15_GA_Release_Notification.pdf)

## Product Keys Reference

<!-- BEGIN GENERATED: product-keys (run `docenter skill sync-reference` to refresh from catalog.yaml) -->
| Key       | Product                                                 | Versions                     |
|-----------|---------------------------------------------------------|------------------------------|
| actone    | ActOne                                                  | 10.0, 10.1, 10.2             |
| sam       | Suspicious Activity Monitoring (SAM)                    | 10.0, 10.1                   |
| cdd       | Customer Due Diligence (CDD)                            | 10.0, 10.1, 10.2, 10.3, 10.4 |
| ifm       | Integrated Fraud Management (IFM)                       | 11.0, 11.1, 11.2             |
| xse-sam   | X-Sight Enterprise Suspicious Activity Monitoring (SAM) | -                            |
| xse-cdd   | X-Sight Enterprise Customer Due Diligence (CDD)         | 10.3                         |
| xse-fraud | X-Sight Enterprise Fraud                                | -                            |
<!-- END GENERATED: product-keys -->

> This table lists the **most commonly used** keys and versions — a curated subset, not the
> source of truth. For the authoritative, current set run `docenter list-products` (every
> configured product key) and `docenter list-docs <key>` (every version/bundle for a product).

## Error Handling

| Error | Action |
|-------|--------|
| `Access denied (403). Run: docenter auth login` | Tell user to run `docenter auth login` |
| `Search request failed` | Check auth status, retry with simpler query |
| No results returned | Online `search` now **auto-retries** the portal's own spelling suggestion / synonyms once before reporting nothing (disable with `--no-retry`). If it still returns nothing, broaden the query: drop abbreviated/rarest tokens, or try alternate product terminology |
| `No such option: --version` on `search` | The search version flag is `--doc-version`, not `--version` |
| `docenter: command not found` | Install via uv (no Python setup needed). Private repo → use SSH: `uv tool install "git+ssh://git@github.com/vinayguda/actwise.git"`, or run ad-hoc with `uvx --from "git+ssh://git@github.com/vinayguda/actwise.git" docenter <command>`. (Developers with a checkout can instead `pip install -e .` in the repo root.) |
