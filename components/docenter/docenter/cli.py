"""
DOCenter CLI — Browse and download NICE Actimize documentation.

Usage:
    docenter auth login                              # SSO login (saves 28-day session)
    docenter auth status                            # Check session expiry
    docenter auth logout                            # Remove saved session
    docenter list-products                          # All products + local status
    docenter list-docs actone                       # All ActOne bundles by version
    docenter list-docs actone --version 10.1        # Filter to one version
    docenter list-docs sam --pages                  # Include live page counts
    docenter download actone --format md --version 10.1
    docenter download actone --format pdf --bundle Actimize_ActOne_10.1_Implementer_Guide
    docenter download actone --format md --dry-run
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# Ensure UTF-8 output on Windows so Rich can render Unicode table chars correctly
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Load .env before anything else reads env vars. Prefer the current working
# directory, then the source-checkout root (one level above this package).
from pathlib import Path as _Path
from actwise.paths import repo_root
for _env_file in (_Path.cwd() / ".env", (repo_root() or _Path(__file__).resolve().parent.parent) / ".env"):
    if _env_file.exists():
        try:
            from dotenv import load_dotenv as _load_dotenv
            _load_dotenv(_env_file, override=False)  # .env sets defaults; real env vars win
        except ImportError:
            pass  # dotenv not installed — env vars must be set manually
        break

# Back-compat: the project was renamed doccenter -> docenter. Older .env files and
# shells use the DOCCENTER_* prefix; alias them to the canonical DOCENTER_* names so
# existing setups keep working without edits. (setdefault: a real DOCENTER_* wins.)
for _k, _v in list(os.environ.items()):
    if _k.startswith("DOCCENTER_"):
        os.environ.setdefault("DOCENTER_" + _k[len("DOCCENTER_"):], _v)

import typer
from rich.console import Console
from rich.table import Table
from rich import print as rprint

# ── Config ─────────────────────────────────────────────────────────────────────

PKG_DIR = Path(__file__).resolve().parent          # .../docenter (installed or source)
REPO_ROOT = repo_root() or PKG_DIR.parent            # repo root in a source checkout
USER_DIR = Path(os.environ.get("DOCENTER_HOME", str(Path.home() / ".docenter")))

# One-time, best-effort migration of the legacy ~/.doccenter directory to ~/.docenter
# (only when the new dir doesn't exist yet and no explicit DOCENTER_HOME is set).
_legacy_user_dir = Path.home() / ".doccenter"
if (
    _legacy_user_dir.exists()
    and not USER_DIR.exists()
    and "DOCENTER_HOME" not in os.environ
):
    try:
        _legacy_user_dir.rename(USER_DIR)
    except OSError:
        pass


def _resolve_path(env_var: str, repo_default: Path, user_default: Path) -> Path:
    """Resolve a runtime path. An explicit env var always wins; otherwise use the
    source-checkout location if it exists; otherwise fall back to a user-dir default
    (so the pip-installed CLI works from any working directory)."""
    val = os.environ.get(env_var)
    if val:
        return Path(val).expanduser()
    if repo_default.exists():
        return repo_default
    return user_default

# ── Zoomin portal ──────────────────────────────────────────────────────────────
PORTAL_URL = os.environ.get("DOCENTER_PORTAL_URL", "https://docs.niceactimize.com")
BASE_API = os.environ.get("DOCENTER_API_URL", "https://docs-be.niceactimize.com/api")
ZOOMIN_ALT_URL = os.environ.get("DOCENTER_ZOOMIN_ALT_URL", "https://niceactimize.zoominsoftware.io")

# Credentials (populated from .env — never hardcoded here)
DOCENTER_EMAIL = os.environ.get("DOCENTER_EMAIL", "")
DOCENTER_PASSWORD = os.environ.get("DOCENTER_PASSWORD", "")
DOCENTER_ZOOMIN_ALT_PASSWORD = os.environ.get("DOCENTER_ZOOMIN_ALT_PASSWORD", "")

COOKIES_FILE = _resolve_path(
    "DOCENTER_COOKIES_FILE",
    REPO_ROOT / "browser-profile" / "session-cookies.json",
    USER_DIR / "session-cookies.json",
)
RAW_DOCS_DIR = _resolve_path(
    "DOCENTER_RAW_DOCS_DIR",
    REPO_ROOT / "raw_docs",
    Path.cwd() / "raw_docs",
)
RAW_PDF_DIR = _resolve_path(
    "DOCENTER_RAW_PDF_DIR",
    REPO_ROOT / "raw_docs_pdf",
    Path.cwd() / "raw_docs_pdf",
)

# ── SharePoint ─────────────────────────────────────────────────────────────────
SP_SITE_URL = os.environ.get(
    "ACTWISE_SP_SITE",
    "https://niceonline.sharepoint.com/teams/ActWiseDocumentation",
)
SP_DEFAULT_FOLDER = os.environ.get("ACTWISE_SP_FOLDER", "Shared Documents/ActWise")
SP_COOKIES_FILE = _resolve_path(
    "ACTWISE_SP_COOKIES_FILE",
    REPO_ROOT / "browser-profile" / "sharepoint-cookies.json",
    USER_DIR / "sharepoint-cookies.json",
)
_SP_SITE_PATH = "/" + SP_SITE_URL.split("/", 3)[-1]  # e.g. /teams/ActWiseDocumentation

# ── Doc type constants ─────────────────────────────────────────────────────────

# Zoomin's native "Type of Information" taxonomy label keys
DOC_TYPE_LABEL_KEYS = {
    "type-product-info":           "Product Info",
    "type-product-doc":            "Product Documentation",
    "type-release-notes":          "Release Notes",
    "type-release-notification":   "Release Notifications",
    "type-patch-release-notes":    "Patch Release Notes",
    "type-professional-services":  "Professional Services",
}

DOC_TYPES = list(DOC_TYPE_LABEL_KEYS.values())

def _resolve_catalog_file() -> Path:
    """Resolve the catalog path. Read order: explicit override → source-checkout
    docs/catalog.yaml → bundled package data (internal builds ship this) → a
    user-writable location that a first-run `catalog refresh` populates.

    Per the Option-A distribution decision, the *public* package ships no catalog
    data, so on a clean public install this falls through to ~/.docenter/catalog.yaml,
    which `catalog refresh` (or the first-run fetch) writes."""
    override = os.environ.get("DOCENTER_CATALOG_FILE")
    if override:
        return Path(override).expanduser()
    repo = REPO_ROOT / "docs" / "catalog.yaml"
    if repo.exists():
        return repo
    bundled = PKG_DIR / "data" / "catalog.yaml"
    if bundled.exists():
        return bundled
    return USER_DIR / "catalog.yaml"


CATALOG_FILE = _resolve_catalog_file()


def _extractor_env() -> dict:
    """Environment for the extractor subprocess so it writes to the same corpus and
    reads the same cookies the CLI resolved (works for source checkout and pip install)."""
    env = dict(os.environ)
    env["DOCENTER_RAW_DOCS_DIR"] = str(RAW_DOCS_DIR)
    env["DOCENTER_RAW_PDF_DIR"] = str(RAW_PDF_DIR)
    env["DOCENTER_COOKIES_FILE"] = str(COOKIES_FILE)
    return env


def _extractor_dir() -> Path:
    """Directory containing extractor.py / pdf_exporter.py (a sibling package of docenter)."""
    import extractor
    return Path(extractor.__file__).resolve().parent

# Legacy overrides: preserve the short slugs, raw_docs paths, and cross-tag
# exclusions used before the catalog-backed loader. Keyed by the desired short
# slug; `title_match` finds the corresponding product in catalog.yaml.
LEGACY_OVERRIDES: dict[str, dict] = {
    "actone": {
        "title_match": "ActOne",
        "category_id": "plt",
        "output_dir": "actone",
        # Zoomin cross-tags other products under ActOne label keys because SAM,
        # CDD, IFM, AIS, FMC, WL-X etc. all run on the ActOne platform.
        "discovery_exclude_prefixes": [
            "Actimize_AML_SAM", "AML_SAM_",
            "Actimize_AML_CDD",
            "Actimize_Fraud_",
            "Actimize_X-Sight_",
            "Actimize_AIS_",
            "Actimize_FMC_",
            "AML_Screening_",
            "Data_Extract_",
        ],
    },
    "sam": {
        "title_match": "Suspicious Activity Monitoring (SAM)",
        "category_id": "aml",
        "output_dir": "sam",
        "discovery_exclude_prefixes": [
            "Actimize_ActOne_",
            "Release_Notes_Platform_ActOne_",
            "Actimize_AIS_",
            "Actimize_Fraud_IFM",
            "Actimize_X-Sight_",
            "Actimize_FMC_",
            "Data_Extract_",
        ],
    },
    "cdd": {
        "title_match": "Customer Due Diligence (CDD)",
        "category_id": "aml",
        "output_dir": "cdd",
        "discovery_exclude_prefixes": [
            "AML_Support_Migration_",
            "AML_Videos",
            "SAM_STAR_",
        ],
    },
    "xse-sam": {
        "title_match": "X-Sight Enterprise Suspicious Activity Monitoring (SAM)",
        "category_id": "aml",
        "output_dir": "xse-sam",
    },
    "xse-cdd": {
        "title_match": "X-Sight Enterprise Customer Due Diligence (CDD)",
        "category_id": "aml",
        "output_dir": "xse-cdd",
    },
    "xse-fraud": {
        "title_match": "X-Sight Enterprise Fraud",
        "category_id": "ifm",
        "output_dir": "xse-fraud",
    },
    "ifm": {
        "title_match": "Integrated Fraud Management (IFM)",
        "category_id": "ifm",
        "output_dir": "ifm",
    },
}


def _slugify(text: str) -> str:
    """Lowercase kebab-case slug. Drops parenthesized substrings."""
    s = re.sub(r"\s*\(.*?\)\s*", " ", text)
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s


def _short_abbreviation(title: str) -> Optional[str]:
    """Extract a parenthesized abbreviation at end of title, e.g. '... (SAM)' -> 'sam'."""
    m = re.search(r"\(([A-Za-z][A-Za-z0-9-]{1,8})\)\s*$", title)
    return m.group(1).lower() if m else None


def _preferred_slug(title: str) -> str:
    """Pick the most ergonomic CLI slug for a product title.

    Rules (first match wins):
      1. Title starts with "X-Sight Enterprise" → prefix slug with "xse-".
         If a trailing (ABC) abbreviation exists, slug = xse-abc; otherwise slug
         = xse + slugified remainder.
      2. Trailing (ABC) abbreviation → use the abbreviation as the slug.
      3. Fall back to full slugified title.
    """
    base_no_abbr = re.sub(r"\s*\([A-Za-z][A-Za-z0-9-]{1,8}\)\s*$", "", title).strip()
    abbr = _short_abbreviation(title)
    if base_no_abbr.startswith("X-Sight Enterprise"):
        if abbr:
            return f"xse-{abbr}"
        remainder = base_no_abbr[len("X-Sight Enterprise"):].strip()
        return f"xse-{_slugify(remainder)}" if remainder else "xse"
    if abbr:
        return abbr
    return _slugify(title)


def _load_catalog_products() -> dict[str, dict]:
    """Load catalog.yaml and return dict[slug] -> product config.

    Schema returned for each product matches the legacy PRODUCTS contract:
        name, output_dir, label_keys, bundles, discovery_exclude_prefixes (optional)
    Plus catalog-only extras: title, category_id, category, description,
    bundles_detail, aliases.

    Legacy short slugs (actone, sam, cdd, ifm, xse-sam, xse-cdd, xse-fraud)
    are preserved via LEGACY_OVERRIDES.
    """
    if not CATALOG_FILE.exists():
        # Fall back to empty dict; commands will print a clear refresh prompt.
        return {}

    try:
        import yaml
    except ImportError:
        rprint("[red]Missing dependency:[/red] pip install pyyaml")
        return {}

    with CATALOG_FILE.open(encoding="utf-8") as f:
        catalog = yaml.safe_load(f) or {}

    # Build reverse lookup: title -> override slug
    override_by_title = {ov["title_match"]: slug for slug, ov in LEGACY_OVERRIDES.items()}

    products: dict[str, dict] = {}
    alias_claims: dict[str, str] = {}  # abbreviation alias -> first claiming slug

    for cat in catalog.get("categories", []):
        cat_id = cat.get("id")
        cat_title = cat.get("title")
        for prod in cat.get("products", []):
            title = prod.get("title") or ""
            override = LEGACY_OVERRIDES.get(override_by_title.get(title, ""), {})

            # Primary slug: legacy short key when present, else preferred
            if title in override_by_title:
                slug = override_by_title[title]
            else:
                slug = _preferred_slug(title) or prod.get("id", "")
            if not slug or slug in products:
                # Collision (or empty): tack on category id and fall back to long slug
                long_slug = _slugify(title) or prod.get("id", "unknown")
                slug = long_slug if long_slug not in products else f"{long_slug}-{cat_id}"

            # Aliases: catalog id, parenthesized abbreviation, and the long slugified title
            aliases: list[str] = []

            def _claim(alias: str) -> None:
                if not alias or alias == slug or alias in aliases:
                    return
                if alias in products or alias in alias_claims:
                    return
                aliases.append(alias)
                alias_claims[alias] = slug

            cid = prod.get("id")
            if cid:
                _claim(cid.lower())
            _claim(_short_abbreviation(title) or "")
            _claim(_slugify(title))

            bundles_detail = prod.get("bundles") or []
            bundle_names = [b.get("name") for b in bundles_detail if b.get("name")]

            products[slug] = {
                "name": title,
                "title": title,
                "category_id": cat_id,
                "category": cat_title,
                "description": prod.get("description"),
                "output_dir": override.get("output_dir", slug),
                "label_keys": prod.get("label_keys") or [],
                "bundles": bundle_names,
                "bundles_detail": bundles_detail,
                "aliases": aliases,
                "discovery_exclude_prefixes": override.get("discovery_exclude_prefixes", []),
            }

    return products


def _resolve_product(name: str) -> Optional[str]:
    """Return the canonical slug for a product name or alias, or None if unknown."""
    if not name:
        return None
    key = name.lower()
    if key in PRODUCTS:
        return key
    for slug, cfg in PRODUCTS.items():
        if key in (a.lower() for a in cfg.get("aliases", [])):
            return slug
    return None


def _require_product(product: str) -> str:
    """Resolve product slug/alias and exit with a friendly message on failure.

    Returns the canonical slug for downstream PRODUCTS[slug] lookups.
    """
    if not _ensure_catalog():
        rprint("[red]No product catalog available.[/red]")
        rprint("Run [bold]docenter auth login[/bold] then [bold]docenter catalog refresh[/bold].")
        raise typer.Exit(1)
    resolved = _resolve_product(product)
    if resolved is None:
        rprint(f"[red]Unknown product:[/red] '{product}'.")
        rprint("Run [bold]docenter list-products[/bold] to see all available products and aliases.")
        raise typer.Exit(1)
    return resolved


PRODUCTS: dict[str, dict] = _load_catalog_products()


def _ensure_catalog(json_out: bool = False) -> bool:
    """Ensure a product catalog is loaded, fetching it once on first use if needed.

    The public package ships no catalog data (Option-A distribution), so the first
    catalog-dependent command offers to fetch it from the portal and save it to
    ``CATALOG_FILE`` (``~/.docenter/catalog.yaml`` on a clean public install).
    Returns True when ``PRODUCTS`` is populated.
    """
    global PRODUCTS
    if PRODUCTS:
        return True
    # A catalog file may exist but have failed to parse on first import — retry once.
    if CATALOG_FILE.exists():
        PRODUCTS = _load_catalog_products()
        if PRODUCTS:
            return True
    # No usable catalog. Don't prompt in machine/non-interactive contexts.
    if json_out or not sys.stdin.isatty():
        return False
    rprint("[yellow]No local product catalog found.[/yellow]")
    rprint(f"It can be fetched once from the portal and saved to [bold]{CATALOG_FILE}[/bold].")
    rprint("[dim](Requires a valid session — run 'docenter auth login' first if this fails.)[/dim]")
    if not typer.confirm("Fetch the catalog now?", default=True):
        return False
    try:
        catalog_builder.build_catalog()
    except Exception as e:
        rprint(f"[red]Catalog fetch failed:[/red] {e}")
        return False
    PRODUCTS = _load_catalog_products()
    return bool(PRODUCTS)


# ── (legacy hardcoded PRODUCTS dict removed — see _load_catalog_products + LEGACY_OVERRIDES above)



# ── Session ────────────────────────────────────────────────────────────────────

def build_session_from_cookies(data):
    """Build a requests.Session from parsed cookie-file data.

    Extracted from ``load_session`` so callers with their own cookie payload
    (e.g. the MCP's per-user store) can build a session without touching the
    shared cookie file. ``data`` is the parsed JSON: ``{"data": {"cookies": [...]}}``."""
    import requests

    session = requests.Session()
    for c in data["data"]["cookies"]:
        session.cookies.set(c["name"], c["value"], domain=c["domain"])
    session.headers.update({"Accept": "application/json"})
    # The /bundlelist endpoint has a server-side bug: it sends
    # Content-Encoding: gzip even when the body is not gzip-encoded.
    # Strip the header only for bundlelist responses — TOC and page
    # responses use valid gzip encoding that must not be stripped.
    def _strip_bad_encoding(r, *a, **kw):
        if "bundlelist" in r.url or "/search" in r.url:
            r.headers.pop("Content-Encoding", None)
            if hasattr(r, "raw") and hasattr(r.raw, "headers"):
                r.raw.headers.pop("content-encoding", None)
    session.hooks["response"].append(_strip_bad_encoding)
    return session


def load_session():
    """Load a requests.Session from the stored session cookie file."""
    try:
        import requests  # noqa: F401  (surface a clean error if requests is missing)
    except ImportError:
        rprint("[red]Missing dependency:[/red] run [bold]pip install requests[/bold]")
        raise typer.Exit(1)

    if not COOKIES_FILE.exists():
        rprint(f"[red]Session cookie not found:[/red] {COOKIES_FILE}")
        rprint("Save cookies to [bold]browser-profile/session-cookies.json[/bold].")
        raise typer.Exit(1)

    raw = COOKIES_FILE.read_bytes()
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8"
    data = json.loads(raw.decode(encoding))
    return build_session_from_cookies(data)


def _save_requests_cookies(cookies_file: Path, session) -> None:
    """Persist a requests.Session cookie jar in the format load_session() expects."""
    cookies_file.parent.mkdir(parents=True, exist_ok=True)
    cookies_file.write_text(
        json.dumps(requests_cookies_to_payload(session), indent=2), encoding="utf-8"
    )


def requests_cookies_to_payload(session) -> dict:
    """Convert a ``requests.Session`` cookie jar into the ``{"data": {"cookies": [...]}}``
    payload that ``build_session_from_cookies`` / the per-user store consume.

    The requests-side analog of ``cookies_to_payload`` (Playwright). Shared by
    ``_save_requests_cookies`` (writes the shared file) and the broker's password
    door (writes the per-user store) so both produce identical cookie payloads."""
    return {
        "data": {
            "cookies": [
                {
                    "name": c.name,
                    "value": c.value,
                    "domain": c.domain,
                    "path": c.path or "/",
                    "expires": c.expires if c.expires else -1,
                    "httpOnly": bool(c.has_nonstandard_attr("HttpOnly")),
                    "secure": bool(c.secure),
                }
                for c in session.cookies
            ]
        }
    }


def http_login(email: str = "", password: str = "", *, save: bool = True):
    """Authenticate to the Zoomin portal via the HTTP login API — no browser.

    Mirrors the browser flow without launching Playwright: primes a pre-auth
    ``_SESSION`` (the login endpoint returns 400 without it), exchanges credentials
    for an authenticated ``_SESSION`` (HTTP 204), and — by default — persists the
    cookies to ``COOKIES_FILE`` so ``load_session()`` picks them up on the next call.
    Returns the authenticated ``requests.Session``; raises ``RuntimeError`` on failure.

    Works only for password accounts (``DOCENTER_EMAIL`` / ``DOCENTER_PASSWORD``);
    SSO-only accounts must use the browser flow (``docenter auth login``).
    """
    import requests

    email = email or DOCENTER_EMAIL
    password = password or DOCENTER_PASSWORD
    if not email or not password:
        raise RuntimeError("DOCENTER_EMAIL / DOCENTER_PASSWORD not set in environment")

    api_origin = BASE_API[:-4] if BASE_API.endswith("/api") else BASE_API
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    # 1. Prime a pre-auth _SESSION — the login endpoint 400s without it.
    session.get(f"{PORTAL_URL}/auth/login", timeout=30)
    # 2. Exchange credentials for an authenticated _SESSION (200/204 on success).
    resp = session.post(
        f"{api_origin}/auth/page/localStorage/api/login",
        json={"userName": email, "password": password},
        timeout=30,
    )
    if resp.status_code not in (200, 204):
        raise RuntimeError(f"portal login failed (HTTP {resp.status_code})")
    # ZD__userAuthenticated is normally set client-side by the portal JS; a confirmed
    # login means we're authenticated, so record it for parity with the browser flow
    # (auth status / browser success-detection check this flag). Harmless on API calls
    # — it's scoped to the portal host, not the docs-be API host.
    from urllib.parse import urlparse
    _portal_host = urlparse(PORTAL_URL).hostname or "docs.niceactimize.com"
    session.cookies.set("ZD__userAuthenticated", "true", domain=_portal_host)
    if save:
        _save_requests_cookies(COOKIES_FILE, session)
    return session


# ── Helpers ────────────────────────────────────────────────────────────────────

def extract_version(bundle_name: str) -> str:
    """Pull version number from a bundle name.

    Handles standard dot notation (_10.1_, _11.2_) and IFM underscore
    notation (_11_1_, _11_2_) where SP patches use underscores.
    """
    # Standard: _10.1_ or _11.2_
    m = re.search(r"_(\d+\.\d+)", bundle_name)
    if m:
        return m.group(1)
    # IFM SP pattern: IFM_11_1_ or IFM_11_2_
    m = re.search(r"IFM_(\d+)_(\d+)", bundle_name)
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    # IFM-X has no version number
    if "IFM-X" in bundle_name:
        return "X"
    return "-"


def guide_label(bundle_name: str) -> str:
    """Human-readable guide type: everything after the version segment."""
    # IFM underscore-version FIRST (more specific — must beat general dot-version regex)
    # e.g. Actimize_Fraud_IFM_11_2_SP1_Performance_Test_Summary_Report
    m = re.search(r"IFM_\d+_\d+_(.+)$", bundle_name)
    if m:
        return m.group(1).replace("_", " ")
    # IFM-X: take everything after IFM-X_
    m = re.search(r"IFM-X_(.+)$", bundle_name)
    if m:
        return m.group(1).replace("_", " ")
    # Standard dot-version: take everything after _X.Y_
    m = re.search(r"_\d+[\d.]*_(.+)$", bundle_name)
    if m:
        label = m.group(1).replace("_", " ")
        # Strip "- Internal Only" suffix common in IFM bundles
        label = re.sub(r"\s*-\s*Internal\s+Only\s*$", "", label, flags=re.IGNORECASE)
        return label.strip()
    # No version in name (e.g. XSE bundles): take last two underscore segments
    parts = bundle_name.replace("-", "_").split("_")
    return " ".join(parts[-2:])


def _type_from_labels(labels: list) -> str:
    """Extract doc type from Zoomin bundle labels using the native taxonomy.

    Looks for a label with subjectheadNavtitle == 'Type of Information' and
    maps its key to our DOC_TYPE_LABEL_KEYS table. Falls back to 'Product Documentation'.
    """
    for lbl in labels:
        if lbl.get("subjectheadNavtitle") == "Type of Information":
            return DOC_TYPE_LABEL_KEYS.get(lbl.get("key", ""), lbl.get("navtitle", "Product Documentation"))
    return "Product Documentation"


def fetch_bundle_type(session, bundle_name: str) -> str:
    """Fetch the doc type for a single bundle via GET /api/bundle/{name}.

    Used for config bundles not returned by label-key discovery queries.
    """
    try:
        resp = session.get(f"{BASE_API}/bundle/{bundle_name}", timeout=20)
        resp.raise_for_status()
        return _type_from_labels(resp.json().get("bundle", {}).get("labels", []))
    except Exception:
        return "Product Documentation"


def discover_bundles(session, label_keys: list[str]) -> list[dict]:
    """Query the Zoomin API for all bundles matching the given label keys.

    Doc type is extracted natively from each bundle's 'Type of Information'
    label — no pattern matching needed.

    Returns deduplicated list of {name, doc_type, updated}, newest first.
    """
    seen: set[str] = set()
    results: list[dict] = []

    for label in label_keys:
        page = 0
        while True:
            url = f"{BASE_API}/bundlelist?labelkey={label}&per_page=50&page={page}"
            try:
                # Accept-Encoding: identity avoids a server-side bug where the
                # /bundlelist endpoint sends Content-Encoding: gzip with a
                # non-gzip body, causing requests to throw ContentDecodingError.
                data = session.get(url, timeout=30, headers={"Accept-Encoding": "identity"}).json()
            except Exception:
                break
            batch = data.get("bundle_list", [])
            for b in batch:
                if b["name"] not in seen:
                    seen.add(b["name"])
                    results.append({
                        "name": b["name"],
                        "doc_type": _type_from_labels(b.get("labels", [])),
                        "updated": (b.get("dates") or {}).get("Updated on", "")[:10],
                    })
            if len(batch) < 50:
                break
            page += 1
        time.sleep(0.2)

    results.sort(key=lambda x: x["updated"], reverse=True)
    return results


def is_locally_extracted(output_dir: str, bundle_name: str) -> bool:
    """Return True if the bundle has been extracted under raw_docs/.

    Primary layout is bundle-centric (raw_docs/bundles/{bundle}); legacy
    product-first layouts (versioned, direct, doc-type subfolder) are still
    honored so pre-reflow corpora keep resolving.
    """
    # Bundle-centric store (current layout): product-agnostic, one copy per bundle.
    if (RAW_DOCS_DIR / "bundles" / bundle_name).is_dir():
        return True

    product_dir = RAW_DOCS_DIR / output_dir
    version = extract_version(bundle_name)
    if version != "-":
        if (product_dir / f"v{version}" / bundle_name).is_dir():
            return True
    if (product_dir / bundle_name).is_dir():
        return True
    if product_dir.is_dir():
        for child in product_dir.iterdir():
            if child.is_dir() and (child / bundle_name).is_dir():
                return True
    return False


def count_toc_pages(entries: list) -> int:
    n = 0
    for e in entries:
        if e.get("nav_path"):
            n += 1
        n += count_toc_pages(e.get("childEntries", []))
    return n


def fetch_page_count(session, bundle_name: str) -> str:
    try:
        resp = session.get(f"{BASE_API}/bundle/{bundle_name}/toc?language=enus", timeout=30)
        resp.raise_for_status()
        return str(count_toc_pages(resp.json()))
    except Exception:
        return "?"


# ── SharePoint helpers ─────────────────────────────────────────────────────────

def load_sp_session():
    """Load a requests.Session with SharePoint auth cookies (FedAuth + rtFa)."""
    try:
        import requests
    except ImportError:
        rprint("[red]Missing dependency:[/red] pip install requests")
        raise typer.Exit(1)

    if not SP_COOKIES_FILE.exists():
        rprint("[red]SharePoint session not found.[/red]")
        rprint("Run: [bold]docenter auth sharepoint login[/bold]")
        raise typer.Exit(1)

    data = json.loads(SP_COOKIES_FILE.read_text(encoding="utf-8"))
    all_cookies = {c["name"]: c["value"] for c in data.get("data", {}).get("cookies", [])}
    fed = all_cookies.get("FedAuth")
    rtfa = all_cookies.get("rtFa")
    if not fed or not rtfa:
        rprint("[red]SharePoint cookies missing FedAuth or rtFa.[/red]")
        rprint("Run: [bold]docenter auth sharepoint login[/bold]")
        raise typer.Exit(1)

    session = requests.Session()
    session.cookies.update({"FedAuth": fed, "rtFa": rtfa})
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    return session


def sp_get_digest(session) -> str:
    """Fetch SharePoint form digest (required for write operations, ~30 min TTL)."""
    resp = session.post(
        f"{SP_SITE_URL}/_api/contextinfo",
        headers={"Accept": "application/json;odata=verbose"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["d"]["GetContextWebInformation"]["FormDigestValue"]


def sp_ensure_folder(session, digest: str, server_rel_path: str):
    """Create a SharePoint folder (no-op if it already exists)."""
    session.post(
        f"{SP_SITE_URL}/_api/web/folders",
        headers={
            "Accept": "application/json;odata=verbose",
            "Content-Type": "application/json;odata=verbose",
            "X-RequestDigest": digest,
        },
        json={"__metadata": {"type": "SP.Folder"}, "ServerRelativeUrl": server_rel_path},
        timeout=30,
    )


def sp_upload_file(session, digest: str, folder_server_rel: str, filename: str, content: bytes) -> bool:
    """Upload one file to SharePoint via REST API. Returns True on success."""
    url = (
        f"{SP_SITE_URL}/_api/web/GetFolderByServerRelativeUrl"
        f"('{folder_server_rel}')"
        f"/Files/add(overwrite=true,url='{filename}')"
    )
    resp = session.post(
        url,
        headers={"Accept": "application/json;odata=verbose", "X-RequestDigest": digest},
        data=content,
        timeout=60,
    )
    return resp.status_code in (200, 201)


# ── CLI app ────────────────────────────────────────────────────────────────────

app = typer.Typer(
    name="docenter",
    help="Browse and download NICE Actimize documentation.",
    no_args_is_help=True,
)
console = Console()

# ── Auth commands ──────────────────────────────────────────────────────────────

auth_app = typer.Typer(help="Manage authentication with the Zoomin doc portal.")
app.add_typer(auth_app, name="auth")


@auth_app.command("login")
def auth_login(
    creds: bool = typer.Option(
        False, "--creds", help="Auto-fill login form using DOCENTER_EMAIL / DOCENTER_PASSWORD from .env"
    ),
    url: str = typer.Option(
        "", "--url", "-u",
        help="Override portal URL (e.g. the alternate niceactimize.zoominsoftware.io site)",
    ),
    http: bool = typer.Option(
        False, "--http",
        help="Log in via the browser-free HTTP API using DOCENTER_EMAIL / DOCENTER_PASSWORD (no Playwright).",
    ),
):
    """Login to the Zoomin doc portal via browser SSO (default).

    Opens a browser window — complete your Microsoft/NICE SSO login interactively.
    The CLI captures your session automatically when done.

    Use --creds to auto-fill the login form from .env instead of SSO.
    Use --http for a browser-free login from .env (fastest; password accounts only).
    Use --url to target the alternate Zoomin URL.
    """
    target_url = url or PORTAL_URL
    is_alt = bool(url and url != PORTAL_URL)

    if http:
        if not DOCENTER_EMAIL or not DOCENTER_PASSWORD:
            rprint("[red]Credentials not found in .env.[/red]")
            rprint("Set DOCENTER_EMAIL and DOCENTER_PASSWORD in your .env file, then retry.")
            raise typer.Exit(1)
        try:
            http_login(DOCENTER_EMAIL, DOCENTER_PASSWORD)
        except Exception as exc:  # noqa: BLE001
            rprint(f"[red]HTTP login failed:[/red] {exc}")
            raise typer.Exit(1)
        rprint("[green]Authenticated (HTTP, no browser).[/green]")
        _auth_status(COOKIES_FILE, "_SESSION", "Zoomin")
        return

    if creds:
        if not DOCENTER_EMAIL or not (DOCENTER_ZOOMIN_ALT_PASSWORD if is_alt else DOCENTER_PASSWORD):
            rprint("[red]Credentials not found in .env.[/red]")
            rprint("Set DOCENTER_EMAIL and DOCENTER_PASSWORD in your .env file, then retry.")
            raise typer.Exit(1)
        email = DOCENTER_EMAIL
        password = DOCENTER_ZOOMIN_ALT_PASSWORD if is_alt else DOCENTER_PASSWORD
    else:
        email = password = ""  # SSO — no auto-fill

    _browser_login(
        site_url=target_url,
        detect_cookie="_SESSION",
        cookies_file=COOKIES_FILE,
        label="Zoomin",
        email=email,
        password=password,
        force_sso=not creds,
    )


@auth_app.command("status")
def auth_status():
    """Show current Zoomin authentication status and session expiry."""
    _auth_status(COOKIES_FILE, "_SESSION", "Zoomin")


@auth_app.command("logout")
def auth_logout():
    """Remove saved Zoomin session cookies."""
    if not COOKIES_FILE.exists():
        rprint("[dim]Not logged in (no cookie file found).[/dim]")
        return
    COOKIES_FILE.unlink()
    rprint("[green]Logged out.[/green] Session cookie removed.")


# ── SharePoint auth sub-commands ───────────────────────────────────────────────

sp_auth_app = typer.Typer(help="Manage authentication with SharePoint.")
auth_app.add_typer(sp_auth_app, name="sharepoint")


def _launch_browser(p):
    """Launch browser: prefers Edge (pre-installed on Windows), then Chrome, then Chromium."""
    for channel in ("msedge", "chrome", None):
        try:
            kwargs: dict = {"headless": False}
            if channel:
                kwargs["channel"] = channel
            return p.chromium.launch(**kwargs)
        except Exception:
            continue
    # Last resort: auto-install Playwright Chromium
    rprint("[yellow]No browser found — installing Playwright Chromium...[/yellow]")
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    return p.chromium.launch(headless=False)


def _fill_login_form(page, email: str, password: str) -> bool:
    """Auto-fill an email+password login form. Returns True if form was found and submitted."""
    page.wait_for_load_state("domcontentloaded")

    # Some portals show a "Sign In" link before the actual form
    for text in ("Sign In", "Log In", "Login"):
        link = page.get_by_role("link", name=text, exact=True)
        if link.count() > 0:
            link.first.click()
            page.wait_for_load_state("domcontentloaded")
            break

    # Locate email input
    email_sel = (
        'input[type="email"], input[name="email"], input[name="username"], '
        'input[id*="email" i], input[placeholder*="email" i], input[placeholder*="user" i]'
    )
    try:
        page.wait_for_selector(email_sel, timeout=12000)
    except Exception:
        return False  # no login form found — caller falls back to manual SSO

    page.locator(email_sel).first.fill(email)

    # Handle two-step forms (email → Next → password)
    for next_text in ("Next", "Continue"):
        btn = page.get_by_role("button", name=next_text, exact=False)
        if btn.count() > 0:
            btn.first.click()
            page.wait_for_timeout(1500)
            break

    # Fill password
    try:
        page.wait_for_selector('input[type="password"]', timeout=10000)
        page.locator('input[type="password"]').first.fill(password)
    except Exception:
        return False

    # Submit
    page.locator('button[type="submit"], input[type="submit"]').first.click()
    return True


def cookies_to_payload(all_cookies: list) -> dict:
    """Convert a Playwright cookie list into the ``{"data": {"cookies": [...]}}``
    payload that ``load_session`` / ``build_session_from_cookies`` consume.

    Shared by ``_save_cookies`` (writes to a file) and the login broker (writes to
    the per-user store) so both produce byte-identical cookie payloads (avoids the
    capture-format drift D1)."""
    return {
        "data": {
            "cookies": [
                {
                    "name": c["name"],
                    "value": c["value"],
                    "domain": c["domain"],
                    "path": c.get("path", "/"),
                    "expires": c.get("expires", -1),
                    "httpOnly": c.get("httpOnly", False),
                    "secure": c.get("secure", False),
                }
                for c in all_cookies
            ]
        }
    }


def zoomin_login_complete(cookies: list):
    """Return the ``_SESSION`` cookie dict when a Zoomin login has completed, else None.

    The single source of truth for the DOCenter login success signal:
    ``ZD__userAuthenticated == "true"`` AND a ``_SESSION`` cookie is present. The
    login page sets ``_SESSION`` immediately (pre-auth), so ``_SESSION`` alone is a
    false positive — ``ZD__userAuthenticated`` flips to ``"true"`` only after the
    full SSO/password flow succeeds. Reused by ``_browser_login`` and the broker."""
    session_cookie = next((c for c in cookies if c["name"] == "_SESSION"), None)
    auth_cookie = next((c for c in cookies if c["name"] == "ZD__userAuthenticated"), None)
    if auth_cookie and str(auth_cookie.get("value", "")).lower() == "true" and session_cookie:
        return session_cookie
    return None


def _save_cookies(cookies_file: Path, all_cookies: list):
    """Persist Playwright cookies in the format load_session() / load_sp_session() expect."""
    cookies_file.parent.mkdir(parents=True, exist_ok=True)
    cookies_file.write_text(
        json.dumps(cookies_to_payload(all_cookies), indent=2), encoding="utf-8"
    )


def _browser_login(
    site_url: str,
    detect_cookie: str,
    cookies_file: Path,
    label: str,
    email: str = "",
    password: str = "",
    force_sso: bool = False,
):
    """
    Browser-based login flow supporting both SSO and credential auto-fill.

    If email+password are provided and force_sso is False, the CLI attempts to
    fill the login form automatically. Falls back to waiting for manual SSO if
    the form cannot be found.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        rprint("[red]Missing dependency:[/red] pip install playwright")
        raise typer.Exit(1)

    use_creds = bool(email and password and not force_sso)

    if use_creds:
        rprint(f"\n[bold]Logging in to {label} with saved credentials...[/bold]")
        rprint(f"[dim]Email: {email}[/dim]\n")
    else:
        rprint(f"\n[bold]Opening browser for {label} SSO login...[/bold]")
        rprint("[dim]Complete your login in the browser. The CLI captures your session automatically.[/dim]\n")

    with sync_playwright() as p:
        # Use a persistent context so the full SSO cookie chain is preserved
        # across redirects (Microsoft → Zoomin SSO → portal).
        user_data_dir = str(cookies_file.parent / "playwright-data")
        context = None
        for channel in ("msedge", "chrome", None):
            try:
                kwargs: dict = {"headless": False, "user_data_dir": user_data_dir}
                if channel:
                    kwargs["channel"] = channel
                context = p.chromium.launch_persistent_context(**kwargs)
                break
            except Exception:
                continue
        if context is None:
            rprint("[yellow]No browser found — installing Playwright Chromium...[/yellow]")
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            context = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir, headless=False
            )

        page = context.new_page()
        rprint(f"[cyan]Navigating to {site_url}...[/cyan]")
        page.goto(site_url, timeout=30000)

        if use_creds:
            filled = _fill_login_form(page, email, password)
            if not filled:
                rprint("[yellow]Login form not found — waiting for manual SSO instead.[/yellow]")
                rprint("[dim]Please complete login in the browser window...[/dim]")

        else:
            rprint("[dim]Waiting for authentication (timeout: 5 minutes)...[/dim]")

        # Poll for successful authentication (up to 5 min).
        # Success indicators: _SESSION cookie exists AND ZD__userAuthenticated = "true".
        # The login page sets _SESSION immediately (pre-auth), so checking only
        # for that cookie gives false positives. ZD__userAuthenticated is set to
        # "true" only after the SSO flow completes successfully.
        deadline = time.time() + 300
        found = None
        while time.time() < deadline:
            cookies = context.cookies()
            # Zoomin portal: require ZD__userAuthenticated == "true" AND _SESSION
            # (shared success signal — see zoomin_login_complete).
            if detect_cookie == "_SESSION":
                found = zoomin_login_complete(cookies)
                if found:
                    break
            else:
                # Fallback for other services (SharePoint etc.) that don't use
                # ZD__userAuthenticated.
                session_cookie = next((c for c in cookies if c["name"] == detect_cookie), None)
                if session_cookie and "/auth/login" not in page.url:
                    found = session_cookie
                    break
            time.sleep(2)

        if not found:
            context.close()
            rprint("[red]Authentication timed out (5 minutes). Please try again.[/red]")
            raise typer.Exit(1)

        all_cookies = context.cookies()
        context.close()

    _save_cookies(cookies_file, all_cookies)

    expires_ts = found.get("expires", -1)
    if expires_ts and expires_ts > 0:
        expiry = datetime.datetime.fromtimestamp(expires_ts)
        days_left = (expiry - datetime.datetime.now()).days
        rprint(f"[green]Authenticated![/green] Session valid until {expiry.strftime('%Y-%m-%d')} ({days_left} days).")
    else:
        rprint("[green]Authenticated![/green] Session cookie saved.")
    rprint(f"[dim]Cookies saved to {cookies_file}[/dim]")


