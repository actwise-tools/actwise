"""ActWise remote DOCenter MCP server.

Exposes the **live NICE Actimize documentation portal** as Model Context Protocol
tools over **Streamable HTTP**, so any MCP client (GitHub Copilot CLI / VS Code,
Claude Code, Copilot Studio) can search the docs through one remote endpoint.

Design goal — *prove locally, port to CoreAI unchanged.* NICE's own DOCenter MCP
runs FastMCP behind uvicorn; this server uses the identical runtime, so promoting
it to CoreAI is a container/image handoff, not a rewrite.

Tools (lean, proven, all read-only — reuse `copilot_proxy`'s exact code path):
  * search_docs   — faceted live search (product/version/guide/bundle), spell-correct + suggestions
  * list_docs     — bundles for a product, filtered by version / doc type
  * find_bundles  — which doc bundles answer a query (bundle discovery for filtering)
  * get_catalog   — product↔slug↔version map (disambiguate a product / pick a slug)
  * get_page      — full page text (HTML→Markdown) for a search result's portal_url
  * get_toc       — a bundle's table of contents (all page titles + URLs)

Transport
---------
Streamable HTTP, ``stateless_http=True`` (horizontally scalable, no sticky sessions).
The MCP endpoint is mounted at ``/mcp``; ``/healthz`` is an unauthenticated probe.

Auth
----
Optional shared secret via the ``DOCENTER_PROXY_API_KEY`` env var (header
``X-API-Key``) — same contract as ``copilot_proxy``. When the var is unset the
server runs open (convenient for desktop proving); set it for any shared/tunnelled
deployment and in CoreAI.

Credentials
-----------
The portal ``_SESSION`` cookie is loaded server-side via ``docenter.cli.load_session``
(``browser-profile/session-cookies.json``; ~monthly MFA re-login). Swap the cookie
for a real service credential later with zero change to MCP clients.

Run (local)
-----------
  cd <repo root>
  py -m uvicorn docenter_mcp.server:app --host 0.0.0.0 --port 8765
  # endpoint: http://localhost:8765/mcp   health: http://localhost:8765/healthz
"""
from __future__ import annotations

import hmac
import logging
import os
import re
import threading
import time
from typing import Optional

import requests
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

# Reuse the proven live-portal functions from the docenter CLI — the same code
# path copilot_proxy already runs in production POC.
from docenter.cli import (
    PRODUCTS,
    _map_portal_item,
    _resolve_product,
    discover_bundles,
    extract_version,
    http_login,
    load_session,
    portal_search_core,
)

# Full-page fetch, TOC listing + HTML→Markdown reuse the extractor's proven path.
from extractor.extractor import fetch_page, get_toc as _extractor_get_toc, html_to_markdown

SERVER_NAME = "actwise-docenter-live"
API_KEY_ENV = "DOCENTER_PROXY_API_KEY"

# Upper bound for per-call max_results (search_docs / find_bundles). Deployment
# override via env — raising it trades caller context budget for recall.
MAX_RESULTS_CEILING = int(os.environ.get("DOCENTER_MCP_MAX_RESULTS", "50"))

