---
marp: true
theme: default
paginate: true
---

<!--
Slide outline — "ActWise overview" deck. Marp-compatible markdown.
Render to PPTX with the pptx skill / ActWise Utility agent, or `marp deck.md --pptx`.
Grounded in the wiki Home + Ecosystem pages.
-->

# ActWise

### An unofficial NICE Actimize engineering toolkit
CLIs · MCP servers · Copilot skills · Copilot Studio agents

> Unofficial — not a NICE product. Ships no NICE content. Uses your own sessions.

---

## The problem

ActOne engineers repeat the same tasks across scattered tools:

- 🔎 Search the docs portal
- 🛰️ Poke the Extend REST API
- 📊 Pull numbers from the database
- 🧰 Run server-side utilities
- ⬇️ Download install media · 🐳 stand up ActOne locally

**One install. One config layer. Terminal *and* AI agents.**

---

## Build once, surface everywhere

Every capability ships in three interchangeable forms:

| Form | Use it in |
| --- | --- |
| **CLI** | terminal, scripts, CI |
| **MCP server** | any AI agent + Copilot Studio |
| **Skill** | Claude Code / GitHub Copilot / Cursor … |

*Same Python core underneath all three.*

---

## Capability buckets

`docenter` · `ops` · `data` · `utils` · `nicedl` · `installer` (+ `core`)

Each bucket = its own CLI + MCP + skill (+ sometimes a Copilot Studio agent).

---

## Grounded & safe by design

- **No fabrication** — docs cite sources; data returns real rows; ops reports real API results
- **Read-first** — data is read-only; ops confirms before writes; utilities/installer dry-run by default
- **Your credentials, your data** — no bundled NICE content

---

## Copilot Studio experience

- **ActWise (Main)** — orchestrator routing to Docs / Data / Ops specialists
- **ActWise (Main1)** — single agent, all three MCP servers attached
- **ActWise Docs / Data / Ops / Utility** — the specialists

---

## Get started

```powershell
uv tool install git+https://github.com/vinayguda/actwise.git
docenter --help
```

**Docs, data, ops, utilities — in your terminal and your agents.**
