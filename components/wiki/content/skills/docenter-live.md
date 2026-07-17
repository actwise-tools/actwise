# docenter-live

> Answer NICE Actimize product questions **strictly from the live documentation portal** by driving the `docenter-live` MCP server, always citing the source URL — never from general knowledge.

## Goal
When someone asks a NICE Actimize product question — how to configure a feature, what changed in a release, how to install a module — the answer must come from the official portal (`docs.niceactimize.com`), not the model's memory. This skill teaches an AI agent to run a faceted, version-aware search over the **live** portal, pull full page text when snippets are thin, and ground every claim in a citation URL. It is the strict, MCP-driven counterpart to the CLI-driven [actimize-docenter](actimize-docenter.md) skill.

## How it fits
This skill drives the [`docenter-mcp`](../mcp/docenter-mcp.md) server (server name `actwise-docenter-live`) in the **docenter** bucket — the live documentation pillar of ActWise. The same six read-only tools power the **ActWise Docs** Copilot Studio agent ([agent page](../agents/docs.md)); this skill carries that agent's system prompt so local IDE agents (Claude Code, the GitHub Copilot CLI, VS Code) behave identically.

## When to use it
Activate when the user:
- Asks about configuration, installation, or features of any Actimize product (ActOne, AML, SAM, IFM, CDD, RCM, CTR, etc.).
- Asks about release notes, patches, service packs, or version differences.
- Asks "does Actimize support X?" or "how do I configure Y in Z?".
- Needs an answer grounded in — and cited from — the official documentation portal.

## What it does
- Calls `search_docs` **before every documentation answer** and answers only from the returned results.
- Auto-scopes to the newest version by passing `product=<slug>`; never asks the user for a version.
- Escalates snippets to full pages: `search_docs → get_page` for procedural / "how do I…" questions.
- Discovers structure with `find_bundles`, `list_docs`, `get_toc`, and resolves slugs with `get_catalog`.
- Cites every factual claim as a clickable Markdown link, copying `portal_url` exactly (never invents or edits URLs).
- Handles empty results (retry once without filters), version transparency, corrected queries, and tool failures per fixed rules.

## Install / enable
Skills follow the open Agent Skills spec and install via the `skills` CLI:
```powershell
npx skills add https://github.com/vinayguda/actwise.git --skill docenter-live -a claude-code -g
```
Skills are instructions only — this one drives the **`docenter-mcp`** server, so install the `actwise` distribution and register the MCP endpoint (`docenter-mcp`, or `python -m uvicorn docenter_mcp.server:app --port 8765`). The tools are discovered by the agentic runtime as `docenter-live-*` (e.g. `docenter-live-search_docs`).

## Walkthrough
- *"What is Dynamic Workflow in ActOne?"* → `search_docs` (product=actone) → `get_page` on the Reference Guide → cited explanation with a version note.
- *"What's the latest ActOne release?"* → `find_bundles`/`list_docs` → `get_toc` → `get_page` on the newest Release Notes page.
- *"Reset my documentation password."* → routed as **out of scope**; no `search_docs` call.

## Limits & safety
- Strictly **read-only** — the tools only search and fetch documentation; they never touch a live ActOne system.
- Answers are confined to portal content; the skill never answers from general knowledge and never fabricates URLs.
- Depends on the `docenter-mcp` server having a valid Zoomin session (`.env` credentials / cookie); tool failures surface as a friendly retry message, not raw errors.

## See also
- MCP: [docenter-mcp](../mcp/docenter-mcp.md)
- CLI: [docenter](../cli/docenter.md)
- Bucket: [docenter](../buckets/docenter.md)
- Agent: [ActWise Docs](../agents/docs.md)
- Related skills: [actimize-docenter](actimize-docenter.md)