mcp = FastMCP(
    SERVER_NAME,
    stateless_http=True,
    # The MCP StreamableHTTP transport enables DNS-rebinding protection by default,
    # which rejects any request whose Host header isn't localhost ("Invalid Host header").
    # This server is designed to run behind a tunnel / CoreAI ingress (variable Host), and
    # access is already gated by the X-API-Key auth gate, so disable the Host/Origin check.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

# ── Server-side portal session (lazy, cached, refreshable) ────────────────────
_session_lock = threading.Lock()
_session = None

_log = logging.getLogger(SERVER_NAME)

# Auto re-login throttle: at most one browser-free HTTP re-login per cooldown
# window, so a persistently-failing credential can't hammer the portal (which
# risks bot-detection / account lockout). Concurrent 403s reuse the last outcome.
_relogin_lock = threading.Lock()
_relogin_ts = float("-inf")   # time.monotonic() of the last attempt
_relogin_ok = False           # outcome of the last attempt
_RELOGIN_COOLDOWN = float(os.environ.get("DOCENTER_MCP_RELOGIN_COOLDOWN", "60"))


class PortalUnavailable(RuntimeError):
    """Raised when the portal session cannot be established or has expired."""


def _get_session():
    """Return a cached requests.Session bound to the portal cookie.

    ``load_session`` calls ``typer.Exit`` (SystemExit) when the cookie file is
    missing — translate that into a clean tool-level error instead of killing
    the worker."""
    global _session
    with _session_lock:
        if _session is None:
            try:
                _session = load_session()
            except SystemExit as exc:  # missing/invalid cookie file
                raise PortalUnavailable(
                    "Portal session unavailable — run `docenter auth login` on the "
                    "server host to refresh browser-profile/session-cookies.json."
                ) from exc
        return _session


def _reset_session() -> None:
    """Drop the cached session so the next call rebuilds it (post cookie refresh)."""
    global _session
    with _session_lock:
        _session = None


# ── Latest-version resolution (lazy, cached per product) ─────────────────────
_ver_lock = threading.Lock()
_latest_ver_cache: dict[str, tuple] = {}  # slug -> (latest_str, [versions desc])


def _version_key(v: str) -> tuple:
    """Sort key for dotted version strings; non-numeric segments sort low."""
    return tuple(int(seg) if seg.isdigit() else -1 for seg in v.split("."))


def _versions_from_catalog(slug: str) -> list:
    """Versions (newest first) derived from the product's *cached* bundle list.

    Reads ``PRODUCTS[slug]["bundles_detail"]`` (committed catalog) — offline, no
    portal call. May lag the portal by a sync cycle, so it's used as a fast source
    for informational tools and as a fallback when the live lookup fails."""
    cfg = PRODUCTS.get(slug) or {}
    vers = {
        v for b in (cfg.get("bundles_detail") or [])
        if (v := extract_version(b.get("name", ""))) and v != "-"
        and any(c.isdigit() for c in v)
    }
    return sorted(vers, key=_version_key, reverse=True)


def _latest_version(slug: str) -> tuple:
    """Resolve (latest_version, [all_versions_desc]) for a product slug.

    Derived live from the portal's bundle list (same path as ``list_docs``) and
    cached for the process lifetime. Falls back to the committed catalog's cached
    bundle list when the live lookup fails, so a transient portal error degrades to
    "slightly stale version" instead of "no version". Only successful (non-empty)
    resolutions are cached."""
    with _ver_lock:
        if slug in _latest_ver_cache:
            return _latest_ver_cache[slug]
    cfg = PRODUCTS.get(slug) or {}
    label_keys = cfg.get("label_keys", [])
    result = (None, [])
    if label_keys:
        try:
            records = _run_portal(discover_bundles, label_keys)
            vers = {
                v for r in records
                if (v := extract_version(r["name"])) and v != "-"
                and any(c.isdigit() for c in v)
            }
            ordered = sorted(vers, key=_version_key, reverse=True)
            if ordered:
                result = (ordered[0], ordered)
        except Exception:
            result = (None, [])
    if result[0] is None:  # live failed/empty — fall back to the cached catalog
        cached = _versions_from_catalog(slug)
        if cached:
            result = (cached[0], cached)
    if result[0] is not None:  # only cache a successful resolution
        with _ver_lock:
            _latest_ver_cache[slug] = result
    return result


def _try_relogin() -> bool:
    """Attempt a single browser-free HTTP re-login from env creds, throttled.

    Returns True if a fresh authenticated session is now available. Concurrent 403s
    within the cooldown reuse the most recent attempt's outcome instead of each
    firing their own login (avoids a login stampede + portal lockout)."""
    global _relogin_ts, _relogin_ok
    with _relogin_lock:
        now = time.monotonic()
        if now - _relogin_ts < _RELOGIN_COOLDOWN:
            return _relogin_ok  # a very recent attempt already decided this
        _relogin_ts = now
        try:
            http_login()      # primes, posts creds, saves cookies to COOKIES_FILE
            _reset_session()  # drop the stale cached session; rebuilt on next _get_session()
            _relogin_ok = True
            _log.info("portal session auto-refreshed via HTTP re-login")
        except Exception as exc:  # noqa: BLE001 — never surface/log credential values
            _relogin_ok = False
            _log.warning("portal auto re-login failed: %s", exc)
        return _relogin_ok


def _run_portal(fn, *args, **kwargs):
    """Run a portal call, mapping access_denied → auto re-login (once) → clear error."""
    try:
        return fn(_get_session(), *args, **kwargs)
    except RuntimeError as exc:
        if str(exc) != "access_denied":
            raise
        # Cookie expired (403). Try one automatic browser-free re-login from env creds.
        if _try_relogin():
            try:
                return fn(_get_session(), *args, **kwargs)
            except RuntimeError as exc2:
                if str(exc2) != "access_denied":
                    raise
                exc = exc2  # fresh cookie still denied — fall through to manual guidance
        else:
            _reset_session()
        raise PortalUnavailable(
            "Portal session expired (403). Automatic re-login was unavailable or failed "
            "(needs DOCENTER_EMAIL / DOCENTER_PASSWORD). Refresh the cookie with "
            "`docenter auth login` on the server host, then retry."
        ) from exc


# ── Page fetch helpers ───────────────────────────────────────────────────────
_PORTAL_URL_RE = re.compile(r"/bundle/([^/]+)/page/(.+)$")


def _parse_portal_url(url: str):
    """Split a portal/citation URL into (bundle, nav_path).

    Accepts both ``docs.niceactimize.com`` and the backend ``docs-be`` host.
    Returns ``(None, None)`` when the URL isn't a recognizable page link."""
    cleaned = url.split("#", 1)[0].split("?", 1)[0]
    m = _PORTAL_URL_RE.search(cleaned)
    if not m:
        return None, None
    return m.group(1), m.group(2)


def _fetch_page_core(session, bundle: str, nav_path: str) -> dict:
    """``fetch_page`` wrapper that maps HTTP 403 → access_denied so the shared
    ``_run_portal`` session-reset path applies."""
    try:
        return fetch_page(session, bundle, nav_path)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 403:
            raise RuntimeError("access_denied") from exc
        raise RuntimeError(str(exc)) from exc


def _get_toc_core(session, bundle: str) -> list:
    """``get_toc`` wrapper mirroring ``_fetch_page_core``'s 403/error mapping."""
    try:
        return _extractor_get_toc(session, bundle)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 403:
            raise RuntimeError("access_denied") from exc
        raise RuntimeError(str(exc)) from exc


# ── Tools ─────────────────────────────────────────────────────────────────────
@mcp.tool()
def search_docs(
    query: str,
    product: Optional[str] = None,
    doc_version: Optional[str] = None,
    guide: Optional[str] = None,
    bundle: Optional[str] = None,
    max_results: int = 10,
    page: int = 1,
    retry: bool = True,
) -> dict:
    """Search the live NICE Actimize documentation portal and return ranked results.

    Use this to answer product questions with citations back to docs.niceactimize.com.
    The portal ranks by keyword match, not semantics — use short keyword queries
    (one concept per query), drop filler words, and narrow with the filter
    parameters instead of lengthening the query. If results look thin, retry
    without the rarest/abbreviated token.

    Args:
        query: Keyword query, one concept (e.g. "conditional step change plugin").
        product: Optional product slug/alias to narrow results (e.g. "actone", "ifm",
            "sam"). Call `get_catalog` to resolve a product name to its slug instead
            of guessing.
        doc_version: Optional doc version (e.g. "10.1", "11.2"). When omitted and a
            product is given, the newest available version is applied automatically
            (see `versionUsed` / `availableVersions` in the result).
        guide: Optional guide type (e.g. "implementer", "reference"). A substring
            post-filter on the bundle name — a value matching no bundle silently
            empties the results.
        bundle: Optional bundle id to search within a single guide (take it from
            `find_bundles`). Substring post-filter on the bundle name; when set,
            product/version defaulting is skipped (bundle names pin the version).
        max_results: Max results to return (1 to the server cap, default cap 50 —
            env `DOCENTER_MCP_MAX_RESULTS` overrides).
        page: Result page (1-based).
        retry: Auto-retry the portal's spelling/synonym suggestion when empty.

    Returns:
        dict with `results` (title, snippet, shortDesc, updated, bundle, version,
        portal_url — note `title` is sometimes the *guide* title, so check
        `shortDesc`/`updated`/`portal_url` to tell similar hits apart), `count`,
        `totalMatches` (portal's pre-filter match total — more docs exist when it
        exceeds `count`), `originalQuery`, `correctedQuery` (set if a spelling
        correction was adopted), `suggestions` (alternative queries — try one when
        results look off-target), `filtersActive`, `facetFallback` (empty faceted
        search was retried broad), `broadened` (weak version-scoped results were
        topped up from other versions), `versionUsed` (the doc version actually
        searched), `versionDefaulted` (true when the newest version was
        auto-applied), and `availableVersions`.
    """
    max_results = max(1, min(MAX_RESULTS_CEILING, max_results))

    def _do(pr, dv, gd):
        return _run_portal(
            portal_search_core,
            query,
            max_results=max_results,
            page=page,
            product=pr,
            doc_version=dv,
            guide=gd,
            bundle=bundle,
            retry=retry,
        )

    # Version defaulting: when the caller names a product but no version, scope to
    # the product's newest version. ActOne (and other "platform" products) have
    # version-segmented facets, so an unversioned product filter returns 0 results
    # and — worse — the broad fallback scatters hits across old versions and other
    # products. Defaulting to latest keeps answers coherent and current. An explicit
    # bundle already pins a version, so it disables defaulting.
    slug = _resolve_product(product) if product else None
    resolved_version = doc_version
    version_defaulted = False
    available_versions: list = []
    if slug and not doc_version and not bundle:
        latest, avail = _latest_version(slug)
        if latest:
            resolved_version = latest
            version_defaulted = True
            available_versions = avail

    sr = _do(product, resolved_version, guide)

    # Facet fallback: if a faceted search still comes back empty (e.g. the topic
    # only exists in an older version, or the facet key didn't resolve), retry as a
    # broad search — the query text still drives relevance, far better than nothing.
    # An explicit bundle scope is kept (it's the caller's stated intent).
    facet_fallback = False
    if not sr["results"] and (product or resolved_version or guide):
        broad = _do(None, None, None)
        if broad["results"]:
            sr = broad
            facet_fallback = True
            resolved_version = None
            version_defaulted = False

    # Weak-result broadening: a defaulted-to-latest search that found only a hit or
    # two may be hiding better coverage in older versions. Top up (don't replace)
    # with broad results, faceted hits first; per-result `version` shows the mix.
    broadened = False
    if version_defaulted and 0 < len(sr["results"]) < 3:
        broad = _do(None, None, None)
        seen = {(it.get("leading_result") or {}).get("url", "") for it in sr["results"]}
        extra = [
            it for it in broad["results"]
            if (it.get("leading_result") or {}).get("url", "") not in seen
        ]
        if extra:
            sr = {**sr, "results": (sr["results"] + extra)[:max_results]}
            broadened = True

    results = []
    for item in sr["results"]:
        m = _map_portal_item(item)
        results.append(
            {
                "title": m["title"],
                "bundle": m["bundle"],
                "version": extract_version(m["bundle"]),
                "snippet": m["snippet"] or m["title"],
                "shortDesc": m["short_desc"],
                "updated": m["updated"],
                "portal_url": m["portal_url"],
            }
        )
    return {
        "results": results,
        "count": len(results),
        "totalMatches": sr["pagination"].get("raw_total_count"),
        "originalQuery": query,
        "correctedQuery": sr["effective_query"] if sr["corrected_from"] else None,
        "suggestions": sr["suggestions"],
        "filtersActive": sr["filters_active"],
        "facetFallback": facet_fallback,
        "broadened": broadened,
        "versionUsed": resolved_version,
        "versionDefaulted": version_defaulted,
        "availableVersions": available_versions,
    }


@mcp.tool()
def list_docs(
    product: str,
    version: Optional[str] = None,
    doc_type: Optional[str] = None,
) -> dict:
    """List documentation bundles for a product, optionally filtered by version / type.

    Discovers bundles live from the portal (Product Info, Release Notes, Patch Notes,
    etc.) — a working alternative to the upstream DOCenter MCP's broken list tool.

    Args:
        product: Product slug or alias (e.g. "actone", "sam", "ifm"). See find_bundles / docs.
        version: Optional version filter (e.g. "10.1"). Version-agnostic bundles are kept.
        doc_type: Optional doc-type substring (e.g. "Product Documentation", "Release Notes").

    Returns:
        dict with `product`, `count`, and `bundles` (name, doc_type, version, updated),
        newest first — or an `error` when the product is unknown.
    """
    if not PRODUCTS:
        return {"error": "no_catalog", "message": "No product catalog loaded. Run: docenter catalog refresh"}
    slug = _resolve_product(product)
    if slug is None:
        return {"error": "unknown_product", "message": f"Unknown product: '{product}'"}

    cfg = PRODUCTS[slug]
    label_keys = cfg.get("label_keys", [])
    if not label_keys:
        return {"error": "no_label_keys", "message": f"No discovery label keys configured for '{slug}'."}

    exclude_prefixes = cfg.get("discovery_exclude_prefixes", [])
    config_set = set(cfg.get("bundles", []))

    records = _run_portal(discover_bundles, label_keys)
    if exclude_prefixes:
        records = [
            r for r in records
            if not any(r["name"].startswith(p) for p in exclude_prefixes) or r["name"] in config_set
        ]

    for r in records:
        r["version"] = extract_version(r["name"])

    if version:
        records = [r for r in records if r["version"] == version or r["version"] == "-"]
    if doc_type:
        needle = doc_type.lower()
        records = [r for r in records if needle in (r.get("doc_type") or "").lower()]

    records.sort(key=lambda r: r.get("updated") or "", reverse=True)
    return {"product": slug, "name": cfg.get("name", slug), "count": len(records), "bundles": records}


@mcp.tool()
def find_bundles(
    query: str,
    product: Optional[str] = None,
    doc_version: Optional[str] = None,
    max_results: int = 20,
) -> dict:
    """Find which documentation bundles answer a query (bundle discovery).

    Runs a live search and aggregates the distinct bundles among the hits, ranked
    by hit count — use it to pick a `product`/`doc_version` (or a specific bundle)
    to narrow a follow-up `search_docs` call.

    Args:
        query: The topic to locate (e.g. "DART drill down query").
        product: Optional product slug/alias to narrow.
        doc_version: Optional doc version to narrow.
        max_results: How many underlying hits to aggregate over (1 to the server
            cap, default cap 50 — env `DOCENTER_MCP_MAX_RESULTS` overrides).

    Returns:
        dict with `query` and `bundles` (bundle id + hit count), most relevant first.
    """
    max_results = max(1, min(MAX_RESULTS_CEILING, max_results))
    sr = _run_portal(
        portal_search_core,
        query,
        max_results=max_results,
        product=product,
        doc_version=doc_version,
    )
    counts: dict[str, int] = {}
    order: list[str] = []
    for item in sr["results"]:
        m = _map_portal_item(item)
        b = m["bundle"]
        if b == "-" or not b:
            continue
        if b not in counts:
            order.append(b)
        counts[b] = counts.get(b, 0) + 1
    bundles = [
        {"bundle": b, "hits": counts[b], "version": extract_version(b)}
        for b in sorted(order, key=lambda x: counts[x], reverse=True)
    ]
    return {"query": query, "count": len(bundles), "bundles": bundles}


@mcp.tool()
def get_catalog(product: Optional[str] = None) -> dict:
    """Look up the Actimize product catalog: slugs, aliases, and available versions.

    Use this to DISAMBIGUATE a product or pick the right `product` slug for
    `search_docs` — it is the authoritative product↔slug↔version map, served from
    the catalog (no portal round-trip). Prefer this over guessing a slug.

    Args:
        product: Optional product name, alias, or slug (e.g. "ActOne", "pltact",
            "actone"). Omit to list the full product roster grouped by category.

    Returns:
        - With `product`: `{resolved: true, product: {slug, name, aliases, category,
          description, latestVersion, versions}}` — or `{resolved: false, suggestions}`
          when the name can't be matched.
        - Without `product`: `{categories: [{id, name, products: [{slug, name,
          latestVersion, versionCount}]}], productCount}`.
    """
    if not PRODUCTS:
        return {"error": "no_catalog",
                "message": "No product catalog loaded. Run: docenter catalog refresh"}

    if product:
        slug = _resolve_product(product)
        if slug is None:
            needle = product.lower()
            suggestions = [
                s for s, cfg in PRODUCTS.items()
                if needle in s.lower() or needle in (cfg.get("name", "") or "").lower()
            ][:8]
            return {"resolved": False, "query": product, "suggestions": suggestions}
        cfg = PRODUCTS[slug]
        versions = _versions_from_catalog(slug)
        return {
            "resolved": True,
            "product": {
                "slug": slug,
                "name": cfg.get("name", slug),
                "aliases": cfg.get("aliases", []),
                "category": cfg.get("category", ""),
                "description": cfg.get("description", ""),
                "latestVersion": versions[0] if versions else None,
                "versions": versions,
            },
        }

    # Full roster, grouped by category.
    cats: dict[str, dict] = {}
    for slug, cfg in PRODUCTS.items():
        cid = cfg.get("category_id") or "other"
        cat = cats.setdefault(cid, {"id": cid, "name": cfg.get("category", cid), "products": []})
        versions = _versions_from_catalog(slug)
        cat["products"].append({
            "slug": slug,
            "name": cfg.get("name", slug),
            "latestVersion": versions[0] if versions else None,
            "versionCount": len(versions),
        })
    for cat in cats.values():
        cat["products"].sort(key=lambda p: p["slug"])
    return {
        "categories": sorted(cats.values(), key=lambda c: c["name"]),
        "productCount": len(PRODUCTS),
    }


@mcp.tool()
def get_page(url: str, max_chars: int = 12000) -> dict:
    """Fetch the full text of a documentation page as Markdown.

    Use this after `search_docs` to read a result in full — pass the result's
    `portal_url`. Returns the complete page body (HTML→Markdown), not just the
    search snippet, so answers can quote the source accurately.

    Args:
        url: A page citation URL (the `portal_url` from `search_docs`), e.g.
            "https://docs.niceactimize.com/bundle/<bundle>/page/Content/.../Page.htm".
        max_chars: Truncate the returned Markdown to this many characters
            (clamped 500–50000); `truncated` flags when content was cut.

    Returns:
        dict with `title`, `bundle`, `version`, `updated`, `url`, `markdown`,
        `truncated` — or an `error` ("bad_url" / "not_found") when the page can't
        be resolved.
    """
    max_chars = max(500, min(50000, max_chars))
    bundle, nav_path = _parse_portal_url(url)
    if not bundle:
        return {
            "error": "bad_url",
            "message": "Expected a portal page URL like "
            ".../bundle/<bundle>/page/Content/.../<Page>.htm",
        }

    data = _run_portal(_fetch_page_core, bundle, nav_path)
    topic_html = (data.get("topic_html") or "").strip()
    if not topic_html:
        return {
            "error": "not_found",
            "message": f"No page content for {bundle}/{nav_path}.",
            "bundle": bundle,
        }

    md = html_to_markdown(topic_html).strip()
    truncated = len(md) > max_chars
    return {
        "title": data.get("title", "-"),
        "bundle": bundle,
        "version": extract_version(bundle),
        "updated": (data.get("dates") or {}).get("Updated on", "")[:10],
        "url": f"https://docs.niceactimize.com/bundle/{bundle}/page/{nav_path}",
        "markdown": md[:max_chars],
        "truncated": truncated,
    }


@mcp.tool()
def get_toc(bundle: str, title_filter: Optional[str] = None, max_pages: int = 200) -> dict:
    """List a documentation bundle's table of contents: every page title + URL.

    Use this after `list_docs` / `find_bundles` to see what a guide actually
    contains — e.g. open a Release Notes bundle to find every release page in it
    (base release, SP1, patches) and pick the newest, or locate the exact page
    for `get_page` without another search. Page titles here are the real page
    titles (search results sometimes show the guide title instead).

    Args:
        bundle: Exact bundle id (from `list_docs` / `find_bundles` /
            a search result's `bundle`), e.g. "Actimize_ActOne_10.2_Release_Notes".
        title_filter: Optional case-insensitive substring to keep only matching
            page titles (e.g. "release", "upgrade").
        max_pages: Max pages to return (clamped 1-500); `truncated` flags a cut.

    Returns:
        dict with `bundle`, `version`, `count` (total pages after filtering),
        `pages` (title, portal_url), `truncated` — or an `error`
        ("unknown_bundle") when the bundle can't be resolved.
    """
    max_pages = max(1, min(500, max_pages))
    try:
        entries = _run_portal(_get_toc_core, bundle)
    except PortalUnavailable:
        raise
    except RuntimeError as exc:
        return {"error": "unknown_bundle", "message": f"No TOC for '{bundle}': {exc}"}

    if title_filter:
        needle = title_filter.lower()
        entries = [e for e in entries if needle in (e.get("title") or "").lower()]

    pages = [
        {
            "title": e.get("title", "-"),
            "portal_url": f"https://docs.niceactimize.com/bundle/{bundle}/page/{e['path']}",
        }
        for e in entries[:max_pages]
    ]
    return {
        "bundle": bundle,
        "version": extract_version(bundle),
        "count": len(entries),
        "pages": pages,
        "truncated": len(entries) > max_pages,
    }


# ── ASGI app: auth gate + health, wrapping the Streamable-HTTP MCP ────────────
class _AuthGate:
    """Pure-ASGI middleware: serves /healthz, enforces X-API-Key when configured.

    Pure ASGI (not BaseHTTPMiddleware) so it never buffers the MCP stream and
    passes lifespan events straight through to the FastMCP session manager."""

    def __init__(self, app, api_key: Optional[str]):
        self.app = app
        self.api_key = api_key

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path == "/healthz":
            await JSONResponse({"status": "ok", "server": SERVER_NAME})(scope, receive, send)
            return
        if self.api_key:
            headers = dict(scope.get("headers") or [])
            provided = headers.get(b"x-api-key", b"").decode()
            if not (provided and hmac.compare_digest(provided, self.api_key)):
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


app = _AuthGate(mcp.streamable_http_app(), os.environ.get(API_KEY_ENV))


def main() -> None:
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("DOCENTER_MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("DOCENTER_MCP_PORT", "8765")),
    )


if __name__ == "__main__":
    main()
