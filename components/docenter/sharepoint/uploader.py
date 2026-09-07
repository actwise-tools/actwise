"""
ActWise SharePoint Uploader — uploads extracted MD files to a SharePoint
document library so M365 Copilot can ground answers from them.

Usage:
    python uploader.py --setup          # discover site_id and drive_id (run once)
    python uploader.py                  # upload all raw_docs/**/*.md
    python uploader.py --dry-run        # list files without uploading

Authentication: device code flow (browser pop-up, no Azure admin needed).
Token is cached in sharepoint/.token_cache.json for reuse.

Setup:
    1. Create a SharePoint site named "ActWise Documentation" at your tenant
    2. Run: python uploader.py --setup
    3. Copy the site_id and drive_id into this file (SITE_ID / DRIVE_ID below)
    4. Run: python uploader.py
"""

import argparse
import json
import sys
import time
from pathlib import Path

import msal
import requests

# ---------------------------------------------------------------------------
# Config — fill in after running --setup
# ---------------------------------------------------------------------------

TENANT_ID = "7123dabd-0e87-4da9-9cb9-b7ec82011aad"
SITE_ID   = ""      # from --setup output
DRIVE_ID  = ""      # from --setup output

# Microsoft Graph Explorer public client — no app registration needed
CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
SCOPES    = ["Files.ReadWrite"]  # No admin consent needed — uploads to your OneDrive
# SCOPES  = ["Sites.ReadWrite.All", "Files.ReadWrite.All"]  # Uncomment if admin approves

GRAPH_BASE   = "https://graph.microsoft.com/v1.0"
TOKEN_CACHE  = Path(__file__).parent / ".token_cache.json"
RAW_DOCS_DIR = Path(__file__).parent.parent / "raw_docs"
SP_FOLDER    = "ActWise"       # top-level folder inside the drive root

DELAY_SECONDS = 0.3            # polite delay between uploads

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def build_msal_app() -> msal.PublicClientApplication:
    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE.exists():
        cache.deserialize(TOKEN_CACHE.read_text())

    app = msal.PublicClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        token_cache=cache,
    )
    return app, cache


def get_token() -> str:
    if not TENANT_ID:
        print("ERROR: Set TENANT_ID in uploader.py first.")
        print("Find it at: https://portal.azure.com → Azure Active Directory → Overview")
        sys.exit(1)

    app, cache = build_msal_app()

    # Try silent (cached) token first
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            TOKEN_CACHE.write_text(cache.serialize())
            return result["access_token"]

    # Device code flow
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        print(f"ERROR initiating device flow: {flow}")
        sys.exit(1)

    print("\n" + "="*60)
    print(flow["message"])
    print("="*60 + "\n")

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        print(f"ERROR acquiring token: {result.get('error_description')}")
        sys.exit(1)

    TOKEN_CACHE.write_text(cache.serialize())
    print("✓ Authenticated and token cached\n")
    return result["access_token"]


# ---------------------------------------------------------------------------
# Graph API helpers
# ---------------------------------------------------------------------------

def graph_get(token: str, path: str) -> dict:
    resp = requests.get(
        f"{GRAPH_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def upload_file(token: str, sp_path: str, content: bytes) -> bool:
    """Upload a single file. Returns True on success."""
    url = f"{GRAPH_BASE}/sites/{SITE_ID}/drives/{DRIVE_ID}/root:/{sp_path}:/content"
    resp = requests.put(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "text/markdown; charset=utf-8",
        },
        data=content,
        timeout=60,
    )
    return resp.status_code in (200, 201)


# ---------------------------------------------------------------------------
# Setup: discover site_id and drive_id
# ---------------------------------------------------------------------------

def run_onedrive_upload(token: str, dry_run: bool = False):
    """Upload to personal OneDrive — no admin consent needed."""
    md_files = sorted(RAW_DOCS_DIR.rglob("*.md"))
    if not md_files:
        print(f"No markdown files found under {RAW_DOCS_DIR}")
        sys.exit(1)

    print(f"Uploading {len(md_files)} files to OneDrive/ActWise/...")
    if dry_run:
        for f in md_files[:5]:
            print(f"  {f.relative_to(RAW_DOCS_DIR)}")
        return

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "text/markdown; charset=utf-8"}
    success = errors = 0

    for i, md_file in enumerate(md_files, 1):
        rel_path = md_file.relative_to(RAW_DOCS_DIR)
        od_path = f"ActWise/{rel_path}".replace("\\", "/")
        url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{od_path}:/content"

        try:
            resp = requests.put(url, headers=headers, data=md_file.read_bytes(), timeout=60)
            if resp.status_code in (200, 201):
                success += 1
            else:
                errors += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            errors += 1

        if i % 100 == 0:
            print(f"  {i}/{len(md_files)} ({errors} errors)...")
        time.sleep(0.2)

    print(f"\n[OK] {success} uploaded, {errors} errors")
    print("View at: https://onedrive.live.com or https://niceonline-my.sharepoint.com")


