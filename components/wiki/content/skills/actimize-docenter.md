# Actimize DOCenter

> Find and retrieve official NICE Actimize product documentation by driving the `docenter` CLI against the live Actimize documentation portal.

## Goal
When someone asks a NICE Actimize product question — how to configure a feature, what a product integrates with, what changed in a release — the answer usually lives in the Actimize documentation portal (`docs.niceactimize.com`). This skill teaches an AI agent to search that portal, interpret the results, cite source URLs, and pull full documentation offline when deeper reading is needed, so answers stay grounded in official docs rather than guesswork.

## How it fits
This skill drives the `docenter` CLI in the **docenter** bucket — the documentation pillar of ActWise. It can query the live Zoomin portal or a local BM25 index built from downloaded Markdown under `raw_docs/`, and the same corpus backs the `actimize-docs` MCP server (`search_actimize_docs`). It is the documentation counterpart to **actimize-nicedl** (which downloads install packages) and **actimize-installer** (which runs installers).

## When to use it
Activate when the user:
- Asks about configuration, installation, or features of any Actimize product (ActOne, SAM, CDD, IFM, X-Sight, DataIQ, etc.).
- Wants to know what integrations or third-party services a product supports.
- Asks about release notes, new features, or version differences.
- Asks "does Actimize support X?" or "how do I configure Y in Z?".
- Wants to download or browse official Actimize documentation bundles.

## What it does
- Verifies the Zoomin session with `docenter auth status` before searching (prompts for `auth login` if expired).
- Runs targeted portal searches (`docenter search "<query>"`), with online facet filters (`--product`, `--doc-version`, `--guide`) or an offline `--local` BM25 index.
- Explores the catalog: `list-categories`, `list-products`, `list-docs <key>` to discover every bundle.
- Downloads full docs offline as Markdown or PDF (`docenter download <key> --format md|pdf`).
- Keeps the corpus fresh with `docenter sync` (re-extracts only changed bundles, with a page-count republish guard).
- Builds derived knowledge (`docenter wiki build`) and publishes to SharePoint (`docenter sharepoint upload`).
- Surfaces downloadable artifacts (`.json`, `.xsd`, `.xlsx`, `.pdf`, `.zip`) and always cites reference URLs.

## Install / enable
Skills follow the open Agent Skills spec and install via the `skills` CLI:
```powershell
npx skills add https://github.com/vinayguda/actwise.git --skill actimize-docenter -a claude-code -g
```
Skills are instructions only — they drive the ActWise CLIs, so install the `actwise` distribution too. This skill requires the **`docenter`** console script (uv/pip install the repo; `playwright install chromium` once for `auth login` and PDF export).

## Walkthrough
- *"Does DataIQ Clarity support LexisNexis Bridger Insight XG?"* → runs `docenter search "LexisNexis Bridger Insight XG"`, then answers with cited portal URLs.
- *"Download the ActOne 10.1 docs so I can search them offline."* → `docenter download actone --format md --version 10.1`, then subsequent questions use `search --local`.
- *"What changed in IFM 11.2?"* → `docenter list-docs ifm --version 11.2 --type "Release Notes"` then `search` within that bundle.

## Limits & safety
- Live portal search and downloads require Zoomin SSO (`docenter auth login`); SharePoint upload needs a separate `auth sharepoint login`.
- Offline `--local` search only covers bundles already downloaded into `raw_docs/` — recall is limited until you `download`/`sync`.
- `wiki build` is a pure, network-free, citation-backed function of the local corpus. This skill only reads and republishes docs; it does not modify Actimize systems.

## See also
- CLI: [../cli/docenter.md](../cli/docenter.md)
- MCP: [../mcp/actimize-docs-mcp.md](../mcp/actimize-docs-mcp.md)
- Bucket: [../buckets/docenter.md](../buckets/docenter.md)
- Related skills: [actimize-nicedl](actimize-nicedl.md), [actimize-installer](actimize-installer.md)