def _auth_status(cookies_file: Path, primary_cookie: str, label: str):
    """Shared status display for any service's cookie file."""
    if not cookies_file.exists():
        rprint(f"[yellow]Not logged in to {label}.[/yellow]")
        raise typer.Exit(1)

    try:
        data = json.loads(cookies_file.read_text(encoding="utf-8"))
        cookies = data["data"]["cookies"]
    except Exception as e:
        rprint(f"[red]Failed to read cookie file:[/red] {e}")
        raise typer.Exit(1)

    found = next((c for c in cookies if c["name"] == primary_cookie), None)
    if not found:
        rprint(f"[red]Cookie file has no {primary_cookie} token.[/red]")
        raise typer.Exit(1)

    expires_ts = found.get("expires", -1)
    if expires_ts and expires_ts > 0:
        expiry = datetime.datetime.fromtimestamp(expires_ts)
        now = datetime.datetime.now()
        if expiry < now:
            rprint(f"[red]{label} session expired[/red] on {expiry.strftime('%Y-%m-%d')}.")
            rprint(f"[dim]Cookie file: {cookies_file}[/dim]")
            raise typer.Exit(1)
        else:
            days_left = (expiry - now).days
            color = "green" if days_left > 3 else "yellow"
            rprint(f"[{color}]Cookie valid ({label})[/{color}] — expires {expiry.strftime('%Y-%m-%d')} ({days_left} days).")
    else:
        mtime = datetime.datetime.fromtimestamp(cookies_file.stat().st_mtime)
        rprint(f"[dim]Cookie saved {mtime.strftime('%Y-%m-%d')} — no explicit expiry.[/dim]")

    # Live probe: for Zoomin, check the ZD__userAuthenticated cookie value.
    # This cookie is set to "true" only after a successful SSO — it's the most
    # reliable indicator without needing a working API endpoint to probe.
    if label == "Zoomin":
        auth_val = next(
            (c.get("value", "") for c in cookies if c["name"] == "ZD__userAuthenticated"),
            None,
        )
        if auth_val is None:
            rprint("[yellow]ZD__userAuthenticated cookie not found — re-run auth login.[/yellow]")
            rprint("[yellow]Run:[/yellow] [bold]docenter auth login[/bold]")
            raise typer.Exit(1)
        elif str(auth_val).lower() != "true":
            rprint(f"[red]Session not authenticated (ZD__userAuthenticated={auth_val!r}).[/red]")
            rprint("[yellow]Run:[/yellow] [bold]docenter auth login[/bold]")
            raise typer.Exit(1)
        else:
            rprint(f"[green]Authenticated ({label})[/green] — ZD__userAuthenticated=true.")

    rprint(f"[dim]Cookie file: {cookies_file}[/dim]")


