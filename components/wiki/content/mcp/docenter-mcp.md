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

## Request flow — tool call to DOCenter API

Every tool call travels the **same lifecycle**: an MCP client `POST`s JSON-RPC to
`/mcp`, the `_AuthGate` ASGI middleware authenticates it, FastMCP dispatches the
`@mcp.tool` handler, and the handler runs a portal call through `_run_portal`
against the **Zoomin backend** `https://docs-be.niceactimize.com/api` (`BASE_API`).
Result URLs are rewritten from the backend host `docs-be.niceactimize.com` to the
user-facing `docs.niceactimize.com` for citations. Only `get_catalog` never hits
the portal — it answers from the committed product catalog.

### Backend endpoints

Base URL `https://docs-be.niceactimize.com/api` (override via `DOCENTER_API_URL`).

| Backend call | Purpose | Used by |
|--------------|---------|---------|
| `GET /search?q=&rpp=&page=` | Broad keyword search | `search_docs`, `find_bundles` |
| `POST /search` (+ `labelkeys` body) | Server-side facet narrowing (product/version) | `search_docs`, `find_bundles` |
| `GET /bundlelist?labelkey=&per_page=50&page=` | Bundle discovery by label key | `list_docs`, `search_docs` (version default) |
| `GET /bundle/{name}` | A bundle's doc-type labels | `list_docs` (config bundles) |
| `GET /bundle/{bundle}/page/{nav_path}` | Full page (`topic_html`) | `get_page` (HTML) |
| `GET /bundle/{bundle}/resource/{file}` | Resource descriptor → `topic_url` (archived/PDF bundles) | `get_page` (PDF) |
| `GET /bundle/{bundle}/raw/resource/enus/{file}` | Raw PDF bytes (from `topic_url`) → pypdf text | `get_page` (PDF) |
| `GET /bundle/{bundle}/toc?language=enus` | Table of contents tree | `get_toc` |
| `GET /auth/login` → `POST /auth/page/localStorage/api/login` | Browser-free login (cold-start bootstrap + 403 self-heal) | `_run_portal` |
| *(none — committed `PRODUCTS` catalog)* | Product↔slug↔version map | `get_catalog` |

Code path: `docenter_mcp/server.py` (tools + transport) → `docenter.cli`
(`portal_search_core`, `discover_bundles`, `load_session`, `http_login`) and
`extractor.extractor` (`fetch_page`, `get_toc`, `html_to_markdown`).

### Shared request lifecycle

```mermaid
sequenceDiagram
    autonumber
    participant C as MCP client
    participant G as _AuthGate (ASGI)
    participant F as FastMCP
    participant T as tool handler
    participant R as _run_portal
    participant Z as Zoomin API
    C->>G: POST /mcp — JSON-RPC tools/call<br/>X-API-Key, opt X-DOCenter-User
    Note over G: /healthz → 200 (no auth)<br/>verify X-API-Key (hmac)<br/>verify X-DOCenter-User if per-user
    G-->>C: 401 on missing/bad key or token
    G->>F: authorized → pass through
    F->>T: dispatch tool(args)
    T->>T: clamp args (max_results, max_chars…)
    T->>R: _run_portal(fn, …)
    R->>R: _resolve_session() — shared or per-user cookie
    R->>Z: fn(session, …) over HTTPS
    Z-->>R: JSON  (or 403)
    alt HTTP 403 — access_denied
        R->>Z: http_login() re-login (throttled) + retry once
    end
    R-->>T: parsed result
    T-->>F: dict → JSON-encoded text content
    F-->>C: SSE event: message (JSON-RPC result)
```

### Session resolution, cold-start bootstrap & 403 self-heal

Shared by every portal-backed tool (`_run_portal` in `server.py`). The per-user
path never touches the shared cookie, and a shared 403 triggers at most one
throttled re-login per cooldown window.

On the shared path the cookie is also **self-minting**: if no cookie exists yet
(cold start — nothing injected), the first portal call performs one browser-free
HTTP login from `DOCENTER_EMAIL` / `DOCENTER_PASSWORD`, writes the cookie, and
serves the request. So the account password is the single source of truth — you
never have to seed or rotate a cookie by hand (SSO-only accounts still inject one).

