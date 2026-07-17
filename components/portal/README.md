# ActWise portal bucket

Web front ends for the ActWise agents, plus the per-user DOCenter auth path that
lets end users query the docs with their **own** credentials. The bucket holds
two portals and two Python services:

| Path | What it is |
|------|------------|
| `web/` | **Static Copilot portal** — vanilla HTML/CSS/JS shell that embeds the ActWise Copilot Studio agent in an iframe. Shared sign-in happens inside the Copilot canvas. |
| `eve/` | **Per-user DOCenter portal** — a Vercel **eve** + Next.js app where each end user queries the live docs with their *own* DOCenter account. Successor front end. See [`eve/README.md`](eve/README.md). |
| `broker/` | **Login broker** — mints one-time login links and drives a hosted browser (SSO) or Zoomin login API (password) to capture each user's `_SESSION` cookie into the per-user store. See [`broker/README.md`](broker/README.md). |
| `server/` | **FastAPI backend** for the static portal — serves `web/` and exchanges a server-held Copilot Studio Direct Line secret for short-lived Direct Line tokens (secret never reaches the browser). |
| `design-src/` | Vendored NiCE Design System reference (read-only; **not served**). |

## Two portals, two auth models

- **Static Copilot portal (`web/` + `server/`)** — one shared ActWise Copilot
  Studio agent. Every visitor uses the *same* agent; Microsoft sign-in happens
  inside the embedded Copilot canvas on first use. This is the original portal.

- **Per-user DOCenter portal (`eve/` + `broker/` + `docenter-mcp`)** — every end
  user brings *their own* DOCenter login and gets answers served from their own
  captured portal cookie. Built for a public/self-serve audience where a single
  shared cookie won't do. The whole per-user path is **additive** and gated behind
  `DOCENTER_PER_USER` — with it off, the docs MCP behaves byte-for-byte as before.

```
Static portal:   browser ─▶ web/ (static) ─▶ Copilot Studio canvas (shared agent)
Per-user portal: browser ─▶ eve/ (Next.js) ─▶ docenter-mcp (per-user cookie)
                                   └─"Connect"─▶ broker ─▶ captures each user's _SESSION
```

### Why the per-user path exists

Per-user Entra/OBO auth directly to `docs-be.niceactimize.com` is **not viable**
(no Entra app registration — see `docs/2026-07-07-portal-auth-probe.md`). A hosted
browser that the user logs into themselves — the **broker** — is the only per-user
path. See `docs/components/docenter/2026-07-16-*` for the full design/spec.

## Run locally

**Static Copilot portal:**

```powershell
python -m http.server 8080 --directory components/portal/web
# → http://localhost:8080/   (or run the FastAPI server/ for Direct Line tokens)
```

**Per-user DOCenter portal:** see [`eve/README.md`](eve/README.md) — it needs the
`docenter-mcp` (per-user mode) and `docenter-broker` running alongside `next dev`.

## Public URL (static portal, Cloudflare tunnel)

The static portal is published via a durable Cloudflare named tunnel
(`actwise-portal`) whose origin is the `actwise-portal` Docker container on port
8080. The public hostname, bring-up, and recovery are covered in
`docs/runbooks/2026-07-10-actwise-mcp-tunnel-runbook.md` and automated by
`infra/tunnels/start-actwise-tunnels.ps1`.

## Update the static agent embed

The Copilot Studio canvas URL lives in exactly one place: the `<iframe src="…">`
in `web/agent.html`. A republished agent keeps the same bot id, so republishing
alone does **not** require a change — only swap the URL if the **environment** or
the agent's **schema name** changes (both are encoded in the path
`/environments/<env-id>/bots/<schema-name>/canvas`).

## `design-src/` provenance

`design-src/` is vendored from the "NiCE Design System" claude.ai/design project
(tokens, layout references, logo SVGs, product icons, a brand gradient PNG). It is
**reference only** and is not served by the portal — the tokens the portal needs
were copied into `web/tokens.css` and `web/portal.css`. Do not serve `design-src/`.

## See also

- [`eve/README.md`](eve/README.md) — per-user DOCenter portal (architecture, env, run)
- [`broker/README.md`](broker/README.md) — login broker (two-door SSO + password)
- `docs/components/portal/HANDOFF-actwise-portal.md` — static portal build spec
- `docs/components/docenter/2026-07-16-docenter-portal-eve-implementation-plan.md` — per-user plan
