# ActWise

**ActWise** is an engineering toolkit for teams that work with **NICE Actimize
ActOne**. It packages a family of command-line tools, [Model Context Protocol
(MCP)](https://modelcontextprotocol.io) servers, and AI-agent skills into a single
Python distribution so an ActOne engineer's daily tasks — search the product
documentation, drive a live ActOne REST surface, run read-only natural-language SQL
over the reporting views, run the server-side utilities, fetch official install
media, and stand up ActOne locally — all install as one tool and share one
config-resolution layer.

> ⚠️ **Unofficial & experimental (beta).** ActWise is a community project. It is
> **not** a NICE Actimize product and is **not affiliated with, endorsed by, or
> supported by NICE Ltd.** "NICE", "Actimize", and "ActOne" are trademarks of their
> respective owners and are used here only to describe interoperability. ActWise is
> provided **as-is, without warranty of any kind**; use at your own risk. It ships
> **no** NICE Actimize content, catalogs, schemas, or credentials — every tool
> retrieves what it needs at runtime using **your own** authenticated session
> against systems **you are already entitled to use**. See `NOTICE`.

## What's inside

One bucket per capability under `components/`. Each bucket owns its packages, CLI
console scripts, MCP server(s), and agent skill(s).

| Bucket      | CLI                                    | MCP servers                              | Skill(s)                              |
| ----------- | -------------------------------------- | ---------------------------------------- | ------------------------------------- |
| `core`      | —                                      | —                                        | —                                     |
| `docenter`  | `docenter`                             | `docenter-mcp`, `actimize-docs-mcp`      | `actimize-docenter`                   |
| `ops`       | `actone`                               | `actone-mcp`                             | `actone-ops`, `actone-api-suite`      |
| `data`      | `actone-data`                          | `actone-data-mcp`                        | `actone-data`                         |
| `utils`     | `actone-utils`                         | `actone-utils-mcp`                       | `actone-utils`                        |
| `nicedl`    | `ndc`                                  | —                                        | `actimize-nicedl`                     |
| `installer` | `actimize-installer`, `actone-local`   | —                                        | `actimize-installer`, `actone-local`  |

## Install

ActWise is a standard Python package. The simplest path is
[uv](https://docs.astral.sh/uv/), which provisions its own Python and an isolated
environment:

```bash
# Persistent: puts every ActWise CLI on PATH (uv-managed Python)
uv tool install actwise

# — or ad-hoc, no install:
uvx --from actwise docenter --help
```

`pip install actwise` and `pipx install actwise` also work (Python ≥ 3.10).

For browser-based sign-in and PDF export (docenter), install the Playwright browser
once:

```bash
playwright install chromium
```

## First run

This package ships **no bundled data**. On first use of a data-dependent command the
relevant CLI fetches what it needs — a documentation catalog, a schema pack, an API
spec, a product-key list — using **your own** authenticated session, and caches it
under your home directory (e.g. `~/.actwise/` or `~/.docenter/`).

```bash
docenter --help          # search & extract the product documentation portal
actone --help            # drive a live ActOne REST surface (read; writes are gated)
actone-data --help       # read-only natural-language SQL over the reporting views
actone-utils --help      # run the server-side Java utilities
ndc --help               # find & download official install media
actimize-installer --help
actone-local --help      # stand up ActOne locally on Docker
```

## MCP servers

The MCP servers are console scripts too and speak stdio, so any MCP-capable client
(GitHub Copilot, Claude, Cursor, …) can launch them locally:

```
docenter-mcp | actimize-docs-mcp | actone-mcp | actone-data-mcp | actone-utils-mcp
```

Point your MCP client at the console script; each server documents its own tools via
`tools/list`. **You self-host these** — ActWise does not run any hosted endpoint on
your behalf.

## AI-agent skills

`skills/` contains agent skills for [skills](https://www.skills.sh/)-compatible
agents (GitHub Copilot, Claude Code, Cursor, Codex, …): `actimize-docenter`,
`actimize-installer`, `actimize-nicedl`, `actone-api-suite`, `actone-data`,
`actone-local`, `actone-ops`, `actone-utils`, and `copilot-studio-browser-authoring`.

## Documentation

A full project wiki (one page per CLI, MCP server, and skill, plus the goal and
ecosystem narrative) lives under `components/wiki/` and builds with MkDocs Material:

```bash
pip install "actwise[docs]"
cd components/wiki && mkdocs serve
```

## Contributing & security

See `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and `SECURITY.md`. Please **never**
open issues, PRs, or discussions that include NICE Actimize proprietary content,
customer data, credentials, or internal endpoints.

## License

Apache-2.0 (see `LICENSE` and `NOTICE`). Any documentation, data, or schema that a
tool retrieves at runtime remains the property of its respective owner and is **not**
redistributed by this package.