@sp_auth_app.command("login")
def sp_auth_login():
    """Open a browser for SharePoint SSO login and save session cookies."""
    _browser_login(SP_SITE_URL, "FedAuth", SP_COOKIES_FILE, "SharePoint")


@sp_auth_app.command("status")
def sp_auth_status():
    """Show current SharePoint authentication status."""
    _auth_status(SP_COOKIES_FILE, "FedAuth", "SharePoint")


@sp_auth_app.command("logout")
def sp_auth_logout():
    """Remove saved SharePoint session cookies."""
    if not SP_COOKIES_FILE.exists():
        rprint("[dim]Not logged in to SharePoint (no cookie file found).[/dim]")
        return
    SP_COOKIES_FILE.unlink()
    rprint("[green]Logged out of SharePoint.[/green] Session cookie removed.")


# ── SharePoint upload command ──────────────────────────────────────────────────

sp_app = typer.Typer(help="Upload documents to SharePoint.")
app.add_typer(sp_app, name="sharepoint")


# ── Catalog commands ──────────────────────────────────────────────────────────

# Catalog build/render logic lives in dedicated modules so the package stays
# modular and matches the distributable layout.
from docenter import catalog_builder, catalog_renderer


catalog_app = typer.Typer(help="Manage the local docs/catalog.yaml product catalog.")
app.add_typer(catalog_app, name="catalog")


@catalog_app.command("refresh")
def catalog_refresh(
    skip_md: bool = typer.Option(False, "--skip-md", help="Skip regenerating docs/catalog.md"),
):
    """Rebuild docs/catalog.yaml from the live Zoomin API.

    Walks /api/categories + /api/taxonomy, then calls /api/bundlelist for every
    label key in the expanded set. Takes 10-20 min on a full portal pass.
    Requires a valid session — run [bold]docenter auth login[/bold] first.

    After the YAML is regenerated, the rendered docs/catalog.md is rebuilt
    unless --skip-md is given.
    """
    rprint("[bold]Refreshing docs/catalog.yaml — this hits ~600-800 API endpoints, expect 10-20 min.[/bold]\n")
    try:
        catalog_builder.build_catalog()
    except Exception as e:
        rprint(f"\n[red]Discovery failed:[/red] {e}")
        raise typer.Exit(1)

    if not skip_md:
        try:
            catalog_renderer.render_catalog_md()
        except Exception as e:
            rprint(f"\n[yellow]YAML written but MD rendering failed:[/yellow] {e}")
            raise typer.Exit(1)

    rprint("\n[green]Catalog refreshed.[/green] Re-run any list-docs or download command to pick up new bundles.")

    # In a source checkout, keep the shipped package-data copy in sync with the
    # source catalog so internal wheel builds aren't stale. Skipped on public/pip
    # installs (Option-A builds ship no catalog and CATALOG_FILE is user-writable).
    if CATALOG_FILE == REPO_ROOT / "docs" / "catalog.yaml":
        try:
            import shutil
            pkg_copy = PKG_DIR / "data" / "catalog.yaml"
            if CATALOG_FILE.exists() and CATALOG_FILE.resolve() != pkg_copy.resolve():
                pkg_copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(CATALOG_FILE, pkg_copy)
        except Exception:
            pass