```mermaid
flowchart TD
    A["_run_portal(fn, …)"] --> R["_resolve_session()"]
    R --> M{DOCENTER_PER_USER?}
    M -->|off| SH["shared cookie<br/>load_session — session-cookies.json"]
    M -->|on, no user header| SH
    M -->|on, X-DOCenter-User| PU["per-user cookie<br/>load_user_cookie_data(user_id)"]
    PU --> PUX{cookie present?}
    PUX -->|no| SR["raise SessionRequired<br/>+ broker login_url if configured"]
    PUX -->|yes| CALL
    SH --> CALL["fn(session, …) → Zoomin"]
    CALL --> OK{HTTP 403?}
    OK -->|no| DONE["return JSON"]
    OK -->|403, shared| RL["http_login (throttled)<br/>GET /auth/login → POST …/api/login<br/>retry once"]
    OK -->|403, per-user| SR
    RL --> DONE2["retry ok → JSON<br/>else PortalUnavailable"]
```

### `search_docs`

`portal_search_core` runs a broad `GET /search`, resolves product/version to portal
**label keys** and re-runs a faceted `POST /search`, then applies client-side
guide/bundle post-filters, a spelling/synonym retry, a broad **facet fallback**, and
**weak-result broadening**. Version defaulting first calls `discover_bundles` to find
the product's newest version.

```mermaid
flowchart TD
    A["search_docs(query, product?, doc_version?,<br/>guide?, bundle?, max_results, page, retry)"] --> B{"product, no version, no bundle?"}
    B -->|yes| V["_latest_version(slug)<br/>discover_bundles → GET /bundlelist?labelkey=…"]
    B -->|no| S
    V --> S["portal_search_core"]
    S --> U["_portal_search broad<br/>GET /search (q, rpp, page)"]
    U --> F{"product/version facet resolves?"}
    F -->|labelkeys| P["_portal_search faceted<br/>POST /search + labelkeys body"]
    F -->|no facet| PF["client-side bundle post-filter"]
    P --> G["guide / bundle substring post-filter"]
    PF --> G
    G --> RE{"empty and retry?"}
    RE -->|yes| DY["adopt did_you_mean / synonym, re-search"]
    RE -->|no| M
    DY --> M["_map_portal_item → results"]
    M --> FB{"still empty and filters active?"}
    FB -->|yes| BR["broad unfaceted retry<br/>facetFallback=true"]
    FB -->|no| OUT
    BR --> OUT["results + versionUsed,<br/>availableVersions, totalMatches, suggestions"]
```

### `list_docs`

Resolves the product slug from the committed catalog, then discovers every bundle
by paging `GET /bundlelist` over the product's label keys.

```mermaid
flowchart TD
    A["list_docs(product, version?, doc_type?)"] --> B["_resolve_product<br/>(committed PRODUCTS catalog)"]
    B --> C{"slug and label_keys?"}
    C -->|no| E["error: unknown_product / no_label_keys"]
    C -->|yes| D["discover_bundles(session, label_keys)"]
    D --> L["loop labels and pages<br/>GET /bundlelist?labelkey=LABEL (per_page, page)"]
    L --> FI["extract_version + filter (version / doc_type)<br/>+ sort newest-first"]
    FI --> O["result: product, count, bundles"]
```

### `find_bundles`

Same live search as `search_docs`, but aggregates the **distinct bundles** among the
hits by frequency instead of returning pages.

```mermaid
flowchart TD
    A["find_bundles(query, product?, doc_version?, max_results)"] --> S["portal_search_core<br/>GET /search (+ POST facet)"]
    S --> AG["aggregate distinct bundle_id<br/>by hit count, descending"]
    AG --> O["result: query, count, bundles (bundle, hits, version)"]
```

### `get_catalog`

The only tool with **no portal round-trip** — it reads the committed `PRODUCTS`
catalog (shipped under `docenter/data`) and resolves names/aliases/versions offline.

```mermaid
flowchart TD
    A["get_catalog(product?)"] --> N["read committed PRODUCTS catalog<br/>NO portal call"]
    N --> B{product given?}
    B -->|yes| R["_resolve_product → detail<br/>slug, aliases, category, versions"]
    B -->|no| C["roster grouped by category"]
```

### `get_page`

Parses the citation URL and reads the source in full. HTML topics
(`/page/…`) are fetched and converted from `topic_html` to Markdown; resource
PDFs (`/resource/….pdf`, common on older/archived bundles) are resolved to their
raw download via the resource descriptor's `topic_url`, then text-extracted with
pypdf (`format: "pdf"`). Shared logic lives in `extractor.fetch_pdf_text`.

