# Actimize NICE Download Center

> Find and download official NICE Actimize installation packages, service packs, and patches via the `ndc` CLI over the NICE Download Center.

## Goal
Before you can install or upgrade an Actimize product you need the right artifact — the installer, service pack, or patch for a specific product and version. This skill teaches an AI agent to locate those packages on the NICE Software Download Center (`nice.subscribenet.com`, a Flexera SubscribeNet portal), confirm the exact files, and download them with MD5 verification, so the correct package is ready to hand to the Actimize Installer.

## How it fits
This skill drives the `ndc` CLI in the **nicedl** bucket — the install-package pillar. It is the counterpart to **actimize-docenter** (documentation) and the upstream feeder for **actimize-installer** and **actone-local**, which consume the packages it downloads. Rule of thumb: "how do I install X?" → docenter; "get me the installer for X" → this skill.

## When to use it
Activate when the user wants to:
- Find or download an **installer, service pack, or patch** for an Actimize product/version.
- Know which package versions are available for a product (ActOne, AIS, SAM, CDD, IFM, WL-X, connectors, etc.).
- Fetch the exact artifact to feed the Actimize Installer for an install/upgrade.
- See recently posted releases or files on the download center.

## What it does
- Checks the portal session (`ndc auth status`) and logs in with `NDC_EMAIL`/`NDC_PASSWORD` from `.env`.
- Locates packages the easy way with `ndc find <product> [version] [--variant Full|SP|Patch]` — answered from an offline catalog cache, printing the exact download command.
- Discovers via `ndc products`, `ndc product-lines`, `ndc search`, and `ndc recent`, using friendly product keys that resolve the portal's opaque `plne` ids.
- Inspects a release's files (`ndc list-files <element> --plne <plne>`) with name, size, and MD5.
- Downloads with `ndc download <element> --plne <plne> [--match SUBSTR] [--dry-run]` — files land in `packages/` (gitignored) and are MD5-verified.
- Maintains an offline catalog cache (`ndc catalog refresh|status`).

## Install / enable
Skills follow the open Agent Skills spec and install via the `skills` CLI:
```powershell
npx skills add https://github.com/vinayguda/actwise.git --skill actimize-nicedl -a claude-code -g
```
Skills are instructions only — they drive the ActWise CLIs, so install the `actwise` distribution too. This skill requires the **`ndc`** console script, plus `NDC_EMAIL`/`NDC_PASSWORD` in `.env`.

## Walkthrough
- *"I want the ActOne 10.2 full installer."* → `ndc find actone 10.2 --variant Full`, then the printed `ndc download …` command.
- *"What SAM patches are available?"* → `ndc search --product sam --variant Patch`, listing each release's `element`/`plne`.
- *"Download the Linux package for this release."* → `ndc download <element> --plne <plne> --match linux --dest packages` with MD5 verification.

## Limits & safety
- All discovery and downloads require a valid portal session; login uses credentials from `.env` (never hardcoded).
- `--dry-run` previews without downloading; real downloads are MD5-verified against the portal signature.
- Corporate TLS interception is handled via the OS trust store (`truststore`). This skill only downloads — installation is handled by **actimize-installer**.

## See also
- CLI: [../cli/ndc.md](../cli/ndc.md)
- Bucket: [../buckets/nicedl.md](../buckets/nicedl.md)
- Related skills: [actimize-installer](actimize-installer.md), [actone-local](actone-local.md), [actimize-docenter](actimize-docenter.md)