@catalog_app.command("status")
def catalog_status():
    """Show local catalog metadata: when it was last refreshed and totals."""
    if not CATALOG_FILE.exists():
        rprint(f"[yellow]No catalog file at[/yellow] {CATALOG_FILE}")
        rprint("Run: [bold]docenter catalog refresh[/bold]")
        raise typer.Exit(1)

    try:
        import yaml
        with CATALOG_FILE.open(encoding="utf-8") as f:
            catalog = yaml.safe_load(f) or {}
    except Exception as e:
        rprint(f"[red]Failed to read catalog:[/red] {e}")
        raise typer.Exit(1)

    gen = (catalog.get("generated_at") or "")[:19] or "(unknown)"
    totals = catalog.get("totals") or {}
    rprint(f"[bold]Catalog file:[/bold] {CATALOG_FILE}")
    rprint(f"[bold]Generated:[/bold]    {gen}")
    rprint(f"[bold]Categories:[/bold]   {totals.get('categories', 0)}")
    rprint(f"[bold]Products:[/bold]     {totals.get('products', 0)}")
    rprint(f"[bold]Bundles:[/bold]      {totals.get('bundles', 0)} listings")


# ── Skill maintenance commands ────────────────────────────────────────────────

skill_app = typer.Typer(help="Maintain the actimize-docenter AI skill file.")
app.add_typer(skill_app, name="skill")

# Path to the AI skill in a source checkout. Absent on pip/wheel installs.
SKILL_REFERENCE_FILE = REPO_ROOT / "skills" / "actimize-docenter" / "SKILL.md"

# The curated keys shown in the skill's "Product Keys Reference" table — the
# commonly-used products. Names/versions are regenerated from the catalog so the
# table never drifts. Order mirrors the existing table.
FEATURED_SKILL_KEYS: list[str] = [
    "actone", "sam", "cdd", "ifm", "xse-sam", "xse-cdd", "xse-fraud",
]

PRODUCT_KEYS_BEGIN = (
    "<!-- BEGIN GENERATED: product-keys "
    "(run `docenter skill sync-reference` to refresh from catalog.yaml) -->"
)
PRODUCT_KEYS_END = "<!-- END GENERATED: product-keys -->"


def _latest_version_line(versions) -> list[str]:
    """Return the versions belonging to the highest major-version line, ascending.

    e.g. {6.0, 10.0, 10.1, 10.2, -} -> ['10.0', '10.1', '10.2']. Non-numeric
    sentinels ('-', 'X') are dropped. Empty when no numeric version is present."""
    parsed: list[tuple[tuple, str]] = []
    for v in versions:
        if not v or v in {"-", "X"}:
            continue
        try:
            key = tuple(int(x) for x in str(v).split("."))
        except ValueError:
            continue
        parsed.append((key, str(v)))
    if not parsed:
        return []
    max_major = max(k[0] for k, _ in parsed)
    line = sorted((p for p in parsed if p[0][0] == max_major), key=lambda p: p[0])
    out: list[str] = []
    for _, v in line:
        if v not in out:
            out.append(v)
    return out


def _featured_skill_rows() -> list[tuple[str, str, str]]:
    """Build (key, product name, versions) rows for the skill reference table,
    pulling current names and the latest version line from the catalog."""
    rows: list[tuple[str, str, str]] = []
    for key in FEATURED_SKILL_KEYS:
        cfg = PRODUCTS.get(key)
        if not cfg:
            continue
        versions = _latest_version_line(
            {extract_version(b) for b in cfg.get("bundles", [])}
        )
        rows.append((key, cfg.get("name", key), ", ".join(versions) if versions else "-"))
    return rows


def _render_product_keys_table(rows: list[tuple[str, str, str]]) -> str:
    """Render rows as an aligned GitHub-flavoured Markdown table."""
    headers = ("Key", "Product", "Versions")
    all_rows = [headers, *rows]
    widths = [max(len(str(r[i])) for r in all_rows) for i in range(3)]

    def _fmt(r) -> str:
        return "| " + " | ".join(str(r[i]).ljust(widths[i]) for i in range(3)) + " |"

    sep = "|" + "|".join("-" * (widths[i] + 2) for i in range(3)) + "|"
    return "\n".join([_fmt(headers), sep, *[_fmt(r) for r in rows]])


@skill_app.command("sync-reference")
def skill_sync_reference(
    check: bool = typer.Option(
        False, "--check",
        help="Exit non-zero if the skill table is out of date (no write). For CI.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print the regenerated table without writing.",
    ),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable output."),
):
    """Regenerate the Product Keys Reference table in the actimize-docenter skill
    from the live catalog, so product names and versions never go stale.

    Updates only the block between the generated-section markers in SKILL.md.
    """
    if not _ensure_catalog(json_out=json_out):
        if json_out:
            print(json.dumps({"error": "no_catalog", "message": "Run: docenter auth login then docenter catalog refresh"}, indent=2))
            raise typer.Exit(1)
        rprint("[red]No product catalog available.[/red]")
        rprint("Run [bold]docenter auth login[/bold] then [bold]docenter catalog refresh[/bold].")
        raise typer.Exit(1)

    if not SKILL_REFERENCE_FILE.exists():
        if json_out:
            print(json.dumps({"error": "no_skill_file", "message": f"Skill file not found: {SKILL_REFERENCE_FILE}"}, indent=2))
            raise typer.Exit(1)
        rprint(f"[red]Skill file not found:[/red] {SKILL_REFERENCE_FILE}")
        rprint("[dim]sync-reference only runs in a source checkout that ships skills/.[/dim]")
        raise typer.Exit(1)

    rows = _featured_skill_rows()
    if not rows:
        if json_out:
            print(json.dumps({"error": "no_rows", "message": "No featured products resolved from the catalog."}, indent=2))
            raise typer.Exit(1)
        rprint("[red]None of the featured product keys resolved from the catalog.[/red]")
        raise typer.Exit(1)

    table = _render_product_keys_table(rows)
    new_block = f"{PRODUCT_KEYS_BEGIN}\n{table}\n{PRODUCT_KEYS_END}"

    text = SKILL_REFERENCE_FILE.read_text(encoding="utf-8")
    block_re = re.compile(
        re.escape("<!-- BEGIN GENERATED: product-keys") + r".*?-->.*?"
        + re.escape(PRODUCT_KEYS_END),
        re.DOTALL,
    )
    if not block_re.search(text):
        if json_out:
            print(json.dumps({"error": "no_markers", "message": "Generated-section markers not found in SKILL.md."}, indent=2))
            raise typer.Exit(1)
        rprint("[red]Generated-section markers not found in[/red] " + str(SKILL_REFERENCE_FILE))
        rprint(f"[dim]Expected a block delimited by:[/dim]\n  {PRODUCT_KEYS_BEGIN}\n  {PRODUCT_KEYS_END}")
        raise typer.Exit(1)

    new_text = block_re.sub(lambda _m: new_block, text, count=1)
    changed = new_text != text

    if json_out:
        print(json.dumps({
            "changed": changed,
            "rows": [{"key": k, "name": n, "versions": v} for k, n, v in rows],
            "checked": check,
            "written": changed and not check and not dry_run,
        }, indent=2))
        if check and changed:
            raise typer.Exit(1)
        return

    if check:
        if changed:
            rprint("[yellow]Skill reference table is OUT OF DATE.[/yellow] Run [bold]docenter skill sync-reference[/bold].")
            raise typer.Exit(1)
        rprint("[green]Skill reference table is up to date.[/green]")
        return

    if dry_run:
        rprint("[dim]--dry-run: regenerated table (not written):[/dim]\n")
        print(table)
        rprint(f"\n[dim]{'Would update' if changed else 'No change to'} {SKILL_REFERENCE_FILE}[/dim]")
        return

    if not changed:
        rprint("[green]Skill reference table already up to date.[/green]")
        return

    SKILL_REFERENCE_FILE.write_text(new_text, encoding="utf-8")
    rprint(f"[green]Updated[/green] the Product Keys Reference table in {SKILL_REFERENCE_FILE} ({len(rows)} products).")


@sp_app.command("upload")
def sp_upload(
    product: str = typer.Argument(
        ..., help="Product slug or alias (run `list-products` to see all 90)"
    ),
    fmt: str = typer.Option("md", "--format", "-f", help="Format to upload: md or pdf"),
    version: Optional[str] = typer.Option(
        None, "--version", "-v", help="Limit to a specific version, e.g. 10.1"
    ),
    dest: str = typer.Option(
        SP_DEFAULT_FOLDER, "--dest", "-d",
        help="Destination folder path within the SharePoint site",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="List files without uploading"),
):
    """Upload extracted docs to SharePoint.

    Requires: docenter auth sharepoint login

    Examples:
      docenter sharepoint upload actone --version 10.1
      docenter sharepoint upload actone --format pdf --dest "Shared Documents/ActWise/pdfs"
    """
    product = _require_product(product)

    if fmt not in ("md", "pdf"):
        rprint(f"[red]Invalid format:[/red] '{fmt}'. Use md or pdf.")
        raise typer.Exit(1)

    cfg = PRODUCTS[product]
    out_dir = cfg.get("output_dir", product)

    # Collect files to upload
    if fmt == "md":
        search_root = RAW_DOCS_DIR / out_dir
        if version:
            search_root = search_root / f"v{version}"
        if not search_root.exists():
            rprint(f"[red]No local files found:[/red] {search_root}")
            rprint("Run [bold]docenter download[/bold] first to extract docs.")
            raise typer.Exit(1)
        files = sorted(search_root.rglob("*.md"))
    else:  # pdf
        search_root = RAW_DOCS_DIR / "pdfs" / out_dir
        if version:
            search_root = search_root / f"v{version}"
        if not search_root.exists():
            rprint(f"[red]No local PDFs found:[/red] {search_root}")
            rprint("Run [bold]docenter download --format pdf[/bold] first.")
            raise typer.Exit(1)
        files = sorted(search_root.rglob("*.pdf"))

    if not files:
        rprint(f"[red]No {fmt.upper()} files found[/red] under {search_root}")
        raise typer.Exit(1)

    rprint(f"\n[bold]SharePoint upload plan:[/bold]")
    rprint(f"  Site:   {SP_SITE_URL}")
    rprint(f"  Dest:   {dest}")
    rprint(f"  Files:  {len(files)} {fmt.upper()} file(s)")
    if version:
        rprint(f"  Filter: v{version}")

    if dry_run:
        rprint()
        for f in files[:15]:
            rprint(f"  [dim]{f.relative_to(search_root.parent if version else RAW_DOCS_DIR / out_dir)}[/dim]")
        if len(files) > 15:
            rprint(f"  [dim]... and {len(files) - 15} more[/dim]")
        rprint("\n[yellow]Dry run — no files uploaded.[/yellow]")
        return

    session = load_sp_session()

    rprint("\n[dim]Fetching SharePoint request digest...[/dim]")
    try:
        digest = sp_get_digest(session)
    except Exception as e:
        rprint(f"[red]Could not connect to SharePoint:[/red] {e}")
        rprint("Your SharePoint session may have expired. Run [bold]docenter auth sharepoint login[/bold]")
        raise typer.Exit(1)

    created_folders: set[str] = set()
    success = errors = 0
    digest_refresh_counter = 0

    rprint(f"\n[bold]Uploading {len(files)} file(s)...[/bold]\n")

    for i, file_path in enumerate(files, 1):
        # Build SharePoint server-relative folder path
        rel = file_path.relative_to(RAW_DOCS_DIR / out_dir)
        sub_parts = rel.parts[:-1]  # everything except the filename
        sp_folder = dest + ("/" + "/".join(sub_parts) if sub_parts else "")
        sp_folder_rel = f"{_SP_SITE_PATH}/{sp_folder}"
        filename = file_path.name

        # Create folder once
        if sp_folder_rel not in created_folders:
            sp_ensure_folder(session, digest, sp_folder_rel)
            created_folders.add(sp_folder_rel)

        try:
            ok = sp_upload_file(session, digest, sp_folder_rel, filename, file_path.read_bytes())
            if ok:
                success += 1
            else:
                errors += 1
                rprint(f"  [red]FAIL[/red] {rel}")
        except Exception as e:
            errors += 1
            rprint(f"  [red]ERROR[/red] {rel}: {e}")

        # Progress every 50 files
        if i % 50 == 0:
            rprint(f"  [dim]{i}/{len(files)} processed ({errors} errors)[/dim]")
        # Refresh digest every 400 files (~30 min TTL)
        digest_refresh_counter += 1
        if digest_refresh_counter >= 400:
            digest = sp_get_digest(session)
            digest_refresh_counter = 0

        time.sleep(0.15)

    console.print()
    if errors:
        rprint(f"[yellow]Done:[/yellow] {success} uploaded, [red]{errors} failed[/red].")
    else:
        rprint(f"[green]Done:[/green] {success} file(s) uploaded successfully.")
    rprint(f"[dim]View at: {SP_SITE_URL}/{dest.replace('Shared Documents', 'Shared%%20Documents')}[/dim]")


# ── Doc commands ───────────────────────────────────────────────────────────────


@app.command("list-categories")
def list_categories(
    json_out: bool = typer.Option(False, "--json", help="Output machine-readable JSON instead of a table"),
):
    """List all product categories from the local catalog, with product/bundle counts.

    Examples:
      docenter list-categories
      docenter list-categories --json
    """
    if not _ensure_catalog(json_out=json_out):
        if json_out:
            print(json.dumps({"error": "no_catalog", "message": "No product catalog. Run: docenter auth login then docenter catalog refresh"}, indent=2))
            raise typer.Exit(1)
        rprint("[red]No product catalog available.[/red]")
        rprint("Run [bold]docenter auth login[/bold] then [bold]docenter catalog refresh[/bold].")
        raise typer.Exit(1)

    # Aggregate by category_id, preserving order of first appearance.
    cats: dict[str, dict] = {}
    for slug, cfg in PRODUCTS.items():
        cat_id = cfg.get("category_id") or "_"
        entry = cats.setdefault(cat_id, {
            "category_id": cat_id,
            "category": cfg.get("category") or cat_id,
            "product_count": 0,
            "bundle_count": 0,
            "local_products": 0,
        })
        entry["product_count"] += 1
        entry["bundle_count"] += len(cfg.get("bundles", []))
        out_dir = cfg.get("output_dir", slug)
        any_local = (RAW_DOCS_DIR / out_dir).exists() and any((RAW_DOCS_DIR / out_dir).iterdir())
        if any_local:
            entry["local_products"] += 1

    if json_out:
        print(json.dumps({"categories": list(cats.values())}, indent=2))
        return

    console.print()
    table = Table(
        title=f"Documentation Categories  ({len(cats)} total)",
        show_lines=False,
        header_style="bold magenta",
        title_justify="left",
    )
    table.add_column("ID", style="bold cyan", no_wrap=True)
    table.add_column("Category", style="white")
    table.add_column("Products", justify="right", style="green")
    table.add_column("Bundles", justify="right", style="yellow")
    table.add_column("Local", justify="right")

    total_products = total_bundles = 0
    for entry in cats.values():
        local_txt = (
            f"[green]{entry['local_products']}[/green]" if entry["local_products"] else "[dim]-[/dim]"
        )
        table.add_row(
            entry["category_id"], entry["category"],
            str(entry["product_count"]), str(entry["bundle_count"]), local_txt,
        )
        total_products += entry["product_count"]
        total_bundles += entry["bundle_count"]

    console.print(table)
    console.print()
    rprint(
        f"[dim]Total: {len(cats)} categories, {total_products} products, {total_bundles} bundle listings. "
        f"Run [bold]docenter list-products --category <id>[/bold] to drill into one category.[/dim]"
    )


