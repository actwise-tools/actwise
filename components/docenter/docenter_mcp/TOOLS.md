# ActWise DOCenter MCP — Tool Reference

Tool-level API contract for the `actwise-docenter-live` MCP server
(`docenter_mcp/server.py`). For install / run / deploy, see [README.md](./README.md).

- **Transport:** Streamable HTTP, `stateless_http=True`
- **MCP endpoint:** `POST /mcp`  ·  **Health:** `GET /healthz`
- **Protocol:** MCP `2025-06-18`  ·  **Server name:** `actwise-docenter-live`
- **Data source:** the **live** NICE Actimize portal (Zoomin), via the proven
  `docenter` CLI code path — always fresh, never a stale local index.
- **All tools are read-only.**

| Tool | One-liner |
|------|-----------|
| [`search_docs`](#1-search_docs) | Faceted live search → ranked pages with citation URLs. |
| [`list_docs`](#2-list_docs) | List a product's doc bundles (live discovery), filterable. |
| [`find_bundles`](#3-find_bundles) | Discover which bundles answer a query (to narrow a follow-up search). |
| [`get_catalog`](#4-get_catalog) | Authoritative product↔slug↔version map (disambiguate / pick a `product`). |
| [`get_page`](#5-get_page) | Fetch a result's **full page text** as Markdown (read beyond the snippet). |
| [`get_toc`](#6-get_toc) | A bundle's **table of contents** — every page title + URL (browse a guide without searching). |

---

## 1. `search_docs`

Search the live portal and return ranked pages with citation URLs. Use this to
answer product questions with links back to `docs.niceactimize.com`.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `query` | string | **required** | **Keyword** query, one concept, e.g. `"conditional step change plugin"` — the portal ranks by keyword match, not semantics. Drop filler words; narrow with filters instead of lengthening the query. |
| `product` | string \| null | `null` | Product slug/alias to narrow (`actone`, `ifm`, `sam`, …). Resolve names via [`get_catalog`](#4-get_catalog). See [facet notes](#facet-behavior-read-this). |
| `doc_version` | string \| null | `null` | Doc version, e.g. `"10.1"`, `"11.2"`. **Omit to auto-default to the product's newest version** — see [facet notes](#facet-behavior-read-this). |
| `guide` | string \| null | `null` | Guide type, e.g. `"implementer"`, `"reference"`. Substring post-filter on the bundle name — a non-matching value silently empties the results. |
| `bundle` | string \| null | `null` | Bundle id to search **within one guide** (take it from [`find_bundles`](#3-find_bundles)). Substring post-filter on the bundle name; when set, product/version defaulting is skipped. |
| `max_results` | integer | `10` | Results to return (clamped to **1–50** by default; env `DOCENTER_MCP_MAX_RESULTS` overrides the cap). |
| `page` | integer | `1` | Result page (1-based). |
| `retry` | boolean | `true` | Auto-adopt the portal's spelling/synonym suggestion when the first pass is empty. |

### Returns

```jsonc
{
  "results": [
    {
      "title":      "Policy Manager",  // sometimes the *guide* title — check shortDesc/updated/portal_url to tell similar hits apart
      "bundle":     "Actimize_ActOne_6.0.1_Advanced_Work_Allocation_Getting_Started_Guide",
      "version":    "6.0.1",      // per-result doc version (parsed from the bundle name)
      "snippet":    "The Policy Manager tab enables you to define business rules…",
      "shortDesc":  "Build No: 10.2.0.23",  // the page's short description (often high-signal; may be empty)
      "updated":    "2026-07-02", // the page's last-updated date (may be empty)
      "portal_url": "https://docs.niceactimize.com/bundle/…/Policy_Manager.htm"
    }
  ],
  "count":          1,
  "totalMatches":   38,          // portal's PRE-FILTER match total — more docs exist when > count
  "originalQuery":  "policy manager",
  "correctedQuery": null,        // set to the adopted spelling when a correction fired
  "suggestions":    [],          // portal "did you mean / related" terms — try one when results look off-target
  "filtersActive":  false,       // true when any product/version/guide/bundle filter applied
  "facetFallback":  false,       // true when a faceted search returned 0 and was auto-retried broad
  "broadened":      false,       // true when weak defaulted-version results were topped up from other versions
  "versionUsed":    "10.2",      // the doc version actually searched (null when broad/unscoped)
  "versionDefaulted": true,      // true when the newest version was auto-applied (no doc_version given)
  "availableVersions": ["10.2","10.1","10.0"]  // other versions the caller can offer the user
}
```

Cite `portal_url` in answers. `correctedQuery`/`suggestions` let a client tell the
user the query was adjusted or offer refinements. When `totalMatches` exceeds
`count`, raise `max_results` or narrow with filters rather than assuming the
returned page is everything.

### Example (MCP JSON-RPC over `POST /mcp`)

```jsonc
{ "jsonrpc": "2.0", "id": 3, "method": "tools/call",
  "params": { "name": "search_docs",
    "arguments": { "query": "policy manager", "max_results": 3 } } }
```

### Facet behavior — read this

ActOne (and other "platform" products) have **version-segmented** facets in the
portal taxonomy. A **product filter *without* a version** can resolve to a
version-bound facet key and return **0 results** upstream.

Observed against the live portal (raw facet behavior):

| Filters | Raw results |
|---------|--------:|
| _(none)_ | 3 |
| `product="actone"` | **0** |
| `product="actone", doc_version="10.1"` | 3 |
| `product="actone", doc_version="10.1", guide="implementer"` | 3 |

**Version defaulting (since 2026-07-01):** when a caller passes a `product` but
**no `doc_version`**, `search_docs` resolves the product's **newest** version (from
the live bundle list) and scopes the search to it, returning `versionUsed`,
`versionDefaulted: true`, and `availableVersions`. This is the primary fix for the
version-segmented facet problem below: a product-only call now returns coherent,
current results instead of 0 (or a scattered broad fallback). Clients should surface
`versionUsed` to the user and offer `availableVersions` if they need a different one.

**Auto-fallback (since 2026-07-01):** as a last resort, if a faceted search still
returns **0 results** (e.g. the topic exists only in an older version), it retries as
a **broad, unfaceted** search (the query text still drives relevance) and sets
**`facetFallback: true`** (with `versionUsed: null`). So callers get useful results
even when the version scope has no match. An explicit `bundle` scope is kept
through the fallback.

**Weak-result broadening (since 2026-07-06):** when the version was *defaulted*
(not explicitly requested) and the scoped search finds only 1–2 hits, the server
**tops up** (never replaces) the result list with broad-search hits from other
versions and sets **`broadened: true`** — the per-result `version` field shows the
mix. This prevents a single tangential latest-version hit from hiding the docs
that actually answer the query in an older version.

**Guidance for clients:** just pass `product` and let the server pick the latest
version. Pass an explicit `doc_version` only when the user asks for a specific one;
to enumerate versions, read `availableVersions` or call
[`find_bundles`](#3-find_bundles).

---

## 2. `list_docs`

List the documentation bundles for a product via **live discovery** (Product Info,
Release Notes, Patch Notes, …), filterable by version / doc type. Returned
newest-first.

> This tool **works**, unlike NICE's upstream `docenter-mcp-server` `list_docs`,
> which currently times out (~30 s) server-side.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `product` | string | **required** | Product slug or alias (`actone`, `sam`, `ifm`, …). |
| `version` | string \| null | `null` | Version filter, e.g. `"10.1"`. Version-agnostic bundles are always kept. |
| `doc_type` | string \| null | `null` | Doc-type substring, e.g. `"Release Notes"`, `"Product Documentation"`. |

### Returns

```jsonc
{
  "product": "actone",
  "name":    "ActOne",
  "count":   66,
  "bundles": [
    {
      "name":     "Actimize_ActOne_10.1_Release_Notes",
      "doc_type": "Release Notes",
      "updated":  "2026-06-18",
      "version":  "10.1"
    }
    // … newest-first
  ]
}
```

### Error shapes

| `error` | When | `message` |
|---------|------|-----------|
| `no_catalog` | Product catalog not loaded | "Run: docenter catalog refresh" |
| `unknown_product` | `product` not recognized | "Unknown product: '…'" |
| `no_label_keys` | Product has no discovery facets configured | "No discovery label keys configured…" |

### Example

```jsonc
{ "jsonrpc": "2.0", "id": 8, "method": "tools/call",
  "params": { "name": "list_docs",
    "arguments": { "product": "actone", "doc_type": "Release Notes" } } }
```

---

## 3. `find_bundles`

Run a live search and aggregate the **distinct bundles** among the hits, ranked by
hit count. Use it to discover the right `product` / `doc_version` (or a specific
bundle) before a precise `search_docs` call — it answers "*where does this live?*".

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `query` | string | **required** | Topic to locate, e.g. `"DART drill down query"`. |
| `product` | string \| null | `null` | Optional product slug/alias to narrow. |
| `doc_version` | string \| null | `null` | Optional doc version to narrow. |
| `max_results` | integer | `20` | Underlying hits to aggregate over (clamped to **1–50** by default; env `DOCENTER_MCP_MAX_RESULTS` overrides the cap). |

### Returns

```jsonc
{
  "query":   "conditional step change plugin",
  "count":   4,
  "bundles": [
    { "bundle": "Actimize_ActOne_10.1_Extend_Implementer_Guide", "hits": 7, "version": "10.1" },
    { "bundle": "Actimize_ActOne_6.6.0_Extend_Implementer_Guide", "hits": 1, "version": "6.6" }
    // … most relevant first
  ]
}
```

### Typical two-step flow

1. `find_bundles("conditional step change plugin")`
   → top bundle is `Actimize_ActOne_10.1_Extend_Implementer_Guide` (version `10.1`).
2. `search_docs("conditional step change plugin", bundle="Actimize_ActOne_10.1_Extend_Implementer_Guide")`
   → pages from that exact guide, with citation URLs.
   (Or narrow by facet instead: `product="actone", doc_version="10.1"`.)

---

## 4. `get_catalog`

The authoritative **product↔slug↔version** map, served from the committed catalog
(no portal round-trip). Use it to **disambiguate a product** or **pick the right
`product` slug** for `search_docs` instead of guessing.

### Parameters

| Name | Type | Default | Notes |
|------|------|---------|-------|
| `product` | string \| null | `null` | Product name, alias, or slug (`"ActOne"`, `"pltact"`, `"actone"`). Omit for the full roster. |

### Returns

- **With `product`** — resolves the name/alias/slug and returns product detail:

```jsonc
{
  "resolved": true,
  "product": {
    "slug":          "actone",
    "name":          "ActOne",
    "aliases":       ["pltact"],
    "category":      "Platform",
    "description":   "A one-for-all intelligent investigation platform.",
    "latestVersion": "10.2",
    "versions":      ["10.2", "10.1", "10.0", "6.6", "…"]   // newest first
  }
}
```

  When the name can't be matched: `{ "resolved": false, "query": "...", "suggestions": [ …slugs ] }`.

- **Without `product`** — the roster grouped by category:

```jsonc
{
  "categories": [
    { "id": "plt", "name": "Platform",
      "products": [ { "slug": "actone", "name": "ActOne", "latestVersion": "10.2", "versionCount": 10 } ] }
  ],
  "productCount": 91
}
```

**Versions note.** `versions` come from the *cached* catalog bundle list (offline,
fast) and may lag the live portal by a sync cycle. For the exact newest version a
search will actually use, rely on `search_docs`'s `versionUsed` / `availableVersions`
(resolved live). `get_catalog` is for disambiguation and slug/version discovery, not
grounding — it never returns page content or citations.

---

## 5. `get_page`

Fetch the **full text** of a documentation page as Markdown — use it after
`search_docs` to read a result in full (the snippet is only a teaser), so answers
can quote the source accurately. Pass the result's `portal_url`.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `url` | string | **required** | A page citation URL (the `portal_url` from `search_docs`), e.g. `https://docs.niceactimize.com/bundle/<bundle>/page/Content/.../<Page>.htm`. |
| `max_chars` | integer | `12000` | Truncate the returned Markdown (clamped **500–50000**). `truncated` flags when content was cut. |

### Returns

```jsonc
{
  "title":     "Post-Step Change Plugin Extension Point",
  "bundle":    "Actimize_ActOne_10.1_Extend_Implementer_Guide",
  "version":   "10.1",
  "updated":   "2026-06-10",
  "url":       "https://docs.niceactimize.com/bundle/…/Post-Step_Change_Plugin_Extension_Point.htm",
  "markdown":  "# Post-Step Change Plugin Extension Point\n\nAn ActOne plugin can declare…",
  "truncated": false
}
```

### Error shapes

| `error` | When |
|---------|------|
| `bad_url` | The URL isn't a recognizable `.../bundle/<bundle>/page/<nav_path>` page link. |
| `not_found` | The page resolved but returned no content (`topic_html` empty). |

### Typical chain

```
search_docs("conditional step change plugin", product="actone", doc_version="10.1")
  → pick a result, take its portal_url
get_page(<portal_url>)
  → full page Markdown to quote / reason over
```

### Example

```jsonc
{ "jsonrpc": "2.0", "id": 4, "method": "tools/call",
  "params": { "name": "get_page",
    "arguments": { "url": "https://docs.niceactimize.com/bundle/Actimize_ActOne_10.1_Extend_Implementer_Guide/page/Content/Platform/ActOne/ActOne_Plugin_Guide/Post-Step_Change_Plugin_Extension_Point.htm" } } }
```

---

## 6. `get_toc`

List a bundle's **table of contents** — every page title + portal URL. Use it
after `list_docs` / `find_bundles` to see what a guide actually contains: find
every release page in a Release Notes bundle (base release, **SP1**, patches)
and pick the newest, or locate the exact page for `get_page` without another
search. TOC titles are the **real page titles** (search results sometimes show
the guide title instead).

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `bundle` | string | **required** | Exact bundle id (from `list_docs` / `find_bundles` / a search result's `bundle`). |
| `title_filter` | string \| null | `null` | Case-insensitive substring filter on page titles (e.g. `"release"`). |
| `max_pages` | integer | `200` | Max pages to return (clamped **1–500**); `truncated` flags a cut. |

### Returns

```jsonc
{
  "bundle":    "Actimize_ActOne_10.2_Release_Notes",
  "version":   "10.2",
  "count":     3,                 // total pages after filtering
  "pages": [
    { "title": "ActOne 10.2 Release",     "portal_url": "https://docs.niceactimize.com/bundle/…/ActOne_10.2_Release.htm" },
    { "title": "ActOne 10.2 SP1 Release", "portal_url": "https://docs.niceactimize.com/bundle/…/ActOne_10.2_SP1_Release.htm" }
  ],
  "truncated": false
}
```

Error shape: `{ "error": "unknown_bundle", "message": "…" }` when the bundle id
can't be resolved.

### Typical "what's the latest release?" chain

```
list_docs("actone", doc_type="Release Notes")   → newest bundle: Actimize_ActOne_10.2_Release_Notes
get_toc("Actimize_ActOne_10.2_Release_Notes", title_filter="release")
  → pages: 10.2 Release, 10.2 SP1 Release  ← the newest is visible immediately
get_page(<SP1 portal_url>)                      → build number, date, highlights
```

---

## Health & server errors

- **`GET /healthz`** → `200 {"status":"ok","server":"actwise-docenter-live"}` (no auth).
- **`401 {"error":"unauthorized"}`** — `DOCENTER_PROXY_API_KEY` is set and the
  request is missing/mismatched on the `X-API-Key` header.
- **Portal session errors** surface as a tool error with a `PortalUnavailable`
  message:
  - cookie missing → *"run `docenter auth login` …"*
  - cookie expired (HTTP 403) → *"Portal session expired (403). Refresh the cookie…"*
    (the server drops its cached session so the next call rebuilds it).

---

## Calling from MCP clients

`tools/call` results return MCP `content` with a single `text` item whose value is
the **JSON-encoded** tool result (parse the string to get the objects above).

### GitHub Copilot CLI / VS Code

Register the server, then call tools naturally; they appear namespaced
(e.g. `DOCenterLive-search_docs`):

```jsonc
// GitHub Copilot CLI — ~/.copilot/mcp-config.json
{ "mcpServers": { "DOCenterLive": { "type": "http", "url": "http://localhost:8765/mcp" } } }

// VS Code — .vscode/mcp.json  ("servers": { … })
{ "DOCenterLive": { "type": "http", "url": "http://localhost:8765/mcp" } }
```

If a key is set, add the header: `"headers": { "X-API-Key": "<your-api-key>" }`.

### Raw HTTP (PowerShell smoke test)

```powershell
$h = @{ "Accept" = "application/json, text/event-stream"; "Content-Type" = "application/json" }
$body = @{ jsonrpc = "2.0"; id = 1; method = "tools/call"
          params = @{ name = "search_docs"; arguments = @{ query = "policy manager"; max_results = 3 } } } |
        ConvertTo-Json -Depth 10
Invoke-WebRequest -Uri "http://localhost:8765/mcp" -Method POST -Headers $h -Body $body -UseBasicParsing
```

> The `Accept` header **must** include both `application/json` and
> `text/event-stream` — Streamable HTTP replies as an SSE `event: message` frame.
