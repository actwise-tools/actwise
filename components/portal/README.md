# ActWise portal

A small, plain static web portal that lets NiCE team members try the **ActWise**
agent — a Microsoft Copilot Studio agent fronting three Actimize ActOne
capabilities (Docs, Data, Ops). It has two screens:

- **Landing** (`web/index.html`) — what ActWise is, the three capabilities,
  sample prompts, and a call-to-action to open the agent.
- **Agent** (`web/agent.html`) — the Copilot Studio chat canvas embedded
  full-height in an iframe.

Vanilla HTML/CSS/JS — no framework, no build step, no npm.

## Run locally

```powershell
python -m http.server 8080 --directory components/portal/web
```

Then open <http://localhost:8080/>.

## Update the agent embed

The Copilot Studio canvas URL lives in exactly one place: the `<iframe src="…">`
in `web/agent.html`. To swap it, edit that single attribute.

A republished agent keeps the same bot id, so republishing alone does **not**
require a change. Only swap the URL if the **environment** or the agent's
**schema name** changes (both are encoded in the path:
`/environments/<env-id>/bots/<schema-name>/canvas`).

## Authentication

Portal-level SSO is deferred. The portal itself is unauthenticated; the embedded
Copilot Studio canvas prompts each user for Microsoft sign-in inside the chat
frame on first use, which is sufficient for now. The natural later path is to
host the portal on Azure Static Web Apps with Microsoft Entra auth in front.

## `design-src/` provenance

`design-src/` is vendored from the "NiCE Design System" claude.ai/design project
(`colors_and_type.css`, `nicewise-styles.css`, the `*.jsx` layout references,
logo SVGs, product icons, and a brand gradient PNG). It is **reference only** and
is not served by the portal — the tokens and patterns the portal needs were
copied into `web/tokens.css` and `web/portal.css`. Do not serve `design-src/`.