@app.command("list-products")
def list_products(
    category: Optional[str] = typer.Option(
        None, "--category", "-c",
        help="Filter to one category (e.g. aml, plt, ifm, fmc, xsight). Run without to see all.",
    ),
    show_aliases: bool = typer.Option(
        False, "--aliases", help="Include the alias column",
    ),
    json_out: bool = typer.Option(False, "--json", help="Output machine-readable JSON instead of a table"),
):
    """List all products from the local catalog, grouped by category.

    Examples:
      docenter list-products
      docenter list-products --category aml
      docenter list-products --aliases
    """
    if not _ensure_catalog(json_out=json_out):
        if json_out:
            print(json.dumps({"error": "no_catalog", "message": "No product catalog. Run: docenter auth login then docenter catalog refresh"}, indent=2))
            raise typer.Exit(1)
        rprint("[red]No product catalog available.[/red]")
        rprint("Run [bold]docenter auth login[/bold] then [bold]docenter catalog refresh[/bold].")
        raise typer.Exit(1)

    # Group products by category_id, preserving order of first appearance
    by_category: dict[str, list[tuple[str, dict]]] = {}
    category_titles: dict[str, str] = {}
    for slug, cfg in PRODUCTS.items():
        cat_id = cfg.get("category_id") or "_"
        by_category.setdefault(cat_id, []).append((slug, cfg))
        category_titles.setdefault(cat_id, cfg.get("category") or cat_id)

    target_cats = [category] if category else list(by_category.keys())
    if category and category not in by_category:
        if json_out:
            print(json.dumps({
                "error": "unknown_category",
                "message": f"Unknown category: '{category}'",
                "valid": list(by_category.keys()),
            }, indent=2))
            raise typer.Exit(1)
        rprint(f"[red]Unknown category:[/red] '{category}'")
        rprint(f"Valid: {', '.join(by_category.keys())}")
        raise typer.Exit(1)

    if json_out:
        products_out = []
        for cat_id in target_cats:
            items = by_category.get(cat_id, [])
            cat_title = category_titles.get(cat_id, cat_id)
            for slug, cfg in items:
                n_bundles = len(cfg.get("bundles", []))
                out_dir = cfg.get("output_dir", slug)
                any_local = (RAW_DOCS_DIR / out_dir).exists() and any(
                    (RAW_DOCS_DIR / out_dir).iterdir()
                )
                products_out.append({
                    "key": slug,
                    "name": cfg.get("name", ""),
                    "category_id": cat_id,
                    "category": cat_title,
                    "aliases": cfg.get("aliases", []),
                    "bundle_count": n_bundles,
                    "local": any_local,
                })
        print(json.dumps({"products": products_out}, indent=2))
        return

    total_products = 0
    total_bundles = 0

    console.print()
    for cat_id in target_cats:
        items = by_category.get(cat_id, [])
        cat_title = category_titles.get(cat_id, cat_id)
        table = Table(
            title=f"{cat_title}  ({cat_id})  —  {len(items)} products",
            show_lines=False,
            header_style="bold magenta",
            title_justify="left",
        )
        table.add_column("Key", style="bold cyan", no_wrap=True)
        table.add_column("Product", style="white")
        if show_aliases:
            table.add_column("Aliases", style="dim")
        table.add_column("Bundles", justify="right", style="yellow")
        table.add_column("Local", justify="center")

        for slug, cfg in items:
            n_bundles = len(cfg.get("bundles", []))
            out_dir = cfg.get("output_dir", slug)
            any_local = (RAW_DOCS_DIR / out_dir).exists() and any(
                (RAW_DOCS_DIR / out_dir).iterdir()
            )
            local_icon = "[green]yes[/green]" if any_local else "[dim]-[/dim]"
            row = [slug, cfg.get("name", "")]
            if show_aliases:
                row.append(", ".join(cfg.get("aliases", [])) or "-")
            row.extend([str(n_bundles), local_icon])
            table.add_row(*row)

            total_products += 1
            total_bundles += n_bundles

        console.print(table)
        console.print()

    rprint(
        f"[dim]Total: {total_products} products, {total_bundles} bundle listings. "
        f"Run [bold]docenter list-docs <key>[/bold] to drill into one product.[/dim]"
    )


@app.command("list-docs")
def list_docs(
    product: str = typer.Argument(
        ..., help="Product slug or alias (e.g. actone, sam, cdd, ifm, xse-sam, svx, hba, surveil-x). Run `list-products` for all 90.",
    ),
    version: Optional[str] = typer.Option(
        None, "--version", "-v", help="Filter by version, e.g. 10.1"
    ),
    doc_type: Optional[str] = typer.Option(
        None, "--type", "-t",
        help="Filter by doc type (partial match): 'Product Info', 'Product Documentation', "
             "'Release Notes', 'Release Notifications', 'Patch Release Notes'",
    ),
    pages: bool = typer.Option(
        False, "--pages", "-p", help="Fetch live page count per bundle"
    ),
    no_discover: bool = typer.Option(
        False, "--no-discover", help="Skip live API discovery; show configured bundles only"
    ),
    json_out: bool = typer.Option(False, "--json", help="Output machine-readable JSON instead of a table"),
):
    """List doc bundles for a product, grouped by version and doc type.

    Queries the Zoomin API live to discover ALL bundles — including Product Info,
    Patch Release Notes, and Release Notifications not in the static config.

    Examples:
      docenter list-docs actone
      docenter list-docs actone --version 10.1
      docenter list-docs actone --type "Product Info"
      docenter list-docs actone --type "Patch"
      docenter list-docs actone --no-discover    (fast, config only)
    """
    if json_out:
        if not PRODUCTS:
            print(json.dumps({"error": "no_catalog", "message": "No product catalog loaded. Run: docenter catalog refresh"}, indent=2))
            raise typer.Exit(1)
        resolved = _resolve_product(product)
        if resolved is None:
            print(json.dumps({"error": "unknown_product", "message": f"Unknown product: '{product}'"}, indent=2))
            raise typer.Exit(1)
        product = resolved
    else:
        product = _require_product(product)

    cfg = PRODUCTS[product]
    label_keys: list[str] = cfg.get("label_keys", [])
    config_bundles: list[str] = cfg.get("bundles", [])
    exclude_prefixes: list[str] = cfg.get("discovery_exclude_prefixes", [])

    # ── Live discovery ────────────────────────────────────────────────────────
    # Doc type comes directly from each bundle's API labels — no pattern matching.
    session = None
    bundle_records: list[dict] = []
    config_set = set(config_bundles)

    if label_keys and not no_discover:
        try:
            session = load_session()
            if not json_out:
                rprint("[dim]Discovering bundles from API...[/dim]")
            bundle_records = discover_bundles(session, label_keys)
            # Remove bundles from other products that Zoomin cross-tags under this
            # product's label keys (e.g. SAM bundles appear under ActOne keys).
            if exclude_prefixes:
                bundle_records = [
                    r for r in bundle_records
                    if not any(r["name"].startswith(p) for p in exclude_prefixes)
                    or r["name"] in config_set
                ]
        except SystemExit:
            if not json_out:
                rprint("[yellow]No API session — showing configured bundles only. Run: docenter auth login[/yellow]\n")
        except Exception as e:
            if not json_out:
                rprint(f"[yellow]API discovery failed ({e}) — showing configured bundles only.[/yellow]\n")

    # Supplement with config bundles not returned by the label-key queries.
    # Prefer catalog metadata (no API calls); fall back to per-bundle fetch if needed.
    detail_map = {b["name"]: b for b in cfg.get("bundles_detail", []) if b.get("name")}
    discovered_names = {r["name"] for r in bundle_records}
    config_only = [b for b in config_bundles if b not in discovered_names]
    for b in config_only:
        info = detail_map.get(b) or {}
        bundle_type = info.get("doc_type") or (fetch_bundle_type(session, b) if session else "Product Documentation")
        bundle_records.append({
            "name": b,
            "doc_type": bundle_type,
            "updated": (info.get("updated") or "")[:10],
        })

    # ── Filters ───────────────────────────────────────────────────────────────
    if version:
        # Include bundles for the requested version AND version-agnostic bundles
        # (version == "-") since Product Info docs like the Compatibility Matrix
        # apply to all versions and should be visible regardless of --version filter.
        bundle_records = [
            r for r in bundle_records
            if extract_version(r["name"]) == version or extract_version(r["name"]) == "-"
        ]
        if not bundle_records:
            if json_out:
                print(json.dumps({"error": "no_bundles", "message": f"No bundles found for {product} version {version}"}, indent=2))
                raise typer.Exit(1)
            rprint(f"[red]No bundles found[/red] for {product} version {version}")
            raise typer.Exit(1)

    if doc_type:
        needle = doc_type.lower()
        bundle_records = [r for r in bundle_records if needle in r["doc_type"].lower()]
        if not bundle_records:
            if json_out:
                print(json.dumps({
                    "error": "no_bundles",
                    "message": f"No bundles found for type filter '{doc_type}'",
                    "valid_types": list(DOC_TYPES),
                }, indent=2))
                raise typer.Exit(1)
            valid_types = ", ".join(f'"{t}"' for t in DOC_TYPES)
            rprint(f"[red]No bundles found[/red] for type filter '{doc_type}'.")
            rprint(f"Valid types: {valid_types}")
            raise typer.Exit(1)

    # ── Page-count session ────────────────────────────────────────────────────
    if pages and session is None:
        try:
            session = load_session()
        except SystemExit:
            if not json_out:
                rprint("[yellow]No API session — skipping page counts.[/yellow]\n")
            pages = False

    # ── Group: version → doc_type → bundles ──────────────────────────────────
    # Sort versions newest first; within version sort by doc type order
    type_order = {t: i for i, t in enumerate(DOC_TYPES)}
    grouped: dict[str, list[dict]] = {}
    for r in bundle_records:
        grouped.setdefault(extract_version(r["name"]), []).append(r)
    for v in grouped:
        grouped[v].sort(key=lambda r: type_order.get(r["doc_type"], 99))

    n_discovered = sum(1 for r in bundle_records if r["name"] not in config_set)
    title = f"{cfg['name']} - Doc Bundles"
    if version:
        title += f"  (v{version})"
    if doc_type:
        title += f"  [{doc_type}]"
    if n_discovered and not no_discover:
        title += f"  [+{n_discovered} from API]"

    table = Table(title=title, show_lines=True, header_style="bold magenta")
    table.add_column("Version", style="bold green", no_wrap=True)
    table.add_column("Doc Type", style="magenta", no_wrap=True)
    table.add_column("Bundle Name", style="cyan")
    table.add_column("Guide", style="white")
    if pages:
        table.add_column("Pages", justify="right", style="yellow")
    table.add_column("Local", justify="center")

    out_dir = cfg.get("output_dir", product)

    def _version_sort_key(v: str) -> tuple:
        # Numeric sort: "10.2" > "10.1" > "X" > "-"
        if v == "-":
            return (0, 0, 0)
        if v == "X":
            return (1, 0, 0)
        parts = v.replace("_", ".").split(".")
        try:
            return tuple(int(x) for x in parts) + (0,) * (3 - len(parts))
        except ValueError:
            return (0, 0, 0)

    if json_out:
        versions_out = []
        for v in sorted(grouped, key=_version_sort_key, reverse=True):
            bundles_out = []
            for rec in grouped[v]:
                bname = rec["name"]
                bundle_obj = {
                    "name": bname,
                    "doc_type": rec["doc_type"],
                    "guide": guide_label(bname),
                    "version": v,
                    "local": is_locally_extracted(out_dir, bname),
                    "updated": rec.get("updated", ""),
                }
                if pages and session:
                    bundle_obj["pages"] = fetch_page_count(session, bname)
                bundles_out.append(bundle_obj)
            versions_out.append({"version": v, "bundles": bundles_out})
        print(json.dumps({
            "product": product,
            "name": cfg["name"],
            "versions": versions_out,
        }, indent=2))
        return

    for v in sorted(grouped, key=_version_sort_key, reverse=True):
        for rec in grouped[v]:
            bname = rec["name"]
            dtype = rec["doc_type"]
            glabel = guide_label(bname)
            local_icon = "[green]yes[/green]" if is_locally_extracted(out_dir, bname) else "[dim]-[/dim]"

            # Colour-code doc type
            type_colours = {
                "Product Info":          "bright_blue",
                "Product Documentation": "white",
                "Release Notes":         "green",
                "Release Notifications": "yellow",
                "Patch Release Notes":   "cyan",
            }
            colour = type_colours.get(dtype, "white")
            dtype_cell = f"[{colour}]{dtype}[/{colour}]"

            if pages and session:
                page_count = fetch_page_count(session, bname)
                table.add_row(v, dtype_cell, bname, glabel, page_count, local_icon)
            else:
                table.add_row(v, dtype_cell, bname, glabel, local_icon)

    console.print()
    console.print(table)
    console.print()
    hint = f"docenter download {product} --format md --version {version or '<version>'}"
    console.print(f"[dim]To download: [bold]{hint}[/bold][/dim]")
    console.print(f"[dim]Filter by type: [bold]docenter list-docs {product} --type \"Product Info\"[/bold][/dim]")


@app.command("download")
def download(
    product: str = typer.Argument(
        ..., help="Product slug or alias (run `list-products` to see all 90)"
    ),
    fmt: str = typer.Option(..., "--format", "-f", help="Format: md or pdf"),
    version: Optional[str] = typer.Option(
        None, "--version", "-v", help="Limit to a specific version, e.g. 10.1"
    ),
    bundle: Optional[str] = typer.Option(
        None, "--bundle", "-b", help="Limit to a specific bundle name (partial match)"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be downloaded without running"
    ),
):
    """Download doc bundles as Markdown or PDF.

    Delegates to extractor/extractor.py (md) or extractor/pdf_exporter.py (pdf).
    """
    product = _require_product(product)

    if fmt not in ("md", "pdf"):
        rprint(f"[red]Invalid format:[/red] '{fmt}'. Use [bold]md[/bold] or [bold]pdf[/bold].")
        raise typer.Exit(1)

    cfg = PRODUCTS[product]
    bundles: list[str] = list(cfg.get("bundles", []))

    if version:
        bundles = [b for b in bundles if version in b]
    if bundle:
        bundles = [b for b in bundles if bundle.lower() in b.lower()]

    if not bundles:
        rprint(
            f"[red]No matching bundles[/red] for product={product}"
            + (f", version={version}" if version else "")
            + (f", bundle filter='{bundle}'" if bundle else "")
        )
        raise typer.Exit(1)

    rprint(f"\n[bold]Download plan:[/bold] {len(bundles)} bundle(s) → [cyan]{fmt.upper()}[/cyan]\n")
    for b in bundles:
        rprint(f"  [dim]•[/dim] {b}")

    if dry_run:
        rprint("\n[yellow]Dry run — no files downloaded.[/yellow]")
        return

    extractor_script = _extractor_dir() / "extractor.py"
    pdf_script = _extractor_dir() / "pdf_exporter.py"

    doc_type_map = {bd["name"]: bd.get("doc_type", "") for bd in cfg.get("bundles_detail", [])}

    failed: list[str] = []
    for b in bundles:
        rprint(f"\n[bold cyan]>>[/bold cyan] {b}")
        if fmt == "md":
            cmd = [sys.executable, str(extractor_script), "--product", product, "--bundle", b]
            dt = doc_type_map.get(b, "")
            if dt:
                cmd += ["--doc-type", dt]
        else:
            cmd = [sys.executable, str(pdf_script), "--product", product, "--bundle", b]
            dt = doc_type_map.get(b, "")
            if dt:
                cmd += ["--doc-type", dt]

        result = subprocess.run(cmd, cwd=str(REPO_ROOT), env=_extractor_env())
        if result.returncode != 0:
            rprint(f"  [red]✗ Failed[/red] (exit {result.returncode})")
            failed.append(b)
        else:
            rprint(f"  [green]✓ Done[/green]")

    console.print()
    if failed:
        rprint(f"[red]{len(failed)} bundle(s) failed:[/red]")
        for b in failed:
            rprint(f"  • {b}")
        raise typer.Exit(1)
    else:
        rprint(f"[green]All {len(bundles)} bundle(s) downloaded successfully.[/green]")