```mermaid
flowchart TD
    A["get_page(url, max_chars)"] --> P{"HTML page or resource PDF?"}
    P -->|"/page/… (HTML)"| PP["_parse_portal_url<br/>regex /bundle/…/page/…"]
    PP --> FE["fetch_page(session, bundle, nav_path)<br/>GET /bundle/BUNDLE/page/NAV_PATH"]
    FE --> H{topic_html empty?}
    H -->|yes| NF["error: not_found"]
    H -->|no| MD["html_to_markdown → truncate(max_chars)"]
    P -->|"/resource/….pdf"| PR["_parse_portal_pdf_url<br/>regex /bundle/…/resource/….pdf"]
    PR --> DESC["GET /bundle/BUNDLE/resource/FILE<br/>JSON descriptor → topic_url"]
    DESC --> RAW["GET topic_url (raw PDF bytes)<br/>/bundle/BUNDLE/raw/resource/enus/FILE"]
    RAW --> PDF["pypdf extract_text → truncate(max_chars)<br/>format: pdf"]
    P -->|neither| BAD["error: bad_url"]
    MD --> O["result: title, bundle, version, updated, url, markdown, truncated"]
    PDF --> O
```

### `get_toc`

Fetches the bundle's TOC tree, flattens it, and builds a page-title + `portal_url`
list.

```mermaid
flowchart TD
    A["get_toc: bundle, title_filter, max_pages"] --> T["extractor get_toc<br/>GET /bundle/BUNDLE/toc?language=enus"]
    T --> FL["flatten_toc → title_filter → cap max_pages"]
    FL --> O["result: bundle, version, count,<br/>pages title+portal_url, truncated"]
```

> Full parameter/return contracts for each tool live in
> [`docenter_mcp/TOOLS.md`](https://github.com/actwise-tools/actwise/blob/main/components/docenter/docenter_mcp/TOOLS.md);
> the same diagrams are in `docenter_mcp/FLOWS.md`.

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

## Per-user mode (`DOCENTER_PER_USER`)

By default the server uses **one shared** DOCenter `_SESSION` cookie for every
caller (the Copilot Studio path). With `DOCENTER_PER_USER` turned on it serves
**each end user from their own** captured cookie — the auth model behind the
[per-user DOCenter portal](../portal.md):

- Every request must carry a signature-valid **`X-DOCenter-User`** header (an
  HMAC token keyed by `DOCENTER_USER_TOKEN_SECRET`) that names the calling user.
  The server verifies it and loads *that user's* cookie from the per-user store.
- A user with no captured cookie yet gets a `SessionRequired` error. When
  `DOCENTER_BROKER_URL` + `DOCENTER_BROKER_SECRET` are set, that error is
  **enriched with a one-time `login_url`** (minted by calling the
  [login broker](../portal.md)'s `POST /links`) so the front end can send the user
  to the two-door login page.
- The whole thing is **additive**: with `DOCENTER_PER_USER` off, behavior is
  byte-for-byte the shared-cookie path, and the existing 403 self-heal writes only
  the shared cookie file (never a per-user path).

| Var | Purpose |
|-----|---------|
| `DOCENTER_PER_USER` | Turn on per-user identity (off = shared cookie). |
| `DOCENTER_USER_TOKEN_SECRET` | HMAC key for `X-DOCenter-User` (must match the portal). |
| `DOCENTER_BROKER_URL` / `DOCENTER_BROKER_SECRET` | Broker to mint one-time login links; unset → plain `SessionRequired`. |

## Safety

Strictly **read-only** — the tools search and fetch documentation only; they
never touch a live ActOne system, run queries, or perform operations. Portal
session errors surface as tool errors, and on the shared path the server both
**cold-start bootstraps** a missing cookie and **self-heals a 403** by logging in
with the configured credentials.

## See also

- CLI: [`docenter`](../cli/docenter.md)
- Bucket: [docenter](../buckets/docenter.md)
- Portal: [ActWise portal](../portal.md) (per-user DOCenter front end)
- Sibling server: [`actimize-docs-mcp`](actimize-docs-mcp.md) (offline BM25)
- Agent: [ActWise Docs](../agents/docs.md)
