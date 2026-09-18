# Video script — "What is ActWise?" (overview, ~2:30)

> Format: screen-capture demo with voiceover. Beats are timed; **[SCREEN]** = what's
> shown, **VO** = voiceover. Grounded in the wiki Home + Ecosystem pages.

---

## 0:00–0:15 · Hook

**[SCREEN]** Terminal, then a Copilot Studio chat side-by-side.
**VO:** "Every ActOne engineer does the same things all day — search the docs, poke
the REST API, pull numbers from the database, run a utility. What if all of that were
one install, usable from your terminal *and* from an AI agent?"

**[ON-SCREEN TEXT]** ActWise — an unofficial NICE Actimize engineering toolkit.

## 0:15–0:35 · The problem

**VO:** "Today those tasks are scattered across portals, Postman, SQL clients, and
tribal knowledge. ActWise packages them as CLIs, MCP servers, and AI skills that all
share one config layer."
**[SCREEN]** The project-map table from the wiki Home page.

> ⚠️ Say clearly: "ActWise is unofficial — not a NICE product, and it ships no NICE
> content. It uses *your own* logins."

## 0:35–1:10 · Build once, surface everywhere

**VO:** "The trick is that each capability is built once and surfaced three ways."
**[SCREEN]** Ecosystem diagram (CLI / MCP / Skill row).
**VO:** "A CLI for your terminal. An MCP server so any AI agent can call it as a
tool. And a skill that teaches the agent when to use it."

## 1:10–1:55 · Live demo — docs

**[SCREEN]** Terminal.
```
docenter auth login
docenter search "blotter configuration" --product actone
```
**VO:** "Search the official docs from the command line — every result links back to
the source. The same engine powers the ActWise Docs agent in Copilot Studio, with
citations."
**[SCREEN]** Switch to Copilot Studio: ask "How do I configure a blotter?" → answer
with citation.

## 1:55–2:20 · Data + Ops, safely

**[SCREEN]** Terminal.
```
actone-data query "SELECT count(*) FROM v_acm_item WHERE status='OPEN'"
```
**VO:** "Ask for real numbers — read-only, validated, audited. And for live
operations, ActWise always confirms before it changes anything."

## 2:20–2:30 · CTA

**[ON-SCREEN TEXT]** Install: `uv tool install git+https://github.com/vinayguda/actwise.git`
**VO:** "One install. Docs, data, ops, utilities — in your terminal and your agents.
That's ActWise."

---

### Assets referenced
- Ecosystem diagram: `content/assets/actwise-architecture.png`
- Home project-map table: `content/index.md`
