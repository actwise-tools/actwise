"""
ActWise PDF Exporter — downloads one PDF per guide from the Actimize DOCenter portal.

Calls the Zoomin server-side PDF export API, polls until the job completes,
then streams the generated PDF to disk.

Stores one PDF per bundle in the bundle-centric layout
``raw_docs_pdf/bundles/{bundle}.pdf`` (mirrors the Markdown store
``raw_docs/bundles/{bundle}/``), so shared bundles are stored once and the
existence check acts as a global already-downloaded guard.

Usage:
    python extractor/pdf_exporter.py --bundle <name>          # single bundle
    python extractor/pdf_exporter.py --dry-run                # list bundles without downloading
    python extractor/pdf_exporter.py --version all            # all hardcoded ActOne bundles

Requires:
    Authenticated session via `docenter auth login`.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests

from actwise.paths import repo_root

PORTAL_BASE = "https://docs.niceactimize.com/bundle"
API_BASE = "https://docs-be.niceactimize.com"
URL_TEMPLATE = "https://docs.niceactimize.com/bundle/[bundleId]/page/[topicIdPath]"
URL_CSH = "https://docs.niceactimize.com/csh"

_BASE = repo_root() or Path(__file__).resolve().parent.parent
for _k, _v in list(os.environ.items()):  # back-compat: DOCCENTER_* -> DOCENTER_*
    if _k.startswith("DOCCENTER_"):
        os.environ.setdefault("DOCENTER_" + _k[len("DOCCENTER_"):], _v)
_RAW_BASE = Path(os.environ.get("DOCENTER_RAW_DOCS_DIR") or (_BASE / "raw_docs"))
_PDF_BASE = Path(os.environ.get("DOCENTER_RAW_PDF_DIR") or (_BASE / "raw_docs_pdf"))
COOKIES_FILE = Path(os.environ.get("DOCENTER_COOKIES_FILE") or (_BASE / "browser-profile" / "session-cookies.json"))

PDF_POLL_INTERVAL = 3
PDF_POLL_TIMEOUT = 120

# Hardcoded bundle sets for standalone CLI use (the docenter CLI uses the catalog instead).
ACTONE_10_0_10_1_BUNDLES = [
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
]

ACTONE_10_2_BUNDLES = [
    "Actimize_ActOne_10.2_Implementer_Guide",
    "Actimize_ActOne_10.2_Reference_Guide",
    "Actimize_ActOne_10.2_Installation_Guide",
    "Actimize_ActOne_10.2_Release_Notes",
    "Actimize_ActOne_10.2_Extend_Implementer_Guide",
    "Actimize_ActOne_10.2_Performance_Test_Summary_Report",
    "Actimize_ActOne_Widget_Library_10.2_Release_Notes",
]

ACTONE_BUNDLE_SETS = {
    "10.0-10.1": ACTONE_10_0_10_1_BUNDLES,
    "10.2": ACTONE_10_2_BUNDLES,
    "all": ACTONE_10_0_10_1_BUNDLES + ACTONE_10_2_BUNDLES,
}


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def extract_version(bundle: str) -> str:
    m = re.search(r"_(\d+\.\d+)", bundle)
    return m.group(1) if m else "unknown"


def bundle_pdf_path(bundle: str, product: str = "", doc_type: str = "") -> Path:
    """Build the PDF path in the bundle-centric store.

    PDF: raw_docs_pdf/bundles/{bundle}.pdf  (one copy per bundle, product-agnostic)

    Mirrors the Markdown store (raw_docs/bundles/{bundle}/), so a shared bundle is
    stored once regardless of how many products reference it, and the
    ``pdf_path.exists()`` skip check acts as a global already-downloaded guard.
    ``product``/``doc_type`` are accepted for CLI compatibility but no longer affect
    the path (product/version live in the bundle name and the Markdown front matter).
    """
    return _PDF_BASE / "bundles" / f"{bundle}.pdf"


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def load_session() -> requests.Session:
    """Load the authenticated session from the docenter cookies file."""
    if not COOKIES_FILE.exists():
        print(f"ERROR: Cookie file not found: {COOKIES_FILE}")
        print("Run `docenter auth login` to authenticate first.")
        sys.exit(1)

    raw = COOKIES_FILE.read_bytes()
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8"
    data = json.loads(raw.decode(encoding))
    session = requests.Session()
    for c in data["data"]["cookies"]:
        session.cookies.set(c["name"], c["value"], domain=c["domain"])

    has_session = any(c["name"] == "_SESSION" for c in data["data"]["cookies"])
    if not has_session:
        print("WARNING: No _SESSION cookie found — PDF export API calls may fail.")
        print("Run `docenter auth login` to refresh your session.")

    return session


_session: requests.Session | None = None


def get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = load_session()
    return _session


# ---------------------------------------------------------------------------
# Zoomin PDF export API
# ---------------------------------------------------------------------------

def api_export_bundle_pdf(bundle: str) -> str | None:
    """POST to the Zoomin PDF export API; return the job_token."""
    url = (
        f"{API_BASE}/api/bundle/{bundle}/pdf"
        f"?_LANG=enus&with_toc=true"
        f"&url_template={quote(URL_TEMPLATE, safe='')}"
        f"&url_csh={quote(URL_CSH, safe='')}"
    )
    try:
        resp = get_session().post(url, timeout=30)
        resp.raise_for_status()
    except requests.HTTPError as e:
        body = resp.text[:200] if resp is not None else ""
        print(f"  Export API HTTP {resp.status_code}: {body}")
        return None
    except Exception as e:
        print(f"  Export API failed: {e}")
        return None

    try:
        data = resp.json()
        return data.get("job_token")
    except (json.JSONDecodeError, AttributeError):
        print(f"  Export API unexpected response: {resp.text[:200]}")
        return None


def api_poll_pdf_status(job_token: str) -> str | None:
    """Poll the PDF job status until done; return download_token or None."""
    url = f"{API_BASE}/api/pdf/{quote(job_token, safe='')}/status"
    deadline = time.time() + PDF_POLL_TIMEOUT
    while time.time() < deadline:
        try:
            resp = get_session().get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  Status poll failed: {e}")
            return None

        status = data.get("status", "")
        if status == "JobDone":
            return data.get("download_token")
        if "Error" in status or "Fail" in status:
            print(f"  PDF generation failed: {data}")
            return None
        time.sleep(PDF_POLL_INTERVAL)

    print("  PDF generation timed out")
    return None


def api_download_pdf(job_token: str, download_token: str, pdf_path: Path) -> bool:
    """Download the generated PDF via streaming HTTP request.

    The download_token is self-authenticating — no session cookie needed.
    """
    url = (
        f"{API_BASE}/api/pdf/{quote(job_token, safe='')}"
        f"/download?download_token={download_token}"
    )
    try:
        resp = requests.get(url, timeout=300, stream=True)
        resp.raise_for_status()
    except Exception as e:
        print(f"  Download failed: {e}")
        return False

    ct = resp.headers.get("content-type", "")
    if "pdf" not in ct.lower():
        print(f"  Unexpected content-type: {ct}")
        return False

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with open(pdf_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=256 * 1024):
            f.write(chunk)

    if pdf_path.stat().st_size < 1000:
        pdf_path.unlink()
        print("  Downloaded file too small, likely an error page")
        return False
    return True


# ---------------------------------------------------------------------------
# Fallback: raw PDF resource (for bundles that ship a pre-built PDF)
# ---------------------------------------------------------------------------

def download_raw_pdf_resource(bundle: str, pdf_path: Path) -> bool:
    url = f"{API_BASE}/bundle/{bundle}/raw/resource/enus/{bundle}.pdf"
    try:
        resp = get_session().get(url, timeout=120)
        resp.raise_for_status()
    except Exception as e:
        print(f"  Raw PDF download failed: {e}")
        return False

    content_type = resp.headers.get("content-type", "")
    if "pdf" not in content_type.lower() or not resp.content.startswith(b"%PDF"):
        print(f"  Raw PDF download returned unexpected content type: {content_type}")
        return False

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(resp.content)
    size_kb = pdf_path.stat().st_size // 1024
    print(f"  [OK] {pdf_path.name} ({size_kb:,} KB)")
    return True


# ---------------------------------------------------------------------------
# Main download orchestrator
# ---------------------------------------------------------------------------

def download_bundle_pdf(bundle: str, pdf_path: Path) -> bool:
    """Export a bundle PDF via the Zoomin API."""
    if bundle.endswith("_Performance_Test_Summary_Report"):
        return download_raw_pdf_resource(bundle, pdf_path)

    print("  Requesting PDF generation...")
    job_token = api_export_bundle_pdf(bundle)
    if not job_token:
        return False

    print("  Waiting for PDF generation...")
    download_token = api_poll_pdf_status(job_token)
    if not download_token:
        return False

    print("  Downloading PDF...")
    if api_download_pdf(job_token, download_token, pdf_path):
        size_kb = pdf_path.stat().st_size // 1024
        print(f"  [OK] {pdf_path.name} ({size_kb:,} KB)")
        return True

    if pdf_path.exists():
        pdf_path.unlink()
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Download DOCenter guide PDFs via the Zoomin export API"
    )
    parser.add_argument("--bundle", help="Download a single bundle by name")
    parser.add_argument(
        "--product",
        default="actone",
        help="Product slug — mirrors raw_docs_pdf/{product}/ layout",
    )
    parser.add_argument(
        "--doc-type",
        default="",
        help="Doc type for unversioned bundles (used as folder name, e.g. 'Product Info')",
    )
    parser.add_argument(
        "--version",
        choices=sorted(ACTONE_BUNDLE_SETS.keys()),
        default="10.0-10.1",
        help="ActOne bundle set to download when --bundle is omitted",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="List bundles without downloading"
    )
    args = parser.parse_args()

    bundles = [args.bundle] if args.bundle else list(ACTONE_BUNDLE_SETS[args.version])

    if args.dry_run:
        print(f"Would download {len(bundles)} PDFs -> {_PDF_BASE / 'bundles'}")
        for b in bundles:
            pdf_path = bundle_pdf_path(b, args.product, args.doc_type)
            status = "exists" if pdf_path.exists() else "missing"
            print(f"  [{status}] {pdf_path.relative_to(_PDF_BASE)}")
        return

    success = errors = skipped = 0

    for i, bundle in enumerate(bundles, 1):
        pdf_path = bundle_pdf_path(bundle, args.product, args.doc_type)
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"\n[{i}/{len(bundles)}] {bundle}")

        if pdf_path.exists() and pdf_path.stat().st_size > 10_000:
            size_kb = pdf_path.stat().st_size // 1024
            print(f"  [SKIP] Already exists ({size_kb:,} KB)")
            skipped += 1
            continue

        if download_bundle_pdf(bundle, pdf_path):
            success += 1
        else:
            errors += 1

    print(f"\n{'='*50}")
    print(f"Done: {success} downloaded, {skipped} skipped, {errors} errors")
    print(f"PDFs: {_PDF_BASE / 'bundles'}")


if __name__ == "__main__":
    main()
