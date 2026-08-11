"""
SharePoint upload using browser cookies — no admin consent, no OAuth.

Uses the same session-cookie approach as the Zoomin extractor.

Setup:
  1. Open https://niceonline.sharepoint.com/teams/ActWiseDocumentation in Edge/Chrome
  2. Sign in with your NICE account
  3. Run: agent-browser --profile browser-profile open https://niceonline.sharepoint.com/teams/ActWiseDocumentation
     Then: agent-browser cookies get --json > browser-profile/sharepoint-cookies.json
  4. Run: py sharepoint/upload_with_cookies.py

Or pass cookies manually via --fedauth and --rtfa flags.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import requests

SITE_URL = "https://niceonline.sharepoint.com/teams/ActWiseDocumentation"
SP_FOLDER = "Shared Documents/ActWise"
RAW_DOCS_DIR = Path(__file__).parent.parent / "raw_docs"
COOKIES_FILE = Path(__file__).parent.parent / "browser-profile" / "sharepoint-cookies.json"

DELAY = 0.2


def load_sp_cookies(fedauth: str = None, rtfa: str = None) -> dict:
    """Load SharePoint auth cookies from file or CLI args."""
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

    print("ERROR: SharePoint cookies not found.")
    print("\nTo get cookies:")
    print("  1. agent-browser --profile browser-profile open 'https://niceonline.sharepoint.com/teams/ActWiseDocumentation'")
    print("  2. Sign in if prompted")
    print("  3. agent-browser cookies get --json > browser-profile/sharepoint-cookies.json")
    print("  4. Re-run this script")
    sys.exit(1)


def get_request_digest(session: requests.Session) -> str:
    """Get SharePoint form digest value needed for writes."""
    resp = session.post(
        f"{SITE_URL}/_api/contextinfo",
        headers={"Accept": "application/json;odata=verbose"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["d"]["GetContextWebInformation"]["FormDigestValue"]


def ensure_folder(session: requests.Session, digest: str, folder_path: str):
    """Create folder if it doesn't exist (ignores error if already exists)."""
    url = f"{SITE_URL}/_api/web/folders"
    session.post(
        url,
        headers={
            "Accept": "application/json;odata=verbose",
            "Content-Type": "application/json;odata=verbose",
            "X-RequestDigest": digest,
        },
        json={"__metadata": {"type": "SP.Folder"}, "ServerRelativeUrl": f"/teams/ActWiseDocumentation/{folder_path}"},
        timeout=30,
    )  # ignore errors — folder may already exist


def upload_file(session: requests.Session, digest: str, folder_path: str, filename: str, content: bytes) -> bool:
    """Upload a single file via SharePoint REST API."""
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
        timeout=60,
    )
    return resp.status_code in (200, 201)


def main():
    parser = argparse.ArgumentParser(description="Upload ActWise docs to SharePoint using browser cookies")
    parser.add_argument("--fedauth", help="FedAuth cookie value (alternative to cookies file)")
    parser.add_argument("--rtfa", help="rtFa cookie value (alternative to cookies file)")
    parser.add_argument("--dry-run", action="store_true", help="List files without uploading")
    args = parser.parse_args()

    cookies = load_sp_cookies(args.fedauth, args.rtfa)

    session = requests.Session()
    session.cookies.update(cookies)
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    md_files = sorted(RAW_DOCS_DIR.rglob("*.md"))
    if not md_files:
        print(f"No markdown files found under {RAW_DOCS_DIR}")
        sys.exit(1)

    print(f"Found {len(md_files)} files to upload to SharePoint")

    if args.dry_run:
        for f in md_files[:10]:
            print(f"  {f.relative_to(RAW_DOCS_DIR)}")
        if len(md_files) > 10:
            print(f"  ... and {len(md_files) - 10} more")
        return

    # Get form digest for write operations
    print("Getting SharePoint request digest...")
    try:
        digest = get_request_digest(session)
    except Exception as e:
        print(f"ERROR: Could not get request digest: {e}")
        print("Your SharePoint cookies may have expired. Re-run the agent-browser cookie capture.")
        sys.exit(1)

    # Track folders created to avoid redundant calls
    created_folders = set()
    success = errors = 0

    for i, md_file in enumerate(md_files, 1):
        rel = md_file.relative_to(RAW_DOCS_DIR)
        parts = rel.parts  # e.g. ('actone', 'v10.1', 'Actimize_ActOne_...', 'page.md')
        folder_path = f"{SP_FOLDER}/{'/'.join(parts[:-1])}"
        filename = parts[-1]

        # Ensure parent folder exists (once per unique folder)
        if folder_path not in created_folders:
            ensure_folder(session, digest, folder_path.replace("Shared Documents/", ""))
            created_folders.add(folder_path)

        try:
            ok = upload_file(session, digest, folder_path, filename, md_file.read_bytes())
            if ok:
                success += 1
            else:
                errors += 1
        except requests.HTTPError as e:
            if e.response.status_code == 403:
                print("\nERROR 403: Cookies expired. Re-capture and retry.")
                sys.exit(1)
            errors += 1
        except Exception as e:
            errors += 1

        if i % 100 == 0:
            print(f"  {i}/{len(md_files)} uploaded ({errors} errors)...")
            # Refresh digest every 500 files (they expire after ~30 min)
            if i % 500 == 0:
                digest = get_request_digest(session)

        time.sleep(DELAY)

    print(f"\n[OK] Done: {success} uploaded, {errors} errors")
    print(f"View at: {SITE_URL}/Shared%20Documents/ActWise/")


if __name__ == "__main__":
    main()
