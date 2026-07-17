"""
ActWise Extractor - pulls Actimize documentation from the Zoomin REST API
and saves each page as a Markdown file with YAML front matter.

Usage:
    python extractor.py                          # extract all ActOne Phase 1 bundles
    python extractor.py --product sam            # extract SAM 10.1 core bundles
    python extractor.py --bundle <bundle_name>   # extract a single bundle
    python extractor.py --dry-run                # list pages without downloading

Requires: browser-profile/session-cookies.json (run auth_refresh.py if expired)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import sys
from pathlib import Path

from actwise.paths import repo_root


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_API = "https://docs-be.niceactimize.com/api"
_BASE = repo_root() or Path(__file__).resolve().parent.parent
for _k, _v in list(os.environ.items()):  # back-compat: DOCCENTER_* -> DOCENTER_*
    if _k.startswith("DOCCENTER_"):
        os.environ.setdefault("DOCENTER_" + _k[len("DOCCENTER_"):], _v)
COOKIES_FILE = Path(os.environ.get("DOCENTER_COOKIES_FILE") or (_BASE / "browser-profile" / "session-cookies.json"))
RAW_DOCS_DIR = Path(os.environ.get("DOCENTER_RAW_DOCS_DIR") or (_BASE / "raw_docs"))

DELAY_SECONDS = 0.5  # polite delay between API calls

# Product bundle sets in extraction priority order
PRODUCTS = {
    "actone": {
        "name": "ActOne",
        "output_dir": RAW_DOCS_DIR / "actone",
        "bundles": [
            "Actimize_ActOne_10.1_Implementer_Guide",
            "Actimize_ActOne_10.1_Reference_Guide",
            "Actimize_ActOne_10.1_Installation_Guide",
            "Actimize_ActOne_10.1_Release_Notes",
            "Actimize_ActOne_10.1_Extend_Implementer_Guide",
            "Actimize_ActOne_QAS_10.1.4_User_Guide",
            "Actimize_ActOne_10.0_Implementer_Guide",
            "Actimize_ActOne_10.0_Reference_Guide",
            "Actimize_ActOne_10.0_Installation_Guide",
            "Actimize_ActOne_10.0_Release_Notes",
            "Actimize_ActOne_10.0_Self_Developer_Guide",
        ],
    },
    "actone-10.2": {
        "name": "ActOne",
        "output_dir": RAW_DOCS_DIR / "actone",
        "bundles": [
            "Actimize_ActOne_10.2_Implementer_Guide",
            "Actimize_ActOne_10.2_Reference_Guide",
            "Actimize_ActOne_10.2_Installation_Guide",
            "Actimize_ActOne_10.2_Release_Notes",
            "Actimize_ActOne_10.2_Extend_Implementer_Guide",
            "Actimize_ActOne_10.2_Performance_Test_Summary_Report",
            "Actimize_ActOne_Widget_Library_10.2_Release_Notes",
        ],
    },
    "sam": {
        "name": "SAM",
        "output_dir": RAW_DOCS_DIR / "sam",
        "bundles": [
            "Actimize_AML_SAM_10.1.0_Implementer_Guide",
            "Actimize_AML_SAM_10.1.0_User_Guide",
            "Actimize_AML_SAM_10.1.0_Solution_Guide",
            "Actimize_AML_SAM_10.1.0_Installation_Guide",
        ],
    },
    "cdd": {
        "name": "CDD",
        "output_dir": RAW_DOCS_DIR / "cdd",
        "bundles": [
            "Actimize_AML_CDD_10.4.0_Implementer_Guide",
            "Actimize_AML_CDD_10.4.0_User_Guide",
            "Actimize_AML_CDD_10.4.0_Installation_Guide",
        ],
    },
    "xse-sam": {
        "name": "X-Sight Enterprise SAM",
        "output_dir": RAW_DOCS_DIR / "xse-sam",
        "bundles": [
            "Actimize_X-Sight_Enterprise_SAM_User_Guide",
            "Actimize_X-Sight_Enterprise_SAM_Administrator_Guide",
            "Actimize_X-Sight_Enterprise_SAM_Solution_Guide",
            "Actimize_X-Sight_Enterprise_SAM_Self-Development_Guide",
        ],
    },
    "xse-cdd": {
        "name": "X-Sight Enterprise CDD",
        "output_dir": RAW_DOCS_DIR / "xse-cdd",
        "bundles": [
            "Actimize_X-Sight_Enterprise_CDD_User_Guide",
            "Actimize_X-Sight_Enterprise_CDD_Administrator_Guide",
            "Actimize_X-Sight_Enterprise_CDD_Onboarding_and_Integration_Guide",
            "Actimize_X-Sight_Enterprise_CDD_Self-Developer_Guide",
        ],
    },
    "xse-fraud": {
        "name": "X-Sight Enterprise Fraud",
        "output_dir": RAW_DOCS_DIR / "xse-fraud",
        "bundles": [
            "Actimize_X-Sight_Enterprise_Fraud_Self-Developer_Guide",
            "Actimize_X-Sight_Enterprise_Retail_Banking_Fraud_User_Guide",
            "Actimize_X-Sight_Enterprise_Commercial_Banking_Fraud_User_Guide",
            "Actimize_X-Sight_Enterprise_Fraud_Administrator_Guide",
            "Actimize_X-Sight_Enterprise_Fraud_Onboarding_and_Integration_Guide",
        ],
    },
    "ifm": {
        "name": "Integrated Fraud Management (IFM)",
        "output_dir": RAW_DOCS_DIR / "ifm",
        "bundles": [
            # 11.2
            "Actimize_Fraud_IFM_11.2_Analytics_Guide_-_Internal_Only",
            "Actimize_Fraud_IFM_11.2_AMP_KeyIndicators_and_AIS_Variables",
            "Actimize_Fraud_IFM_11.2_Profiles_and_Profile_Validation",
            "Actimize_Fraud_IFM_11.2_Sizing_Calculator_for_On-Prem",
            "Actimize_Fraud_IFM_11.2_Internal_Master_Feed",
            "Actimize_Fraud_IFM_11_2_Performance_Test_Summary_Report",
            "Actimize_Fraud_IFM_11_2_SP1_Performance_Test_Summary_Report",
            # 11.1
            "Actimize_Fraud_IFM_11.1_Analytics_Guide_-_Internal_Only",
            "Actimize_Fraud_IFM_11.1_AMP_KeyIndicators_and_AIS_Variables",
            "Actimize_Fraud_IFM_11.1_Profiles_and_Profile_Validation",
            "Actimize_Fraud_IFM_11.1_Sizing_Calculator_for_Cassandra",
            "Actimize_Fraud_IFM_11.1_Sizing_Calculator_for_On-Prem",
            "Actimize_Fraud_IFM_11.1_Solution_Model_Tuning_Report_Template",
            "Actimize_Fraud_IFM_11.1_Internal_Master_Feed",
            "Actimize_Fraud_IFM_11_1_Performance_Test_Summary_Report",
            "Actimize_Fraud_IFM_11_1_SP1_Performance_Test_Summary_Report",
            "Actimize_Fraud_IFM_11_1_SP2_Performance_Test_Summary_Report",
            # 11.0
            "Actimize_Fraud_IFM_11.0_Analytics_Guide_-_Internal_Only",
            "Actimize_Fraud_IFM_11.0_AMP_KeyIndicators_and_AIS_Variables",
            "Actimize_Fraud_IFM_11.0_Profiles_and_Profile_Validation",
            "Actimize_Fraud_IFM_11.0_Sizing_Calculator_for_Cassandra",
            "Actimize_Fraud_IFM_11.0_Sizing_Calculator_for_On-Prem",
            "Actimize_Fraud_IFM_11.0_Solution_Model_Tuning_Report_Template",
            "Actimize_Fraud_IFM_11.0_Performance_Test_Summary_Report",
            # IFM-X
            "Actimize_Fraud_IFM-X_AMP_Upgrade_Utility_Guide",
        ],
    },
}

# Patch note label keys — fetched dynamically
PATCH_LABEL_KEYS = [
    "product-platform-actone-basic-1010",
    "product-platform-actone-basic-1000",
]


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def load_session() -> requests.Session:
    import requests

    if not COOKIES_FILE.exists():
        print(f"ERROR: Cookie file not found: {COOKIES_FILE}")
        print("Run auth_refresh.py to re-authenticate.")
        sys.exit(1)

    raw = COOKIES_FILE.read_bytes()
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8"
    data = json.loads(raw.decode(encoding))
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
# TOC
# ---------------------------------------------------------------------------

def flatten_toc(entries: list) -> list[dict]:
    """Recursively flatten nested TOC into [{title, path}]."""
    pages = []
    for entry in entries:
        if entry.get("nav_path"):
            pages.append({
                "title": entry.get("title", ""),
                "path": entry["nav_path"],
            })
        pages.extend(flatten_toc(entry.get("childEntries", [])))
    return pages


def get_toc(session: requests.Session, bundle: str) -> list[dict]:
    url = f"{BASE_API}/bundle/{bundle}/toc?language=enus"
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return flatten_toc(resp.json())


# ---------------------------------------------------------------------------
# Page extraction
# ---------------------------------------------------------------------------

def extract_version(bundle_name: str) -> str:
    m = re.search(r"_(\d+\.\d+)", bundle_name)
    return m.group(1) if m else "unknown"


def html_to_markdown(html: str) -> str:
    import html2text

    converter = html2text.HTML2Text()
    converter.ignore_links = False
    converter.ignore_images = False
    converter.body_width = 0        # no wrapping
    converter.unicode_snob = True
    return converter.handle(html)


def fetch_page(session: requests.Session, bundle: str, nav_path: str) -> dict:
    url = f"{BASE_API}/bundle/{bundle}/page/{nav_path}"
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def page_slug(nav_path: str) -> str:
    base = Path(nav_path).stem
    digest = hashlib.sha1(nav_path.encode("utf-8")).hexdigest()[:8]
    return f"{base}_{digest}"


def build_front_matter(product_name: str, bundle: str, page_data: dict, nav_path: str) -> str:
    version = extract_version(bundle)
    title = page_data.get("title", "")
    updated = (page_data.get("dates") or {}).get("Updated on", "")[:10]
    updated_full = (page_data.get("dates") or {}).get("Updated on", "")
    source_url = f"https://docs.niceactimize.com/bundle/{bundle}/page/{nav_path}"

    # Derive guide type from bundle name
    guide_type = "unknown"
    for keyword in ["Implementer_Guide", "Reference_Guide", "Installation_Guide",
                    "Release_Notes", "Extend_Implementer", "Self_Developer",
                    "Self-Development_Guide", "Self-Developer_Guide", "User_Guide",
                    "Solution_Guide", "Administrator_Guide",
                    "Onboarding_and_Integration_Guide",
                    "Performance_Test_Summary_Report", "Widget_Library", "QAS"]:
        if keyword.lower() in bundle.lower():
            guide_type = keyword.replace("_", " ")
            break

    okf_type = "Documentation Topic" if guide_type == "unknown" else guide_type
    safe_title = title.replace(chr(34), chr(39))

    return (
        "---\n"
        f"product: {product_name}\n"
        f"version: \"{version}\"\n"
        f"bundle: {bundle}\n"
        f"guide_type: {guide_type}\n"
        f"page_title: \"{safe_title}\"\n"
        f"source_url: {source_url}\n"
        f"updated: \"{updated}\"\n"
        f"type: \"{okf_type}\"\n"
        f"title: \"{safe_title}\"\n"
        f"resource: {source_url}\n"
        f"tags: [\"{product_name}\", \"{version}\", \"{bundle}\", \"{guide_type}\"]\n"
        f"timestamp: \"{updated_full}\"\n"
        "---\n\n"
    )


# ---------------------------------------------------------------------------
# Bundle extraction
# ---------------------------------------------------------------------------

def extract_bundle(
    session: requests.Session,
    product_name: str,
    output_dir: Path,
    bundle: str,
    dry_run: bool = False,
    doc_type: str = "",
) -> int:
    print(f"\n>> Bundle: {bundle}")
    # Bundle-centric store: one copy per bundle, shared across every product that
    # references it. Product/version live in front matter, not the path. The
    # existing per-page resume guard (out_path.exists()) therefore also acts as a
    # GLOBAL already-extracted guard — a shared bundle pulled under one product is
    # not re-downloaded under another.
    out_base = RAW_DOCS_DIR / "bundles" / bundle

    try:
        pages = get_toc(session, bundle)
    except Exception as e:
        print(f"  ERROR fetching TOC: {e}")
        return 0

    print(f"  {len(pages)} pages found")

    if dry_run:
        for p in pages[:5]:
            print(f"    - {p['title']}")
        if len(pages) > 5:
            print(f"    ... and {len(pages) - 5} more")
        return len(pages)

    success = 0
    errors = 0

    for i, page in enumerate(pages, 1):
        nav_path = page["path"]
        slug = page_slug(nav_path)

        out_path = out_base / f"{slug}.md"

        # Skip if already extracted (resume support)
        if out_path.exists():
            success += 1
            continue

        try:
            page_data = fetch_page(session, bundle, nav_path)
            topic_html = page_data.get("topic_html", "")

            if not topic_html.strip():
                continue

            markdown = html_to_markdown(topic_html)
            front_matter = build_front_matter(product_name, bundle, page_data, nav_path)

            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(front_matter + markdown, encoding="utf-8")
            success += 1

            if i % 25 == 0:
                print(f"  {i}/{len(pages)} pages extracted...")

            time.sleep(DELAY_SECONDS)

        except KeyboardInterrupt:
            print("\n  Interrupted — progress saved, re-run to resume.")
            sys.exit(0)
        except Exception as e:
            print(f"  ERROR on {nav_path}: {e}")
            errors += 1
            time.sleep(1)

    print(f"  [OK] {success} pages saved, {errors} errors -> {out_base}")
    return success


# ---------------------------------------------------------------------------
# Patch notes discovery
# ---------------------------------------------------------------------------

def fetch_patch_bundles(session: requests.Session) -> list[str]:
    """Discover all patch release note bundles for ActOne 10.x."""
    bundles = []
    actone_bundles = PRODUCTS["actone"]["bundles"]
    for label in PATCH_LABEL_KEYS:
        for page in range(10):
            url = f"{BASE_API}/bundlelist?labelkey={label}&per_page=10&page={page}"
            data = session.get(url, timeout=30, headers={"Accept-Encoding": "identity"}).json()
            batch = data.get("bundle_list", [])
            if not batch:
                break
            for b in batch:
                name = b["name"]
                if "Patch" in name and name not in bundles and name not in actone_bundles:
                    bundles.append(name)
            if len(batch) < 10:
                break

    # Deduplicate, sort
    return sorted(set(bundles))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Extract Actimize docs from Zoomin API")
    parser.add_argument(
        "--product",
        default="actone",
        help="Product key (default: actone). Any slug accepted when --bundle is given.",
    )
    parser.add_argument("--bundle", help="Extract a single named bundle")
    parser.add_argument("--include-patches", action="store_true",
                        help="Also extract ActOne patch release notes")
    parser.add_argument("--doc-type", default="",
                        help="Doc type label (e.g. 'Product Info'); used as folder name for unversioned bundles")
    parser.add_argument("--dry-run", action="store_true",
                        help="List pages without downloading")
    parser.add_argument("--resume", action="store_true", default=True,
                        help="Skip already-extracted pages (default: on)")
    args = parser.parse_args()

    if args.product in PRODUCTS:
        product = PRODUCTS[args.product]
        product_name = product["name"]
        output_dir = product["output_dir"]
    elif args.bundle:
        product_name = args.product
        output_dir = RAW_DOCS_DIR / args.product
    else:
        parser.error(
            f"unknown product '{args.product}' (known: {', '.join(sorted(PRODUCTS))}). "
            "Pass --bundle to extract an arbitrary product."
        )

    session = load_session()
    print("[OK] Session loaded")

    if args.bundle:
        bundles = [args.bundle]
    else:
        bundles = list(product["bundles"])
        if args.include_patches:
            if args.product != "actone":
                print("WARNING: --include-patches is currently supported for ActOne only.")
            print("\nDiscovering patch bundles...")
            patch_bundles = fetch_patch_bundles(session)
            print(f"Found {len(patch_bundles)} patch bundles")
            bundles.extend(patch_bundles)

    total_pages = 0
    for bundle in bundles:
        total_pages += extract_bundle(
            session,
            product_name,
            output_dir,
            bundle,
            dry_run=args.dry_run,
            doc_type=args.doc_type,
        )

    print(f"\n{'DRY RUN - ' if args.dry_run else ''}Done. Total pages: {total_pages}")
    print(f"Output: {RAW_DOCS_DIR / 'bundles'}")


if __name__ == "__main__":
    main()
