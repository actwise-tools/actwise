# ActWise eve portal (per-user DOCenter)

A [Vercel **eve**](https://www.npmjs.com/package/eve) + Next.js portal that lets
**any** end user query the live NICE Actimize documentation with **their own**
DOCenter credentials — no shared cookie, no Copilot Studio. It is the successor
front end to the static Copilot-embed portal in `../web`.

Each browser session carries a per-user identity all the way down to the
`docenter-mcp` server, which serves that user from *their own* captured DOCenter
`_SESSION` cookie. First-time users connect their account through the
[login broker](../broker/README.md) two-door page (SSO or username/password).

Everything here is **additive**: the shared-cookie path the Copilot agent uses is
untouched, and the whole per-user path is gated behind `DOCENTER_PER_USER`.

## Architecture — end-to-end per-user flow

```
Browser                     Next.js (this app)                Python services
───────                     ──────────────────                ───────────────
sign in (email)  ──POST /api/session──▶  portal_user cookie (httpOnly, 8h)
                                         │
chat  ──GET /api/token──▶  mint HS256 portal JWT (sub = user email)
      ◀── token ──────────  (PORTAL_JWT_SECRET, ~300s)
      │
      ├─ Authorization: Bearer <portal JWT> ─▶ eve HTTP channel
      │                                        caller.subject = user email
      │                                        │
      │        docenter connection mints X-DOCenter-User (HMAC,
      │        DOCENTER_USER_TOKEN_SECRET) and calls the MCP:
      │                                        ▼
      │                              docenter-mcp  (DOCENTER_PER_USER=on)
      │                              verifies X-DOCenter-User → per-user cookie
      │                              ├─ cookie present → answer + citations
      │                              └─ none → SessionRequired + login_url
      │
"Connect" ─POST /api/connect─▶  broker POST /links (X-Broker-Secret) ─▶ login_url
      ◀── login_url ────────────  window.open ─▶ broker two-door page (SSO | password)
                                                 broker captures _SESSION ─▶ per-user store
```

The browser never holds the broker secret or the HMAC secrets — the Next.js route
handlers (`/api/token`, `/api/connect`) run server-side and hold them. The portal
JWT `sub` is the only identity the browser carries, and it is re-minted per request.

## Identity plumbing (files)

| File | Role |
|------|------|
| `app/api/session/route.ts` | `GET`/`POST`/`DELETE` the lightweight `portal_user` identity cookie (email). No password check here — the real credential check is the broker door. |
| `app/api/token/route.ts` | Mints the short-lived HS256 portal JWT (`sub` = DOCenter user id) the browser sends to eve. |
| `app/api/connect/route.ts` | Proactive "Connect your DOCenter account" — server-side call to broker `POST /links`, returns a one-time `login_url`. |
| `agent/lib/portal-jwt.ts` | Mint/verify the portal JWT (HS256, `PORTAL_JWT_SECRET`). |
| `agent/lib/docenter-user-token.ts` | Mint/verify the `X-DOCenter-User` HMAC token — a byte-for-byte mirror of the Phase-3 Python verifier (`docenter_mcp/user_token.py`). |
| `agent/lib/docenter-headers.ts` | The exact header map the MCP connection sends; adds `X-DOCenter-User` **only** when a caller subject is present, else falls back to the shared-cookie path. |
| `agent/connections/docenter.ts` | Registers the `docenter-mcp` MCP connection. |
| `agent/channels/eve.ts` | eve HTTP channel; decodes the portal JWT into `caller.subject`. |
| `agent/agent.ts` | eve agent definition (model routes through the Vercel AI Gateway). |
| `agent/instructions.md` | System prompt — cite `source_url`, answer from the live portal. |
| `app/page.tsx` | The chat UI: sign-in gate, Connect button, and the `useEveAgent` chat with live progress. |

## Configuration (`.env.local`)

| Var | Required | Purpose |
|-----|----------|---------|
| `AI_GATEWAY_API_KEY` | yes (local dev) | Model credential — routes `anthropic/claude-sonnet-4.5` through the Vercel AI Gateway. |
| `PORTAL_JWT_SECRET` | yes | HS256 secret for the browser→eve portal JWT. |
| `DOCENTER_USER_TOKEN_SECRET` | yes | HMAC secret for `X-DOCenter-User`. **Must match** the MCP's `DOCENTER_USER_TOKEN_SECRET`. |
| `DOCENTER_MCP_URL` | yes | Base URL of the `docenter-mcp` server (per-user mode on). |
| `DOCENTER_BROKER_URL` | for Connect | Base URL of the login broker (`POST /links`). |
| `DOCENTER_BROKER_SECRET` | for Connect | Shared secret for broker `POST /links`. **Must match** the broker's `DOCENTER_BROKER_SECRET`. |

The three Python services must agree on the shared secrets: the MCP and this app
share `DOCENTER_USER_TOKEN_SECRET`; this app and the broker share
`DOCENTER_BROKER_SECRET`. `.env.local` is gitignored — never commit it.

## Run (local dev)

eve/Next require **Node ≥ 24**. From `components/portal/eve`:

```powershell
pnpm install            # or npm install
pnpm dev                # next dev on http://localhost:3333
```

Bring up the two Python services it depends on (per-user mode + broker):

```powershell
$env:DOCENTER_PER_USER = "1"
$env:DOCENTER_USER_TOKEN_SECRET = "<shared-with-eve>"
$env:DOCENTER_BROKER_URL = "http://127.0.0.1:8099"
$env:DOCENTER_BROKER_SECRET = "<shared-with-eve-and-broker>"
docenter-mcp                     # per-user docs MCP (:8765)

$env:DOCENTER_BROKER_SECRET = "<same-as-above>"
docenter-broker                  # login broker (:8099)
```

Then open <http://localhost:3333>, sign in with an email, click **Connect** to
authorize your DOCenter account through the broker, and ask a question.

## Progress UI (Phase 4d — "no results" fix)

**Symptom.** In `next dev`, a turn whose single MCP tool call left the NDJSON
stream **silent for ~20 s+** (a slow live-portal search/`get_page`) rendered the
first narration bubbles and then **stalled** — the final cited answer never
appeared in the browser, even though the turn completed correctly server-side.

**Root cause.** `next dev` proxies `/eve/v1/*` to the eve dev sidecar via a
`rewrites()` proxy. During a long silent gap the browser's streaming fetch through
that proxy stalls **open-but-silent** (not a disconnect), so eve's reconnect hook
— which only reopens on *disconnect* — never recovers. `node:http` clients and the
sidecar-direct connection tolerate the same gap and stream the full turn. This is
**`next dev`-only**: Vercel routes `/eve/v1/**` natively (no rewrite proxy).

**Fix** (in `app/page.tsx` + `app/globals.css`):
- `useEveAgent({ maxReconnectAttempts: 10 })` (was default 3).
- Render `dynamic-tool` parts as a live activity line — "🔍 Searching the
  documentation (N×)" — so a long tool call visibly shows progress.
- A "Working… Ns" elapsed indicator (adds "this can take a minute" after 20 s).
- Kept live partial-narration rendering.

Verified in real headless Chromium: the full multi-tool answer now renders with
progress the whole way.

## Production (Vercel) note

On Vercel, `withEve` routes `/eve/v1/**` **natively** (no dev rewrite proxy), so
the `next dev` silent-stall does not apply. Deferred for production: a real IdP
sign-in (Auth.js/Entra) whose verified subject becomes the DOCenter user id
(replacing the lightweight email cookie), Redis-backed session state, and a hosted
browser backend (Browserbase) for the SSO door.

## See also

- [Portal bucket README](../README.md)
- [Login broker](../broker/README.md)
- MCP: `docenter-mcp` (`components/docenter/docenter_mcp/`)
- Design/spec: `docs/components/docenter/2026-07-16-docenter-portal-eve-implementation-plan.md`,
  `…-docenter-mcp-per-user-session-spec.md`, `…-docenter-broker-R5-go-no-go.md`
- Auth probe: `docs/2026-07-07-portal-auth-probe.md`
