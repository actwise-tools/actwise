# actimize-docs-mcp

> Offline BM25 search over the extracted NICE Actimize documentation corpus —
> the local, network-free sibling of `docenter-mcp`.

## Goal

Answer NICE Actimize product questions from the Markdown corpus that the
`extractor` wrote under `raw_docs/actone/…`, without hitting the live portal. It
builds (and caches) a BM25 index over those files, reads their YAML front matter
(`version`, `guide_type`, `page_title`, `source_url`), and returns ranked
excerpts plus the `source_url` to cite. It is **read-only**.

## How it fits

- **Bucket:** [docenter](../buckets/docenter.md).
- **Shares code with:** the same `mcp_server` package also ships an
  `actimize-docs-mcp` **CLI** search mode (`run_cli`) over the identical index —
  same corpus, same ranking, run either as an MCP server or a one-shot search.
- **Consumed by:** local IDE agents over stdio (VS Code, Claude Code, the GitHub
  Copilot CLI). It is the offline counterpart to the live
  [`docenter-mcp`](docenter-mcp.md); the Copilot Studio **ActWise Docs** agent
  uses the live server, while this one needs no portal session.

## Tools exposed

Enumerated from `components/docenter/mcp_server/server.py` — the server registers
exactly **one** tool via `@server.list_tools()`:

| Tool | What it does |
|------|--------------|
| `search_actimize_docs` | Search the extracted NICE Actimize docs (all products). Returns excerpts ranked by BM25 relevance with `source_url`s. Optional filters: `product`, `version`, `guide_type` (`implementer`, `reference`, `installation`, `release_notes`, `extend`). |

## Transport & run

**stdio.** Launch the console script from `pyproject.toml`
(`actimize-docs-mcp = "mcp_server.server:main"`):

```powershell
actimize-docs-mcp
```

Register it as a stdio server in your agent, e.g. VS Code `.vscode/mcp.json`:

```jsonc
{ "actimize-docs": { "type": "stdio", "command": "actimize-docs-mcp" } }
```

It is **self-hosted** and runs entirely locally against `raw_docs/` — no network
call, no portal auth. If the corpus is empty, populate it first with
`docenter download` / `docenter sync`.

## Safety

Strictly **read-only** — it only reads the local Markdown corpus and its front
matter. No write path, no live-system access.

## See also

- CLI: [`docenter`](../cli/docenter.md) (`docenter search --local` uses the same corpus)
- Bucket: [docenter](../buckets/docenter.md)
- Sibling server: [`docenter-mcp`](docenter-mcp.md) (live portal, HTTP)
- Agent: [ActWise Docs](../agents/docs.md)
