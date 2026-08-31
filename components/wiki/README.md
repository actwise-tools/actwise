# wiki bucket

The **ActWise project wiki** — a detailed, browsable guide with **one page per
CLI, MCP server, AI skill, and Copilot Studio agent**, plus the ActWise goal and
ecosystem narrative. Built with [MkDocs Material](https://squidfunk.github.io/mkdocs-material/).

> Not to be confused with the repo-root `wiki/` directory, which is the
> **generated NICE product-documentation wiki** (`docenter wiki build` output from
> `raw_docs/`). This bucket is the wiki *about ActWise itself*.

## Layout

```
components/wiki/
├─ mkdocs.yml            # site config + nav
└─ content/              # Markdown source (docs_dir)
   ├─ index.md           # Home / goal
   ├─ ecosystem.md       # Ecosystem & architecture
   ├─ install.md config.md security.md glossary.md faq.md legal.md
   ├─ buckets/           # 7 bucket hub pages
   ├─ cli/               # 7 CLI pages
   ├─ mcp/               # 5 MCP-server pages
   ├─ skills/            # 9 skill pages
   ├─ agents/            # 6 Copilot Studio agent pages
   ├─ assets/            # images
   └─ kit/ (sibling of content/) — content kit: video scripts, deck outlines
```

The **content kit** (`components/wiki/kit/`) holds production inputs for
presentations, blog posts, and videos — kept outside `content/` so it isn't
published as wiki pages.

## Develop

```powershell
pip install mkdocs-material
cd components/wiki
mkdocs serve          # live preview at http://127.0.0.1:8000
mkdocs build --strict # fail on broken nav/links
```

## Publish

The wiki is published to the **public** distribution repo's GitHub Pages, served
from its `gh-pages` branch (separate from the force-pushed `main` snapshot):

**Live:** <https://actwise-tools.github.io/actwise/>

Deploy an update (build with Python 3.11, which has `mkdocs-material`):

```powershell
# one-time: add the public repo as a remote (of this private repo)
git remote add wiki-public https://github.com/actwise-tools/actwise.git

cd components/wiki
& "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe" -m mkdocs gh-deploy `
    --remote-name wiki-public --remote-branch gh-pages `
    --message "Deploy ActWise wiki {sha}" --force
```

GitHub Pages is already enabled on `actwise-tools/actwise` (source: `gh-pages`, `/`);
`gh-deploy` rebuilds `site/` and force-pushes it to that branch.

- **Portal:** alternatively build with `mkdocs build`, then serve the generated
  `site/` under the `components/portal/` site (e.g. at `/wiki`) or link it from the
  landing page.

## Regenerate the CLI reference

Each CLI page embeds a command table sourced from the live `--help`. Refresh with:

```powershell
python components/wiki/scripts/gen_cli_reference.py
```

## Public-safe

Wiki pages must not print real hosted endpoint FQDNs, IPs, or tunnel hostnames —
the wiki is intended for public publication. Use generic placeholders
("a self-hosted MCP endpoint").