SYNC_STATE_FILE = REPO_ROOT / "docs" / "sync-state.json"
SYNC_LOG_FILE = REPO_ROOT / "docs" / "sync-log.md"


def _load_sync_state() -> dict:
    if SYNC_STATE_FILE.exists():
        try:
            return json.loads(SYNC_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_sync": None, "bundles": {}}


def _save_sync_state(state: dict) -> None:
    SYNC_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SYNC_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _locally_present(slug: str) -> bool:
    """True if the product already has any extracted files under raw_docs/."""
    out_dir = RAW_DOCS_DIR / PRODUCTS[slug].get("output_dir", slug)
    return out_dir.exists() and any(out_dir.iterdir())


def _bundles_for_product(slug: str, session, no_refresh: bool) -> list[dict]:
    """Return [{name, title, doc_type, updated}] for a product.

    Live-refreshes the product's bundle list from /bundlelist unless no_refresh,
    in which case it uses the committed catalog.yaml detail.
    """
    cfg = PRODUCTS[slug]
    if no_refresh or session is None:
        return list(cfg.get("bundles_detail", []))
    seen: set[str] = set()
    out: list[dict] = []
    for lk in cfg.get("label_keys", []):
        for b in catalog_builder.fetch_bundles(session, lk):
            name = b.get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            out.append(catalog_builder.normalize_bundle(b))
        time.sleep(catalog_builder.CATALOG_REQUEST_DELAY)
    # Fall back to catalog detail if the live call yielded nothing
    return out or list(cfg.get("bundles_detail", []))


@app.command("sync")
def sync(
    product: Optional[str] = typer.Option(
        None, "--product", "-p", help="Sync one product (slug or alias)"
    ),
    category: Optional[str] = typer.Option(
        None, "--category", "-c", help="Sync all products in a category (e.g. aml, plt, ifm)"
    ),
    bundle: Optional[str] = typer.Option(
        None, "--bundle", "-b", help="Limit to bundles whose name contains this text"
    ),
    version: Optional[str] = typer.Option(
        None, "--version", "-v", help="Limit to bundles whose name contains this version, e.g. 10.1"
    ),
    since: Optional[str] = typer.Option(
        None, "--since", help="Only bundles updated after this date/ISO timestamp, e.g. 2026-01-01"
    ),
    since_last: bool = typer.Option(
        False, "--since-last", help="Only bundles updated since the last sync (state.last_sync)"
    ),
    fmt: str = typer.Option("md", "--format", "-f", help="Format to re-extract: md or pdf"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the change set without downloading"),
    force: bool = typer.Option(False, "--force", help="Re-extract in-scope bundles regardless of timestamp"),
    include_new: bool = typer.Option(
        False, "--include-new",
        help="Also download in-scope bundles not present locally (backfill). Default only refreshes existing.",
    ),
    no_refresh: bool = typer.Option(
        False, "--no-refresh", help="Diff against committed catalog.yaml instead of live /bundlelist"
    ),
    json_out: bool = typer.Option(False, "--json", help="Output machine-readable JSON"),
):
    """Re-extract only the bundles that changed on the portal since the last sync.

    Scope is category > product > (default) all locally-present products.
    Freshness signal is each bundle's portal 'Updated on' timestamp compared
    against docs/sync-state.json.
    """
    global PRODUCTS
    if not PRODUCTS:
        if json_out:
            print(json.dumps({"error": "no_catalog"}, indent=2))
        else:
            rprint("[red]No product catalog loaded.[/red] Run [bold]docenter catalog refresh[/bold].")
        raise typer.Exit(1)

    if fmt not in ("md", "pdf"):
        if json_out:
            print(json.dumps({"error": "invalid_format", "message": fmt}, indent=2))
        else:
            rprint(f"[red]Invalid format:[/red] '{fmt}'. Use md or pdf.")
        raise typer.Exit(1)

    # ── Resolve scope: product > category > locally-present ──────────────────
    if product:
        slugs = [_require_product(product)]
        scope_desc = f"product={slugs[0]}"
    elif category:
        valid_cats = {cfg.get("category_id") for cfg in PRODUCTS.values()}
        if category not in valid_cats:
            if json_out:
                print(json.dumps({"error": "unknown_category", "valid": sorted(filter(None, valid_cats))}, indent=2))
            else:
                rprint(f"[red]Unknown category:[/red] '{category}'. Valid: {', '.join(sorted(filter(None, valid_cats)))}")
            raise typer.Exit(1)
        slugs = [s for s, cfg in PRODUCTS.items() if cfg.get("category_id") == category]
        scope_desc = f"category={category} ({len(slugs)} products)"
    else:
        slugs = [s for s in PRODUCTS if _locally_present(s)]
        scope_desc = f"locally-present ({len(slugs)} products)"
        if not slugs:
            if json_out:
                print(json.dumps({"error": "no_scope", "message": "Nothing extracted locally; pass --product or --category."}, indent=2))
            else:
                rprint("[yellow]Nothing extracted locally.[/yellow] Pass [bold]--product[/bold] or [bold]--category[/bold] to seed a corpus.")
            raise typer.Exit(1)

    state = _load_sync_state()
    since_cmp = state.get("last_sync") if since_last else since

    session = None
    if not no_refresh:
        session = load_session()

    # Catalog-first: for broad syncs (no --product), refresh the catalog once
    # upfront and use its timestamps instead of per-product /bundlelist calls.
    catalog_first = not product and not no_refresh and session is not None
    if catalog_first:
        if not json_out:
            rprint("[bold]Refreshing catalog...[/bold] (one-time, replaces per-product API calls)")
        catalog_builder.build_catalog()
        PRODUCTS = _load_catalog_products()

    if not json_out:
        source = "catalog-first" if catalog_first else ("catalog.yaml" if no_refresh else "live refresh")
        rprint(f"\n[bold]Sync scope:[/bold] {scope_desc}  "
               f"[dim]({source}, format={fmt})[/dim]")

    new_items: list[dict] = []
    updated_items: list[dict] = []
    unchanged = 0
    seen_bundles: set[str] = set()

    use_catalog = no_refresh or catalog_first
    for i, slug in enumerate(slugs, 1):
        if not json_out:
            rprint(f"  [{i}/{len(slugs)}] {slug}")
        bundles = _bundles_for_product(slug, session, use_catalog)
        for bd in bundles:
            name = bd.get("name")
            if not name or name in seen_bundles:
                continue
            if bundle and bundle.lower() not in name.lower():
                continue
            if version and version not in name:
                continue
            seen_bundles.add(name)
            upd = bd.get("updated") or ""
            if since_cmp and upd and upd <= since_cmp:
                continue

            state_key = name if fmt == "md" else f"pdf::{name}"
            entry = state["bundles"].get(state_key)
            if fmt == "md":
                owner = _find_local_owner(name, slugs)
                local = owner is not None
                owner_slug = owner or slug
            else:
                local = _pdf_present(name)
                owner_slug = slug
            rec = {"product": owner_slug, "name": name, "state_key": state_key,
                   "version": extract_version(name),
                   "doc_type": bd.get("doc_type", ""), "updated": upd}

            if force:
                action = "update"
            elif not local:
                action = "new"
            elif entry is None:
                # Local files exist but untracked — adopt as baseline, don't re-extract.
                _raw_pc = fetch_page_count(session, name) if session and fmt == "md" else "?"
                pc = int(_raw_pc) if _raw_pc.isdigit() else None
                state["bundles"][state_key] = {"updated": upd, "downloaded_at": None,
                                               "product": owner_slug, "version": rec["version"],
                                               "page_count": pc}
                unchanged += 1
                continue
            elif upd and entry.get("updated") and upd > entry["updated"]:
                if session and entry.get("page_count") is not None and fmt == "md":
                    raw = fetch_page_count(session, name)
                    live_count = int(raw) if raw.isdigit() else None
                    if live_count is not None and live_count == entry["page_count"]:
                        unchanged += 1
                        continue
                    if live_count is not None:
                        rec["page_count"] = live_count
                action = "update"
            else:
                unchanged += 1
                continue

            (new_items if action == "new" else updated_items).append(rec)

    changed = updated_items + (new_items if include_new else [])

    # ── Dry run / reporting ──────────────────────────────────────────────────
    if dry_run or not changed:
        if not dry_run and unchanged:
            state["last_sync"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            _save_sync_state(state)
        if json_out:
            print(json.dumps({
                "scope": scope_desc, "refreshed": not no_refresh,
                "include_new": include_new,
                "new": new_items, "updated": updated_items,
                "unchanged": unchanged, "dry_run": dry_run,
            }, indent=2))
            return
        new_note = "" if include_new else " [dim](not downloaded — pass --include-new)[/dim]"
        rprint(f"\n[bold]Change set:[/bold] [green]{len(new_items)} new[/green]{new_note}, "
               f"[yellow]{len(updated_items)} updated[/yellow], {unchanged} unchanged")
        for r in new_items:
            rprint(f"  [green]+ NEW[/green]     {r['name']}  [dim]({r['updated']})[/dim]")
        for r in updated_items:
            rprint(f"  [yellow]~ UPDATED[/yellow] {r['name']}  [dim]({r['updated']})[/dim]")
        if dry_run:
            rprint("\n[yellow]Dry run — nothing downloaded.[/yellow]")
        elif not changed:
            rprint("\n[green]Everything is up to date.[/green]")
        return

    # ── Re-extract changed bundles ───────────────────────────────────────────
    extractor_script = _extractor_dir() / "extractor.py"
    pdf_script = _extractor_dir() / "pdf_exporter.py"
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    done_names: list[str] = []
    failed: list[str] = []

    if not json_out:
        rprint(f"\n[bold]Re-extracting {len(changed)} bundle(s)...[/bold]")
    for r in changed:
        if fmt == "md":
            cmd = [sys.executable, str(extractor_script), "--product", r["product"], "--bundle", r["name"]]
            dt = r.get("doc_type", "")
            if dt:
                cmd += ["--doc-type", dt]
        else:
            cmd = [sys.executable, str(pdf_script), "--product", r["product"], "--bundle", r["name"]]
            dt = r.get("doc_type", "")
            if dt:
                cmd += ["--doc-type", dt]
        if not json_out:
            rprint(f"\n[bold cyan]>>[/bold cyan] {r['name']}")
        result = subprocess.run(cmd, cwd=str(REPO_ROOT), env=_extractor_env())
        if result.returncode == 0:
            pc = r.get("page_count")
            if pc is None and session and fmt == "md":
                _raw = fetch_page_count(session, r["name"])
                pc = int(_raw) if _raw.isdigit() else None
            state["bundles"][r["state_key"]] = {
                "updated": r["updated"], "downloaded_at": now_iso,
                "product": r["product"], "version": r["version"],
                "page_count": pc,
            }
            done_names.append(r["name"])
        else:
            failed.append(r["name"])

    state["last_sync"] = now_iso
    _save_sync_state(state)
    _append_sync_log(now_iso, scope_desc, new_items, updated_items, done_names, failed)

    if json_out:
        print(json.dumps({
            "scope": scope_desc, "synced_at": now_iso,
            "downloaded": done_names, "failed": failed, "unchanged": unchanged,
        }, indent=2))
        return

    console.print()
    if failed:
        rprint(f"[yellow]Synced {len(done_names)}[/yellow], [red]{len(failed)} failed[/red]:")
        for n in failed:
            rprint(f"  • {n}")
        raise typer.Exit(1)
    rprint(f"[green]Synced {len(done_names)} bundle(s).[/green] State: [dim]{SYNC_STATE_FILE}[/dim]")


def _append_sync_log(ts: str, scope: str, new_items: list[dict], updated_items: list[dict],
                     done: list[str], failed: list[str]) -> None:
    """Append a dated entry to docs/sync-log.md (change feed for wiki/agent)."""
    done_set = set(done)
    lines = [f"\n## {ts}  ({scope})\n"]
    for r in new_items:
        if r["name"] in done_set:
            lines.append(f"- **new** [{r['name']}](https://docs.niceactimize.com/bundle/{r['name']})  ({r['updated']})")
    for r in updated_items:
        if r["name"] in done_set:
            lines.append(f"- **updated** [{r['name']}](https://docs.niceactimize.com/bundle/{r['name']})  ({r['updated']})")
    for n in failed:
        lines.append(f"- **FAILED** {n}")
    if len(lines) == 1:
        return
    SYNC_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    header = "" if SYNC_LOG_FILE.exists() else "# DOCenter Sync Log\n"
    with SYNC_LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(header + "\n".join(lines) + "\n")


def _pdf_present(name: str) -> bool:
    """True if a PDF for this bundle already exists under raw_docs_pdf/."""
    if not RAW_PDF_DIR.exists():
        return False
    return any(RAW_PDF_DIR.rglob(f"{name}.pdf"))


def _find_local_owner(name: str, slugs: list[str]) -> Optional[str]:
    """Return the in-scope product slug whose raw_docs/ dir already holds this bundle.

    Makes sync order-independent for cross-tagged bundles (e.g. ActOne bundles
    listed under several platform products) and ensures re-extraction targets the
    directory where the bundle already lives.
    """
    for s in slugs:
        if is_locally_extracted(PRODUCTS[s].get("output_dir", s), name):
            return s
    return None


def _search_local(
    query: str,
    max_results: int,
    product: Optional[str],
    doc_version: Optional[str],
    guide: Optional[str],
    json_out: bool,
) -> None:
    """Search the locally extracted corpus (raw_docs/) by reusing the MCP search."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        from mcp_server.server import search_docs, format_results_text
    except Exception as exc:
        if json_out:
            print(json.dumps({"error": "local_search_unavailable", "message": str(exc)}, indent=2))
            raise typer.Exit(1)
        rprint(f"[red]Local search unavailable:[/red] {exc}")
        raise typer.Exit(1)

    results = search_docs(
        query,
        version=doc_version,
        guide_type=guide,
        product=product,
        max_results=max_results,
    )

    if json_out:
        results_out = []
        for i, r in enumerate(results, 1):
            url = str(r.get("resource") or r.get("source_url") or "").replace(
                "docs-be.niceactimize.com", "docs.niceactimize.com"
            )
            results_out.append({
                "num": i,
                "title": r.get("title") or r.get("page_title", ""),
                "product": r.get("product", ""),
                "version": r.get("version", ""),
                "bundle": r.get("bundle", ""),
                "guide_type": r.get("guide_type", ""),
                "url": url,
                "snippet": (r.get("excerpt", "") or "")[:300],
                "file": r.get("file", ""),
            })
        print(json.dumps({"mode": "local", "results": results_out, "count": len(results_out)}, indent=2))
        return

    console.print()
    print(format_results_text(results, query))


def _norm_token(s: str) -> str:
    """Lowercase and strip non-alphanumerics for forgiving substring matching."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _version_overlap(found: str, want: str) -> bool:
    """True if a dotted version found in a facet label is the same line as the
    requested version (e.g. facet '10.2.0' matches --doc-version '10.2')."""
    if found == want:
        return True
    return found.startswith(want + ".") or want.startswith(found + ".")


def _resolve_product_labelkeys(relevant_labels, product, doc_version):
    """Map --product/--doc-version to the portal's facet label keys.

    The live /api/search endpoint accepts a POST body ``{"labelkeys": [...]}``
    for server-side facet narrowing. Product facets are keyed like
    ``product-platform-actone-basic-1020`` with a human navtitle
    ``"ActOne Basic 10.2.0"``. We match the requested product against the
    navtitle/key (normalized substring) and, when given, require a matching
    dotted version. Multiple matches are returned and OR-combined by the portal
    within the product facet group (verified empirically)."""
    pnorm = _norm_token(product) if product else ""
    want = doc_version.strip() if doc_version else ""
    keys: list[str] = []
    for lab in relevant_labels or []:
        key = lab.get("key") or ""
        if not key.startswith("product-"):
            continue
        if (lab.get("subjectheadNavtitle") or "") == "Type of Information":
            continue
        nav = lab.get("navtitle") or ""
        if pnorm and pnorm not in _norm_token(nav) and pnorm not in _norm_token(key):
            continue
        if want:
            found = re.findall(r"\d+(?:\.\d+)+", nav)
            if not any(_version_overlap(f, want) for f in found):
                continue
        keys.append(key)
    return keys


def _bundle_matches(bundle_id, product=None, doc_version=None, guide=None, bundle=None) -> bool:
    """Client-side post-filter on a result's bundle_id, mirroring local
    --product/--doc-version/--guide semantics. Used as the fallback when a
    product/version cannot be resolved to a portal facet, and always for
    --guide and bundle scoping (the portal has no facets for either)."""
    bn = _norm_token(bundle_id)
    if product and _norm_token(product) not in bn:
        return False
    if doc_version and _norm_token(doc_version) not in bn:
        return False
    if guide and _norm_token(guide) not in bn:
        return False
    if bundle and _norm_token(bundle) not in bn:
        return False
    return True


def _portal_search(session, query, per_page, page, labelkeys=None):
    """Single live-portal /api/search call. Issues a GET for an unfiltered
    query, or a POST with a ``labelkeys`` body for server-side facet filtering.
    Returns the parsed JSON dict. Raises RuntimeError('access_denied') on HTTP
    403, or RuntimeError(<message>) on any other failure.

    Page size uses the portal's ``rpp`` parameter (``per_page`` is silently
    ignored and always yields 10; ``rpp`` is honored up to a server cap of 100
    — verified empirically 2026-07-06)."""
    import requests as _req

    url = f"{BASE_API}/search?q={_req.utils.quote(query)}&rpp={per_page}&page={page}"
    headers = {"Accept-Encoding": "identity"}
    try:
        if labelkeys:
            resp = session.post(url, json={"labelkeys": labelkeys}, timeout=30, headers=headers)
        else:
            resp = session.get(url, timeout=30, headers=headers)
        if resp.status_code == 403:
            raise RuntimeError("access_denied")
        resp.raise_for_status()
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(str(exc))
    return resp.json()


def _portal_query_suggestions(data: dict, original: str) -> list[str]:
    """Collect alternative query strings the portal offers when a search comes up
    short — the ``did_you_mean`` spell-correction and any ``query_synonyms`` —
    excluding candidates equivalent to the original query. ``did_you_mean`` is
    returned first. De-duplicated by normalized form so an abbreviation and its
    expansion don't both appear."""
    out: list[str] = []
    seen = {_norm_token(original)}

    def _add(s) -> None:
        if not isinstance(s, str):
            return
        s = s.strip()
        n = _norm_token(s)
        if not n or n in seen:
            return
        seen.add(n)
        out.append(s)

    _add(data.get("did_you_mean"))
    syn = data.get("query_synonyms")
    if isinstance(syn, str):
        _add(syn)
    elif isinstance(syn, list):
        for item in syn:
            if isinstance(item, str):
                _add(item)
            elif isinstance(item, dict):
                _add(item.get("text") or item.get("term") or item.get("synonym"))
    return out


def _map_portal_item(item: dict) -> dict:
    """Flatten a raw portal search result into the fields callers use: title,
    bundle, snippet (HTML stripped), short_desc, updated date, backend url and
    user-facing portal url."""
    lr = item.get("leading_result", {})
    url_link = lr.get("url", "")
    raw_snippet = item.get("highlighted_snippet") or lr.get("snippet") or lr.get("shortDesc") or ""
    snippet = re.sub(r"<[^>]+>", "", str(raw_snippet)).strip()
    return {
        "title": lr.get("title", "-"),
        "bundle": lr.get("bundle_id", "-"),
        "snippet": snippet,
        "short_desc": (lr.get("shortDesc") or "").strip(),
        "updated": ((lr.get("dates") or {}).get("Updated on") or "")[:10],
        "url": url_link,
        "portal_url": url_link.replace("docs-be.niceactimize.com", "docs.niceactimize.com"),
    }


def portal_search_core(
    session,
    query: str,
    *,
    max_results: int = 10,
    page: int = 1,
    product: Optional[str] = None,
    doc_version: Optional[str] = None,
    guide: Optional[str] = None,
    bundle: Optional[str] = None,
    retry: bool = True,
) -> dict:
    """Shared live-portal search used by the CLI and the Copilot proxy.

    Runs the hybrid facet/labelkeys fetch, the client-side fallback + ``--guide``
    / ``bundle`` post-filters, and one spelling/synonym auto-retry when the query
    comes up empty. Returns a dict with trimmed raw ``results``, ``pagination``
    (including ``raw_total_count``, the portal's pre-filter match total),
    ``effective_query``/``corrected_from`` (set when a suggestion was adopted),
    ``suggestions`` (portal alternative queries), ``filters_active``,
    ``next_page`` and ``did_you_mean``.

    Raises ``RuntimeError('access_denied')`` on HTTP 403, or
    ``RuntimeError(<message>)`` on any other portal failure.
    """
    want_facet = bool(product or doc_version)
    filters_active = want_facet or bool(guide) or bool(bundle)
    fetch_n = min(100, max(max_results * 3, 20)) if filters_active else max_results
    if guide or bundle:
        # Substring post-filters keep only a tiny fraction of raw hits — fetch
        # the portal's maximum page so they have enough candidates.
        fetch_n = 100

    def _fetch_filtered(q: str):
        d = _portal_search(session, q, fetch_n, page)
        lk_used: list[str] = []
        if want_facet:
            lk = _resolve_product_labelkeys(d.get("relevant_labels", []), product, doc_version)
            if lk:
                d = _portal_search(session, q, fetch_n, page, labelkeys=lk)
                lk_used = lk
        res = d.get("Results", [])
        if want_facet and not lk_used:
            res = [
                it for it in res
                if _bundle_matches(it.get("leading_result", {}).get("bundle_id", ""),
                                   product=product, doc_version=doc_version)
            ]
        if guide or bundle:
            res = [
                it for it in res
                if _bundle_matches(it.get("leading_result", {}).get("bundle_id", ""),
                                   guide=guide, bundle=bundle)
            ]
        return d, res, lk_used

    effective_query = query
    corrected_from: Optional[str] = None
    data, results, _lk = _fetch_filtered(query)
    if not results and retry:
        for alt in _portal_query_suggestions(data, query):
            alt_data, alt_results, _alk = _fetch_filtered(alt)
            if alt_results:
                data, results = alt_data, alt_results
                effective_query, corrected_from = alt, query
                break

    pagination = data.get("Pagination", {})
    results = results[:max_results]
    pagination_out = {
        "page_number": pagination.get("page_number", 1),
        "total_pages": 1 if filters_active else pagination.get("total_pages", 1),
        "total_count": len(results) if filters_active else pagination.get("total_count", len(results)),
        "raw_total_count": pagination.get("total_count"),
    }
    suggestions = _portal_query_suggestions(data, query) if retry else []
    return {
        "results": results,
        "pagination": pagination_out,
        "effective_query": effective_query,
        "corrected_from": corrected_from,
        "suggestions": suggestions,
        "filters_active": filters_active,
        "next_page": pagination.get("next_page"),
        "did_you_mean": data.get("did_you_mean"),
    }


@app.command("search")
def search(
    query: str = typer.Argument(..., help="Search query, e.g. 'LexisNexis Bridger'"),
    max_results: int = typer.Option(10, "--max", "-n", help="Max results to display (default 10)"),
    page: int = typer.Option(1, "--page", "-p", help="Page number (default 1)"),
    local: bool = typer.Option(
        False, "--local",
        help="Search the local extracted corpus (raw_docs/) instead of the live portal — no auth needed",
    ),
    product: Optional[str] = typer.Option(
        None, "--product", help="Filter by product key/name, e.g. actone, ifm, sam",
    ),
    doc_version: Optional[str] = typer.Option(
        None, "--doc-version", help="Filter by doc version, e.g. 10.1",
    ),
    guide: Optional[str] = typer.Option(
        None, "--guide", help="Filter by guide type, e.g. implementer (online: post-filtered on bundle name)",
    ),
    no_retry: bool = typer.Option(
        False, "--no-retry",
        help="Don't auto-retry with the portal's spelling suggestion when a search returns no results.",
    ),
    json_out: bool = typer.Option(False, "--json", help="Output machine-readable JSON instead of a table"),
):
    """Search NICE Actimize docs — the live portal by default, or the local corpus with --local.

    Online filtering (hybrid): --product/--doc-version use the portal's
    server-side facet filter (labelkeys) for true narrowing; --guide is applied
    as a client-side post-filter on the bundle name (the portal has no
    guide-type facet). All three already work offline with --local."""
    if local:
        _search_local(query, max_results, product, doc_version, guide, json_out)
        return

    try:
        import requests  # noqa: F401  (dependency check; _portal_search imports it)
    except ImportError:
        if json_out:
            print(json.dumps({"error": "missing_dependency", "message": "pip install requests"}, indent=2))
            raise typer.Exit(1)
        rprint("[red]Missing dependency:[/red] pip install requests")
        raise typer.Exit(1)

    session = load_session()

    # Hybrid online filtering:
    #   --product / --doc-version  -> portal server-side facet filter (labelkeys)
    #   --guide                    -> client-side post-filter on bundle name
    # When a product/version cannot be resolved to a facet, fall back to a
    # client-side bundle-name filter so behavior still mirrors --local.
    try:
        sr = portal_search_core(
            session, query, max_results=max_results, page=page,
            product=product, doc_version=doc_version, guide=guide, retry=not no_retry,
        )
    except RuntimeError as exc:
        if str(exc) == "access_denied":
            if json_out:
                print(json.dumps({
                    "error": "access_denied",
                    "message": "Access denied (403). Your session has expired or is invalid. Run: docenter auth login",
                }, indent=2))
                raise typer.Exit(1)
            rprint("[red]Access denied (403).[/red] Your session has expired or is invalid.")
            rprint("Run: [bold]docenter auth login[/bold]")
            raise typer.Exit(1)
        if json_out:
            print(json.dumps({"error": "request_failed", "message": str(exc)}, indent=2))
            raise typer.Exit(1)
        rprint(f"[red]Search request failed:[/red] {exc}")
        raise typer.Exit(1)

    results = sr["results"]
    pagination_out = sr["pagination"]
    effective_query = sr["effective_query"]
    corrected_from = sr["corrected_from"]
    filters_active = sr["filters_active"]

    if not results:
        suggestions = sr["suggestions"]
        if json_out:
            payload = {"results": [], "pagination": pagination_out}
            if sr.get("did_you_mean"):
                payload["did_you_mean"] = sr["did_you_mean"]
            if suggestions:
                payload["suggestions"] = suggestions
                payload["retried"] = True
            print(json.dumps(payload, indent=2))
            raise typer.Exit(0)
        msg = "[yellow]No results found.[/yellow]"
        if suggestions:
            tried = ", ".join(f"[bold]{s}[/bold]" for s in suggestions)
            msg += f"  Tried the portal's suggestion(s) too — {tried} — still nothing."
        elif sr.get("did_you_mean"):
            msg += f"  Did you mean: [bold]{sr['did_you_mean']}[/bold]?"
        rprint(msg)
        raise typer.Exit(0)

    if corrected_from and not json_out:
        rprint(
            f"[dim]No results for [bold]{corrected_from}[/bold] — showing results for "
            f"[bold]{effective_query}[/bold] (portal suggestion).[/dim]"
        )

    if json_out:
        results_out = []
        for i, item in enumerate(results, 1):
            mapped = _map_portal_item(item)
            results_out.append({
                "num": i,
                "title": mapped["title"],
                "bundle": mapped["bundle"],
                "snippet": mapped["snippet"][:160],
                "url": mapped["url"],
                "portal_url": mapped["portal_url"],
            })
        payload = {"results": results_out, "pagination": pagination_out}
        if corrected_from:
            payload["original_query"] = corrected_from
            payload["corrected_query"] = effective_query
        print(json.dumps(payload, indent=2))
        return

    table = Table(
        title=f"Portal Search: [bold]{effective_query}[/bold]  "
              f"(page {pagination_out['page_number']} of {pagination_out['total_pages']}, "
              f"{pagination_out['total_count']} total)",
        show_lines=True,
        header_style="bold magenta",
    )
    table.add_column("#", style="dim", width=3, no_wrap=True)
    table.add_column("Title", style="bold cyan", min_width=30)
    table.add_column("Bundle / Product", style="white", min_width=35)
    table.add_column("Snippet", style="dim white", min_width=40)

    refs: list[tuple[int, str, str]] = []  # (num, title, portal_url)

    for i, item in enumerate(results, 1):
        mapped = _map_portal_item(item)
        snippet = mapped["snippet"][:160]
        table.add_row(str(i), mapped["title"], mapped["bundle"], snippet or mapped["url"][:80])
        refs.append((i, mapped["title"], mapped["portal_url"]))

    console.print()
    console.print(table)

    # References
    console.print("\n[bold magenta]References[/bold magenta]")
    for num, title, portal_url in refs:
        console.print(f"  [dim]{num}.[/dim] [cyan]{title}[/cyan]")
        console.print(f"     [blue underline]{portal_url}[/blue underline]")

    if not filters_active and sr.get("next_page"):
        console.print(f"\n[dim]More results: [bold]docenter search \"{effective_query}\" --page {page + 1}[/bold][/dim]")
    console.print()


WIKI_DIR = REPO_ROOT / "wiki"
_WIKI_GEN_HEADER = (
    "<!-- generated by `docenter wiki build` - do not edit by hand; "
    "regenerate from raw_docs/ -->"
)


def _read_frontmatter(path: Path) -> dict:
    """Parse the YAML frontmatter block at the top of a Markdown file."""
    import yaml

    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        data = yaml.safe_load(text[3:end]) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _portal_url(u: str) -> str:
    return (u or "").replace("docs-be.niceactimize.com", "docs.niceactimize.com")


def _collect_corpus(only_product: Optional[str]) -> dict:
    """Walk raw_docs/ into {product: {version: {bundle: {meta + topics}}}}.

    Each topic is {"title", "url"} where url is the portal source. Ordering is
    applied deterministically here so the wiki is a pure function of the corpus.
    """
    corpus: dict = {}
    if not RAW_DOCS_DIR.exists():
        return corpus
    for product_dir in sorted(RAW_DOCS_DIR.iterdir(), key=lambda p: p.name):
        if not product_dir.is_dir() or product_dir.name == "pdfs":
            continue
        if only_product and product_dir.name != only_product:
            continue
        for version_dir in sorted(product_dir.iterdir(), key=lambda p: p.name):
            if not version_dir.is_dir():
                continue
            version = version_dir.name.lstrip("v")
            for bundle_dir in sorted(version_dir.iterdir(), key=lambda p: p.name):
                if not bundle_dir.is_dir():
                    continue
                md_files = sorted(
                    (m for m in bundle_dir.glob("*.md") if m.name.lower() != "index.md"),
                    key=lambda p: p.name,
                )
                if not md_files:
                    continue
                topics, guide_type, product_name, updated = [], "", product_dir.name, ""
                for mf in md_files:
                    fm = _read_frontmatter(mf)
                    title = fm.get("title") or fm.get("page_title") or mf.stem.replace("_", " ")
                    url = _portal_url(fm.get("resource") or fm.get("source_url") or "")
                    guide_type = guide_type or fm.get("guide_type") or fm.get("type") or ""
                    product_name = fm.get("product") or product_name
                    ts = str(fm.get("updated") or fm.get("timestamp") or "")
                    if ts > updated:
                        updated = ts
                    topics.append({"title": str(title), "url": url})
                topics.sort(key=lambda t: t["title"].lower())
                corpus.setdefault(product_dir.name, {}).setdefault(version, {})[bundle_dir.name] = {
                    "title": bundle_dir.name.replace("_", " "),
                    "product_name": product_name,
                    "guide_type": guide_type,
                    "topics": topics,
                    "updated": updated,
                }
    return corpus


def _wiki_bundle_page(version: str, bundle: str, data: dict, siblings: list) -> str:
    lines = [_WIKI_GEN_HEADER, "", f"# {data['title']}", ""]
    lines.append(f"- **Product:** {data['product_name']}")
    lines.append(f"- **Version:** {version}")
    if data["guide_type"]:
        lines.append(f"- **Guide type:** {data['guide_type']}")
    lines.append(f"- **Topics:** {len(data['topics'])}")
    if data["updated"]:
        lines.append(f"- **Latest source update:** {data['updated']}")
    lines.append(f"- **Source bundle:** [{bundle}](https://docs.niceactimize.com/bundle/{bundle})")
    lines += ["", "[<- Product index](../../index.md) | [<- Wiki home](../../../index.md)", "",
              "## Topics", ""]
    for t in data["topics"]:
        lines.append(f"- [{t['title']}]({t['url']})" if t["url"] else f"- {t['title']}")
    if siblings:
        lines += ["", "## Related bundles", ""]
        for sv, sb, stitle in siblings:
            lines.append(f"- [{stitle}](../../v{sv}/{sb}/index.md)")
    return "\n".join(lines) + "\n"


def _wiki_product_page(product: str, versions: dict) -> str:
    nb = sum(len(v) for v in versions.values())
    nt = sum(len(b["topics"]) for v in versions.values() for b in v.values())
    lines = [_WIKI_GEN_HEADER, "", f"# {product} - documentation wiki", "",
             "[<- Wiki home](../index.md)", "", f"{nb} bundle(s), {nt} topic(s).", ""]
    for version in sorted(versions, reverse=True):
        lines += [f"## v{version}", ""]
        for bundle in sorted(versions[version]):
            data = versions[version][bundle]
            gt = f" - {data['guide_type']}" if data["guide_type"] else ""
            lines.append(
                f"- [{data['title']}](v{version}/{bundle}/index.md){gt}  ({len(data['topics'])} topics)"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def _wiki_global_page(corpus: dict) -> str:
    tot_bundles = sum(len(v) for p in corpus.values() for v in p.values())
    tot_topics = sum(len(b["topics"]) for p in corpus.values() for v in p.values() for b in v.values())
    lines = [_WIKI_GEN_HEADER, "", "# Actimize Documentation Wiki", "",
             "Deterministically generated from the local `raw_docs/` corpus. "
             "Topic links point to the official NICE Actimize documentation portal.", "",
             f"**{len(corpus)} product(s) | {tot_bundles} bundle(s) | {tot_topics} topic(s)**", ""]
    if SYNC_LOG_FILE.exists():
        lines += ["See also: [What's new (sync log)](../docs/sync-log.md)", ""]
    lines += ["## Products", ""]
    for product in sorted(corpus):
        nb = sum(len(v) for v in corpus[product].values())
        nt = sum(len(b["topics"]) for v in corpus[product].values() for b in v.values())
        vers = ", ".join(f"v{v}" for v in sorted(corpus[product], reverse=True))
        lines.append(f"- [{product}]({product}/index.md) - {vers}  ({nb} bundles, {nt} topics)")
    return "\n".join(lines) + "\n"


wiki_app = typer.Typer(help="Generate a deterministic, cross-linked documentation wiki from raw_docs/.")
app.add_typer(wiki_app, name="wiki")


@wiki_app.command("build")
def wiki_build(
    product: Optional[str] = typer.Option(
        None, "--product", "-p", help="Build only one product (slug), e.g. actone"
    ),
    json_out: bool = typer.Option(False, "--json", help="Output a machine-readable build summary"),
):
    """Generate a navigable, citation-backed wiki under wiki/ - purely from raw_docs/.

    Emits a global landing page, a per-product index, and a per-bundle index that
    lists every topic with a link to its official portal page. No LLM, no network:
    re-running produces identical output (a pure function of the corpus).
    """
    import shutil

    corpus = _collect_corpus(product)
    if not corpus:
        if json_out:
            print(json.dumps({"error": "empty_corpus",
                              "message": "No extracted Markdown found under raw_docs/."}, indent=2))
            raise typer.Exit(1)
        rprint("[yellow]No extracted Markdown found under raw_docs/.[/yellow] "
               "Run [bold]docenter download <bundle>[/bold] first.")
        raise typer.Exit(1)

    # Clean the generated tree so deletions propagate (pure-function guarantee).
    if product:
        tgt = WIKI_DIR / product
        if tgt.exists():
            shutil.rmtree(tgt)
    elif WIKI_DIR.exists():
        shutil.rmtree(WIKI_DIR)
    WIKI_DIR.mkdir(parents=True, exist_ok=True)

    pages = 0
    for prod, versions in corpus.items():
        prod_dir = WIKI_DIR / prod
        prod_dir.mkdir(parents=True, exist_ok=True)
        (prod_dir / "index.md").write_text(_wiki_product_page(prod, versions), encoding="utf-8")
        pages += 1
        # Pre-compute sibling list (all other bundles in the same product).
        all_bundles = [(v, b, versions[v][b]["title"]) for v in versions for b in versions[v]]
        for version, bundles in versions.items():
            for bundle, data in bundles.items():
                siblings = sorted(
                    (s for s in all_bundles if not (s[0] == version and s[1] == bundle)),
                    key=lambda s: (s[0], s[1]),
                )
                bdir = prod_dir / f"v{version}" / bundle
                bdir.mkdir(parents=True, exist_ok=True)
                (bdir / "index.md").write_text(
                    _wiki_bundle_page(version, bundle, data, siblings), encoding="utf-8"
                )
                pages += 1

    # The global landing page reflects only what was (re)built when scoped to one
    # product, so rebuild it from a full corpus walk to stay accurate.
    full = corpus if not product else _collect_corpus(None)
    (WIKI_DIR / "index.md").write_text(_wiki_global_page(full), encoding="utf-8")
    pages += 1

    tot_bundles = sum(len(v) for p in corpus.values() for v in p.values())
    tot_topics = sum(len(b["topics"]) for p in corpus.values() for v in p.values() for b in v.values())

    if json_out:
        print(json.dumps({
            "scope": product or "all",
            "products": len(corpus), "bundles": tot_bundles,
            "topics": tot_topics, "pages_written": pages,
            "output": str(WIKI_DIR),
        }, indent=2))
        return

    rprint(f"[green]Wiki built.[/green] {len(corpus)} product(s), {tot_bundles} bundle(s), "
           f"{tot_topics} topic(s) -> {pages} page(s).")
    rprint(f"Open [bold]{WIKI_DIR / 'index.md'}[/bold]")


INDEX_DIR = RAW_DOCS_DIR / "index"


def _bundle_version(bundle_name: str) -> str:
    """Derive a version tag from a bundle name (mirrors extractor.extract_version)."""
    m = re.search(r"_(\d+\.\d+)", bundle_name or "")
    return m.group(1) if m else "unknown"


def _canonical_owner(bundle_name: str, candidate_slugs: list[str]) -> str:
    """Pick the product whose slug best matches a shared bundle name.

    Uses slug<->bundle token overlap (same heuristic as scripts/dedup_corpus.py),
    so e.g. ``actone`` owns ``Actimize_ActOne_10.2_Implementer_Guide``. Ties break
    deterministically (shortest, then lexicographic) so output is stable.
    """
    def toks(s: str) -> set[str]:
        for ch in "-_.":
            s = s.replace(ch, " ")
        return {t for t in s.lower().split() if t}

    btoks = toks(bundle_name)
    return sorted(candidate_slugs, key=lambda s: (-len(toks(s) & btoks), len(s), s))[0]


def _build_taxonomy_index() -> dict:
    """Compute the category->product->bundle taxonomy + a bundle reverse index.

    Pure function of the catalog (PRODUCTS). Surfaces cross-listing: each bundle
    records every product that references it plus a single canonical owner.
    """
    by_product: dict[str, dict] = {}
    by_category: dict[str, dict] = {}
    bundles: dict[str, dict] = {}

    for slug, cfg in PRODUCTS.items():
        detail = cfg.get("bundles_detail") or []
        prod_bundles = []
        for b in detail:
            name = b.get("name")
            if not name:
                continue
            entry = {
                "name": name,
                "title": b.get("title"),
                "doc_type": b.get("doc_type"),
                "version": _bundle_version(name),
                "updated": b.get("updated"),
            }
            prod_bundles.append(entry)
            rev = bundles.setdefault(name, {
                "name": name,
                "title": b.get("title"),
                "doc_type": b.get("doc_type"),
                "version": _bundle_version(name),
                "updated": b.get("updated"),
                "products": [],
            })
            if slug not in rev["products"]:
                rev["products"].append(slug)

        by_product[slug] = {
            "name": cfg.get("name"),
            "title": cfg.get("title"),
            "category_id": cfg.get("category_id"),
            "category": cfg.get("category"),
            "output_dir": cfg.get("output_dir", slug),
            "bundle_count": len(prod_bundles),
            "bundles": sorted(prod_bundles, key=lambda e: e["name"]),
        }

        cat_id = cfg.get("category_id") or "uncategorized"
        cat = by_category.setdefault(cat_id, {
            "id": cat_id,
            "title": cfg.get("category"),
            "products": [],
        })
        cat["products"].append({"slug": slug, "name": cfg.get("name"), "bundle_count": len(prod_bundles)})

    # Stamp the canonical owner now that every bundle's full product list is known.
    for name, rev in bundles.items():
        rev["products"].sort()
        rev["shared"] = len(rev["products"]) > 1
        rev["canonical_product"] = _canonical_owner(name, rev["products"]) if rev["products"] else None

    for cat in by_category.values():
        cat["products"].sort(key=lambda p: p["slug"])

    shared = [n for n, r in bundles.items() if r["shared"]]
    return {
        "by_product": by_product,
        "by_category": by_category,
        "bundles": dict(sorted(bundles.items())),
        "stats": {
            "products": len(by_product),
            "categories": len(by_category),
            "bundles": len(bundles),
            "shared_bundles": len(shared),
            "bundle_listings": sum(len(p["bundles"]) for p in by_product.values()),
        },
    }


index_app = typer.Typer(help="Generate the catalog taxonomy index (category -> product -> bundle).")
app.add_typer(index_app, name="index")


@index_app.command("build")
def index_build(
    json_out: bool = typer.Option(False, "--json", help="Output a machine-readable build summary"),
):
    """Emit raw_docs/index/ from the catalog - the taxonomy as data, not folders.

    Writes by_product.json, by_category.json, and bundles.json (a reverse index
    that records, for every bundle, all products that reference it plus a single
    canonical owner). Pure function of docs/catalog.yaml: no corpus mutation, no
    network. This is the foundation the dedup/migration and publish steps read.
    """
    if not PRODUCTS:
        if json_out:
            print(json.dumps({"error": "no_catalog",
                              "message": f"No catalog at {CATALOG_FILE}. Run: docenter catalog refresh"}, indent=2))
            raise typer.Exit(1)
        rprint(f"[yellow]No catalog file at[/yellow] {CATALOG_FILE}")
        rprint("Run: [bold]docenter catalog refresh[/bold]")
        raise typer.Exit(1)

    idx = _build_taxonomy_index()
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def _dump(name: str, payload: dict) -> None:
        (INDEX_DIR / name).write_text(
            json.dumps({"generated_at": generated_at, **payload}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    _dump("by_product.json", {"products": idx["by_product"]})
    _dump("by_category.json", {"categories": idx["by_category"]})
    _dump("bundles.json", {"bundles": idx["bundles"]})

    stats = idx["stats"]
    if json_out:
        print(json.dumps({"output": str(INDEX_DIR), "generated_at": generated_at, **stats}, indent=2))
        return

    rprint(f"[green]Index built.[/green] -> {INDEX_DIR}")
    rprint(f"  Products:        {stats['products']}")
    rprint(f"  Categories:      {stats['categories']}")
    rprint(f"  Bundles:         {stats['bundles']} unique ({stats['bundle_listings']} listings)")
    rprint(f"  Shared bundles:  {stats['shared_bundles']} (referenced by >1 product)")


@index_app.command("status")
def index_status(
    json_out: bool = typer.Option(False, "--json", help="Output machine-readable status"),
):
    """Show whether raw_docs/index/ exists and summarize its contents."""
    files = ["by_product.json", "by_category.json", "bundles.json"]
    present = {f: (INDEX_DIR / f).exists() for f in files}
    if not all(present.values()):
        if json_out:
            print(json.dumps({"built": False, "index_dir": str(INDEX_DIR), "present": present}, indent=2))
            raise typer.Exit(1)
        rprint(f"[yellow]Index not built[/yellow] at {INDEX_DIR}")
        rprint("Run: [bold]docenter index build[/bold]")
        raise typer.Exit(1)

    try:
        bundles = json.loads((INDEX_DIR / "bundles.json").read_text(encoding="utf-8"))
        by_product = json.loads((INDEX_DIR / "by_product.json").read_text(encoding="utf-8"))
    except Exception as e:
        rprint(f"[red]Failed to read index:[/red] {e}")
        raise typer.Exit(1)

    bdict = bundles.get("bundles", {})
    shared = {n: r for n, r in bdict.items() if r.get("shared")}
    gen = bundles.get("generated_at", "(unknown)")[:19]
    if json_out:
        print(json.dumps({
            "built": True, "index_dir": str(INDEX_DIR), "generated_at": gen,
            "products": len(by_product.get("products", {})),
            "bundles": len(bdict), "shared_bundles": len(shared),
        }, indent=2))
        return

    rprint(f"[bold]Index dir:[/bold]      {INDEX_DIR}")
    rprint(f"[bold]Generated:[/bold]      {gen}")
    rprint(f"[bold]Products:[/bold]       {len(by_product.get('products', {}))}")
    rprint(f"[bold]Bundles:[/bold]        {len(bdict)} unique")
    rprint(f"[bold]Shared bundles:[/bold] {len(shared)} (referenced by >1 product)")
    if shared:
        top = sorted(shared.items(), key=lambda kv: -len(kv[1]["products"]))[:5]
        rprint("\n[bold]Most cross-listed bundles:[/bold]")
        for name, rev in top:
            rprint(f"  [dim]{len(rev['products']):>3}x[/dim] {name}  "
                   f"[dim](owner: {rev['canonical_product']})[/dim]")


if __name__ == "__main__":
    app()