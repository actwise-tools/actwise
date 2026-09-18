"""
ActWise Survey — catalogs bundle structure for SAM, CDD, IFM and other products.

Read-only: queries Zoomin API for bundle names, page counts, and top-level chapters.
No content is downloaded. Writes a markdown report to docs/.

Usage:
    py extractor/survey.py                    # survey all configured products
    py extractor/survey.py --product sam      # survey SAM only
    py extractor/survey.py --product xse-sam  # survey X-Sight Enterprise SAM
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_API = "https://docs-be.niceactimize.com/api"
COOKIES_FILE = Path(__file__).parent.parent / "browser-profile" / "session-cookies.json"
OUTPUT_FILE = Path(__file__).parent.parent / "docs" / "2026-05-08-docmap-survey.md"

SURVEY_PRODUCTS = {
    "actone": {
        "name": "ActOne",
        # These label keys go beyond the hardcoded bundle list in extractor.py.
        # They discover Product Info docs (e.g. Compatibility Matrix) and any
        # bundles not yet in the extractor config.
        "label_keys": [
            "product-platform-actone",
            "product-platform-actone-info",
            "product-platform-actone-product-docs",
            "product-platform-actone-basic-1010",
            "product-platform-actone-basic-1000",
        ],
    },
    "sam": {
        "name": "Suspicious Activity Monitoring (SAM)",
        "label_keys": [
            "product-sam",
            "product-sam-10x",
            "product-sam-1010",
            "product-sam-1000",
            "product-sam-9x",
            "product-sam-920",
        ],
    },
    "xse-sam": {
        "name": "X-Sight Enterprise SAM",
        "label_keys": [
            "product-x-sight-enterprise-sam",
            "product-x-sight-enterprise-sam-product-docs",
        ],
    },
    "cdd": {
        "name": "Customer Due Diligence (CDD)",
        "label_keys": [
            "product-cdd",
            "product-cdd-10x",
            "product-cdd-1040",
            "product-cdd-1020",
            "product-cdd-1010",
        ],
    },
    "xse-cdd": {
        "name": "X-Sight Enterprise CDD",
        "label_keys": [
            "product-x-sight-enterprise-cdd",
            "product-x-sight-enterprise-cdd-product-docs",
        ],
    },
    "ifm": {
        "name": "Integrated Fraud Management (IFM)",
        "label_keys": [
            "product-ifm-pro",
            "product-ifm-platform",
            "product-ifm-pro-ifmx",
            "product-ifm-pro-ifm-11",
            "product-ifm-pro-ifm-110",
            "product-ifm-pro-ifm-111",
            "product-ifm-pro-ifm-112",
        ],
    },
    "xse-fraud": {
        "name": "X-Sight Enterprise Fraud",
        "label_keys": [
            "product-x-sight-enterprise-fraud",
            "product-x-sight-enterprise-fraud-product-docs",
        ],
    },
}


# ---------------------------------------------------------------------------
# Session (same pattern as extractor.py)
# ---------------------------------------------------------------------------

def load_session() -> requests.Session:
    if not COOKIES_FILE.exists():
        print(f"ERROR: Cookie file not found: {COOKIES_FILE}")
        print("Run auth refresh using agent-browser.")
        sys.exit(1)
    data = json.loads(COOKIES_FILE.read_text())
    session = requests.Session()
    for c in data["data"]["cookies"]:
        session.cookies.set(c["name"], c["value"], domain=c["domain"])
    session.headers.update({"Accept": "application/json"})
    # The /bundlelist endpoint has a server-side bug: it sends
    # Content-Encoding: gzip even when the body is not gzip-encoded.
    # Strip the header only for bundlelist responses — TOC and page
    # responses use valid gzip encoding that must not be stripped.
    def _strip_bad_encoding(r, *a, **kw):
        if "bundlelist" in r.url:
            r.headers.pop("Content-Encoding", None)
            if hasattr(r, "raw") and hasattr(r.raw, "headers"):
                r.raw.headers.pop("content-encoding", None)
    session.hooks["response"].append(_strip_bad_encoding)
    return session


# ---------------------------------------------------------------------------
# TOC (same as extractor.py)
# ---------------------------------------------------------------------------

def flatten_toc(entries: list) -> list[dict]:
    pages = []
    for e in entries:
        if e.get("nav_path"):
            pages.append({"title": e.get("title", ""), "path": e["nav_path"]})
        pages.extend(flatten_toc(e.get("childEntries", [])))
    return pages


# ---------------------------------------------------------------------------
# Bundle discovery
# ---------------------------------------------------------------------------

def discover_bundles(session: requests.Session, label_keys: list[str]) -> list[dict]:
    """Return all unique bundles matching any of the given label keys."""
    seen = set()
    bundles = []
    for label in label_keys:
        for page in range(20):
            url = f"{BASE_API}/bundlelist?labelkey={label}&per_page=10&page={page}"
            try:
                # Accept-Encoding: identity avoids a server-side bug where the
                # /bundlelist endpoint sends Content-Encoding: gzip with a
                # non-gzip body, causing requests to raise ContentDecodingError.
                data = session.get(url, timeout=30, headers={"Accept-Encoding": "identity"}).json()
            except Exception as e:
                print(f"  WARNING: API error for label {label} page {page}: {e}")
                break
            batch = data.get("bundle_list", [])
            for b in batch:
                if b["name"] not in seen:
                    seen.add(b["name"])
                    bundles.append({
                        "name": b["name"],
                        "title": b.get("title", b["name"]),
                        "updated": (b.get("dates") or {}).get("Updated on", "")[:10],
                    })
            if len(batch) < 10:
                break
        time.sleep(0.3)
    return sorted(bundles, key=lambda x: x["updated"], reverse=True)


# ---------------------------------------------------------------------------
# Bundle survey
# ---------------------------------------------------------------------------

def survey_bundle(session: requests.Session, bundle_name: str) -> dict:
    """Get page count and top-level chapter names for a bundle."""
    try:
        resp = session.get(
            f"{BASE_API}/bundle/{bundle_name}/toc?language=enus", timeout=30
        )
        resp.raise_for_status()
        toc = resp.json()
    except Exception as e:
        return {"page_count": 0, "top_chapters": [], "error": str(e)}

    pages = flatten_toc(toc)
    top_chapters = [e.get("title", "") for e in toc if e.get("title")][:12]
    time.sleep(0.3)
    return {"page_count": len(pages), "top_chapters": top_chapters, "error": None}


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def build_report(results: dict) -> str:
    lines = [
        "# ActWise Documentation Survey — SAM / CDD / IFM",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "---",
        "",
    ]

    summary_rows = []

    for product_key, product_data in results.items():
        product_name = product_data["name"]
        bundles = product_data["bundles"]

        lines.append(f"## {product_name}")
        lines.append("")

        if not bundles:
            lines.append("_No bundles found for this product._")
            lines.append("")
            summary_rows.append((product_name, 0, 0))
            continue

        total_pages = 0
        for b in bundles:
            survey = b.get("survey", {})
            page_count = survey.get("page_count", 0)
            total_pages += page_count
            updated = b["updated"] or "unknown"
            err = survey.get("error")

            lines.append(f"### {b['title']}")
            lines.append(f"- **Bundle ID:** `{b['name']}`")
            lines.append(f"- **Last Updated:** {updated}")
            if err:
                lines.append(f"- **Error:** {err}")
            else:
                lines.append(f"- **Pages:** {page_count}")
                if survey.get("top_chapters"):
                    chapters = ", ".join(survey["top_chapters"])
                    lines.append(f"- **Top Chapters:** {chapters}")
            lines.append("")

        summary_rows.append((product_name, len(bundles), total_pages))

    # Summary table
    lines.append("---")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Product | Bundles | Total Pages |")
    lines.append("|---------|---------|-------------|")
    grand_bundles = grand_pages = 0
    for name, nb, np in summary_rows:
        lines.append(f"| {name} | {nb} | {np:,} |")
        grand_bundles += nb
        grand_pages += np
    lines.append(f"| **TOTAL** | **{grand_bundles}** | **{grand_pages:,}** |")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Survey Zoomin doc structure (read-only)")
    parser.add_argument(
        "--product",
        choices=list(SURVEY_PRODUCTS.keys()),
        help="Survey a single product (omit for all)",
    )
    args = parser.parse_args()

    session = load_session()
    print("[OK] Session loaded")

    products_to_survey = (
        {args.product: SURVEY_PRODUCTS[args.product]}
        if args.product
        else SURVEY_PRODUCTS
    )

    results = {}
    for key, config in products_to_survey.items():
        print(f"\n>> {config['name']}")
        bundles = discover_bundles(session, config["label_keys"])
        print(f"   {len(bundles)} bundles found")

        for b in bundles:
            print(f"   Surveying: {b['name']}...", end=" ", flush=True)
            b["survey"] = survey_bundle(session, b["name"])
            pc = b["survey"]["page_count"]
            print(f"{pc} pages")

        results[key] = {"name": config["name"], "bundles": bundles}

    report = build_report(results)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(report, encoding="utf-8")
    print(f"\n[OK] Report saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