def run_setup(token: str):
    # Direct lookup by hostname + path (works for /teams/ and /sites/ URLs)
    print("Looking up site: niceonline.sharepoint.com/teams/ActWiseDocumentation")
    try:
        direct = graph_get(token, "/sites/niceonline.sharepoint.com:/teams/ActWiseDocumentation")
        sites = [direct]
    except Exception:
        print("Direct lookup failed, falling back to search...")
        data = graph_get(token, "/sites?search=ActWise")
        sites = data.get("value", [])

    if not sites:
        print("No sites found with 'ActWise' in the name.")
        print("Create the site first: go to SharePoint home → + Create site → Team site → 'ActWise Documentation'")
        return

    print(f"\nFound {len(sites)} site(s):\n")
    for site in sites:
        site_id = site["id"]
        print(f"  Name:    {site.get('displayName', site.get('name'))}")
        print(f"  site_id: {site_id}")
        print(f"  URL:     {site.get('webUrl')}\n")

        # Get drives for this site
        drives_data = graph_get(token, f"/sites/{site_id}/drives")
        for drive in drives_data.get("value", []):
            print(f"    Drive: {drive['name']}  drive_id: {drive['id']}")

    print("\nCopy the site_id and drive_id into SITE_ID / DRIVE_ID at the top of uploader.py")


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def run_upload(token: str, dry_run: bool = False):
    if not SITE_ID or not DRIVE_ID:
        print("ERROR: Set SITE_ID and DRIVE_ID in uploader.py first.")
        print("Run: python uploader.py --setup")
        sys.exit(1)

    md_files = sorted(RAW_DOCS_DIR.rglob("*.md"))
    if not md_files:
        print(f"No markdown files found under {RAW_DOCS_DIR}")
        print("Run the extractor first: python extractor/extractor.py")
        sys.exit(1)

    print(f"Found {len(md_files)} markdown files to upload")
    if dry_run:
        for f in md_files[:10]:
            print(f"  {f.relative_to(RAW_DOCS_DIR)}")
        if len(md_files) > 10:
            print(f"  ... and {len(md_files) - 10} more")
        return

    success = errors = skipped = 0

    for i, md_file in enumerate(md_files, 1):
        rel_path = md_file.relative_to(RAW_DOCS_DIR)
        sp_path = f"{SP_FOLDER}/{rel_path}".replace("\\", "/")

        try:
            content = md_file.read_bytes()
            ok = upload_file(token, sp_path, content)
            if ok:
                success += 1
            else:
                errors += 1
                print(f"  WARN: unexpected response for {sp_path}")
        except requests.exceptions.HTTPError as e:
            print(f"  ERROR {e.response.status_code} on {sp_path}: {e}")
            errors += 1
            if e.response.status_code == 401:
                print("  Token expired — re-run the script to re-authenticate")
                sys.exit(1)
        except Exception as e:
            print(f"  ERROR: {e}")
            errors += 1

        if i % 50 == 0:
            print(f"  {i}/{len(md_files)} uploaded ({errors} errors)...")

        time.sleep(DELAY_SECONDS)

    print(f"\n✓ Upload complete: {success} succeeded, {errors} errors, {skipped} skipped")
    print(f"View at: https://your-tenant.sharepoint.com/sites/ActWiseDocumentation/Shared%20Documents/{SP_FOLDER}/")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Upload ActWise MD files to SharePoint")
    parser.add_argument("--setup", action="store_true",
                        help="Discover site_id and drive_id (run once after creating SharePoint site)")
    parser.add_argument("--onedrive", action="store_true",
                        help="Upload to personal OneDrive instead of SharePoint (no admin consent needed)")
    parser.add_argument("--dry-run", action="store_true",
                        help="List files without uploading")
    args = parser.parse_args()

    token = get_token()

    if args.setup:
        run_setup(token)
    elif args.onedrive:
        run_onedrive_upload(token, dry_run=args.dry_run)
    else:
        run_upload(token, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
