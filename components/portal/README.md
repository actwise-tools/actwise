# ActWise portal bucket

The ActWise docs portal — a per-user DOCenter front end that lets end users query
the live NICE Actimize documentation with their **own** credentials, gated behind
Microsoft (Entra) sign-in. The bucket holds one portal and its supporting services:

| Path | What it is |
|------|------------|
| `eve/` | **DOCenter portal** — a Vercel **eve** + Next.js app where each signed-in user queries the live docs with their *own* DOCenter account. Entra SSO (Auth.js) gates access; the verified identity flows down to `docenter-mcp`. See [`eve/README.md`](eve/README.md). |
| `broker/` | **Login broker** — mints one-time login links and drives a hosted browser (SSO) or Zoomin login API (password) to capture each user's `_SESSION` cookie into the per-user store. See [`broker/README.md`](broker/README.md). |
| `design-src/` | Vendored NiCE Design System reference (read-only; **not served**). |

> **Note (2026-07-27):** the original **static Copilot-embed portal** (`web/` +
> `server/`, Direct Line + iframe) has been **decommissioned** and removed. The eve
> portal is the sole front end, live at `actwise.nousy.ai`.

## Architecture

```
browser ─▶ eve/ (Next.js) ─▶ docenter-mcp (per-user cookie)
   │              └─"Connect"─▶ broker ─▶ captures each user's _SESSION
   └─ Entra SSO (Auth.js) ─▶ verified email = DOCenter user id
```

Every end user brings *their own* DOCenter login and gets answers served from their
own captured portal cookie. The per-user path is **additive** and gated behind
`DOCENTER_PER_USER` — with it off, the docs MCP behaves byte-for-byte as before.

### Why the per-user path exists

Per-user Entra/OBO auth directly to `docs-be.niceactimize.com` is **not viable**
(see `docs/2026-07-07-portal-auth-probe.md`). A hosted browser that the user logs
into themselves — the **broker** — is the only per-user path. See
`docs/components/docenter/2026-07-16-*` for the full design/spec.

## Run locally

See [`eve/README.md`](eve/README.md) — the portal needs the `docenter-mcp` (per-user
mode) and `docenter-broker` running alongside `next dev`.

## Public URL (Cloudflare tunnel)

The eve portal is published via a durable Cloudflare named tunnel (`actwise-portal`)
whose origin is the `actwise-eve-portal` Docker container on port 8080. Bring-up and
recovery are covered in `docs/runbooks/2026-07-10-actwise-mcp-tunnel-runbook.md` and
automated by `infra/tunnels/run-actwise-portal.ps1` + `start-actwise-tunnels.ps1`.

## Entra SSO (Auth.js)

The eve portal signs users in with their Microsoft identity via Auth.js (NextAuth v5,
Microsoft Entra ID provider). The verified email becomes the DOCenter portal user id
(replacing the lightweight email cookie). Additive and env-gated — unset the vars and
the portal falls back to the email-cookie sign-in, so local dev needs no registration.

| Env var | Purpose |
|---------|---------|
| `AUTH_MICROSOFT_ENTRA_ID_ID` | App registration client id. |
| `AUTH_MICROSOFT_ENTRA_ID_SECRET` | Client secret (confidential Web client). |
| `AUTH_MICROSOFT_ENTRA_ID_ISSUER` | `https://login.microsoftonline.com/<tenant>/v2.0`. |
| `AUTH_SECRET` | Auth.js session-cookie encryption secret. |

App registration: **Web** platform, redirect URI
`https://actwise.nousy.ai/api/auth/callback/microsoft-entra-id` (+ the local dev
`http://localhost:3333/...`). Delegated `User.Read` / OpenID scopes only — no admin
consent. **Restricting who can sign in:** set **Assignment required = Yes** on the
enterprise app and assign an Entra security group — no code change. See
[`eve/README.md`](eve/README.md) for the full wiring.

## `design-src/` provenance

`design-src/` is vendored from the "NiCE Design System" claude.ai/design project
(tokens, layout references, logo SVGs, product icons, a brand gradient PNG). It is
**reference only** and is not served by the portal.

## See also

- [`eve/README.md`](eve/README.md) — DOCenter portal (architecture, env, run)
- [`broker/README.md`](broker/README.md) — login broker (two-door SSO + password)
- `docs/components/docenter/2026-07-16-docenter-portal-eve-implementation-plan.md` — per-user plan
