"""
Upload ActOne guide PDFs to SharePoint for M365 Copilot indexing.

Uploads PDFs from raw_docs/pdfs/ to the same relative folder structure under:
  Shared Documents/ActWise/actone-pdfs/
on the existing ActWiseDocumentation SharePoint site.

Uses the same cookie-based auth as upload_with_cookies.py (no OAuth needed).

Usage:
    python sharepoint/upload_pdfs.py
    python sharepoint/upload_pdfs.py --dry-run
    python sharepoint/upload_pdfs.py --fedauth <val> --rtfa <val>

Session Setup (if sharepoint-cookies.json is missing or expired):
    agent-browser --profile browser-profile open 'https://niceonline.sharepoint.com/teams/ActWiseDocumentation'
    agent-browser --profile browser-profile cookies get --json > browser-profile/sharepoint-cookies.json
"""

import argparse
import json
import sys
import time
from pathlib import Path

import requests

SITE_URL = "https://niceonline.sharepoint.com/teams/ActWiseDocumentation"
SP_FOLDER = "Shared Documents/ActWise/actone-pdfs"
PDF_DIR = Path(__file__).parent.parent / "raw_docs" / "pdfs"
COOKIES_FILE = Path(__file__).parent.parent / "browser-profile" / "sharepoint-cookies.json"

DELAY = 1.0  # PDFs are large — be polite


def load_sp_cookies(fedauth: str = None, rtfa: str = None) -> dict:
    if fedauth and rtfa:
        return {"FedAuth": fedauth, "rtFa": rtfa}

    if COOKIES_FILE.exists():
        data = json.loads(COOKIES_FILE.read_text())
        cookies = {c["name"]: c["value"] for c in data.get("data", {}).get("cookies", [])}
        fed = cookies.get("FedAuth")
        rt = cookies.get("rtFa")
        if fed and rt:
            print(f"[OK] Loaded SharePoint cookies from {COOKIES_FILE}")
            return {"FedAuth": fed, "rtFa": rt}

    print("ERROR: SharePoint cookies not found or missing FedAuth/rtFa.")
    print("\nTo get cookies:")
    print("  1. agent-browser --profile browser-profile open 'https://niceonline.sharepoint.com/teams/ActWiseDocumentation'")
    print("  2. Sign in if prompted")
    print("  3. agent-browser --profile browser-profile cookies get --json > browser-profile/sharepoint-cookies.json")
    print("  4. Re-run this script")
    sys.exit(1)


def get_request_digest(session: requests.Session) -> str:
    resp = session.post(
        f"{SITE_URL}/_api/contextinfo",
        headers={"Accept": "application/json;odata=verbose"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["d"]["GetContextWebInformation"]["FormDigestValue"]


def ensure_folder(session: requests.Session, digest: str, folder_path: str):
    """Create a SharePoint folder (no-op if already exists)."""
    resp = session.post(
        f"{SITE_URL}/_api/web/folders",
        headers={
            "Accept": "application/json;odata=verbose",
            "Content-Type": "application/json;odata=verbose",
            "X-RequestDigest": digest,
        },
        json={
            "__metadata": {"type": "SP.Folder"},
            "ServerRelativeUrl": f"/teams/ActWiseDocumentation/{folder_path}",
        },
        timeout=30,
    )
    if resp.status_code not in (200, 201, 409):
        # SharePoint may return another 4xx for "already exists"; uploads will prove access.
        return


def upload_pdf(session: requests.Session, digest: str, folder_path: str, pdf_path: Path) -> bool:
    filename = pdf_path.name
    content = pdf_path.read_bytes()
    url = (
        f"{SITE_URL}/_api/web/GetFolderByServerRelativeUrl"
        f"('/teams/ActWiseDocumentation/{folder_path}')"
        f"/Files/add(overwrite=true,url='{filename}')"
    )
    resp = session.post(
        url,
        headers={
            "Accept": "application/json;odata=verbose",
            "X-RequestDigest": digest,
            "Content-Length": str(len(content)),
        },
        data=content,
        timeout=120,  # large PDFs need time
    )
    return resp.status_code in (200, 201)


def main():
    parser = argparse.ArgumentParser(description="Upload ActOne PDFs to SharePoint")
    parser.add_argument("--fedauth", help="FedAuth cookie value")
    parser.add_argument("--rtfa", help="rtFa cookie value")
    parser.add_argument("--dry-run", action="store_true", help="List PDFs without uploading")
    args = parser.parse_args()

    pdf_files = sorted(PDF_DIR.rglob("*.pdf"))
    if not pdf_files:
        print(f"No PDFs found in {PDF_DIR}")
        print("Run: python extractor/pdf_exporter.py")
        sys.exit(1)

    print(f"Found {len(pdf_files)} PDFs in {PDF_DIR}")
    total_mb = sum(f.stat().st_size for f in pdf_files) / 1_048_576
    print(f"Total size: {total_mb:.1f} MB\n")

    if args.dry_run:
        for f in pdf_files:
            size_mb = f.stat().st_size / 1_048_576
            rel = f.relative_to(PDF_DIR)
            print(f"  {rel} ({size_mb:.1f} MB)")
        print(f"\nDestination: {SITE_URL}/{SP_FOLDER}/")
        return

    cookies = load_sp_cookies(args.fedauth, args.rtfa)
    session = requests.Session()
    session.cookies.update(cookies)
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    print("Getting SharePoint request digest...")
    try:
        digest = get_request_digest(session)
    except Exception as e:
        print(f"ERROR: Could not get request digest: {e}")
        print("SharePoint cookies may have expired — re-capture and retry.")
        sys.exit(1)

    created_folders = set()
    ensure_folder(session, digest, SP_FOLDER)
    created_folders.add(SP_FOLDER)
    print(f"Uploading to: {SITE_URL}/{SP_FOLDER}/\n")

    success = errors = 0
    for i, pdf_path in enumerate(pdf_files, 1):
        rel = pdf_path.relative_to(PDF_DIR)
        folder_path = f"{SP_FOLDER}/{'/'.join(rel.parts[:-1])}" if len(rel.parts) > 1 else SP_FOLDER
        folder_parts = folder_path.split("/")
        for depth in range(1, len(folder_parts) + 1):
            partial_folder = "/".join(folder_parts[:depth])
            if partial_folder not in created_folders:
                ensure_folder(session, digest, partial_folder)
                created_folders.add(partial_folder)

        size_mb = pdf_path.stat().st_size / 1_048_576
        print(f"[{i}/{len(pdf_files)}] {rel} ({size_mb:.1f} MB) ... ", end="", flush=True)
        try:
            ok = upload_pdf(session, digest, folder_path, pdf_path)
            if ok:
                print("OK")
                success += 1
            else:
                print("FAILED")
                errors += 1
        except requests.HTTPError as e:
            if e.response.status_code == 403:
                print("\nERROR 403: Cookies expired. Re-capture and retry.")
                sys.exit(1)
            print(f"HTTP {e.response.status_code}")
            errors += 1
        except Exception as e:
            print(f"ERROR: {e}")
            errors += 1

        time.sleep(DELAY)

    print(f"\n[OK] Done: {success} uploaded, {errors} errors")
    print(f"View: {SITE_URL}/Shared%20Documents/ActWise/actone-pdfs/")
    print("\nM365 Copilot will index the new files automatically within minutes.")


if __name__ == "__main__":
    main()
