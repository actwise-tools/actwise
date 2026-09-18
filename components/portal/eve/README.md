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

## UI design (editorial-docs redesign, 2026-07-18)

The chat surface uses the "editorial docs" direction: a centered reading column,
a mono `QUESTION` label per turn, an emerald accent rail down each answer, and
cited sources rendered as cards (title + host path). Foundations:

- **Type:** Geist Sans + Geist Mono via `next/font` (the `geist` package bundles
  the font files, so the container build needs no network fetch). Wired in
  `app/layout.tsx` as `--font-geist-sans` / `--font-geist-mono`.
- **Icons:** `@phosphor-icons/react` (no emoji): search, send, connect, sign-out,
  copy, file, sparkle, warning, spinner.
- **Tokens + theme:** one cohesive cool-neutral scale with the emerald accent
  locked across the whole page; dark theme locked; WCAG-AA contrast.
- **Motion:** restrained (answer/question rise-in, streaming cursor, spinners);
  everything collapses under `prefers-reduced-motion`.
- **Responsive:** single-file CSS (`app/globals.css`). Below 640px the topbar
  collapses to icon-only actions, suggestions go single-column, and the answer
  rail thins. Verified live on desktop + mobile through the deployed portal domain.

All UI copy is em-dash-free by design.


> **Update (2026-07-18): this stall is NOT `next dev`-only.** Self-hosting the portal
> with `next start` (the Docker container below) hits the same Next rewrite-proxy
> buffering, plus a second Cloudflare-edge buffering of the NDJSON stream. Both are
> fixed by `front-proxy.mjs` — see "Live via local Docker" below. The progress-UI
> mitigations above still apply and are still useful.

## Production (Vercel) note

On Vercel, `withEve` routes `/eve/v1/**` **natively** (no dev rewrite proxy), so
the `next dev` silent-stall does not apply. Deferred for production: a real IdP
sign-in (Auth.js/Entra) whose verified subject becomes the DOCenter user id
(replacing the lightweight email cookie), Redis-backed session state, and a hosted
browser backend (Browserbase) for the SSO door.

**Wired to the deployed AWS MCP (2026-07-18).** `.env.local` now points at the
deployed docenter MCP (`https://<deployed-mcp-host>`) with the
same shared secrets the AWS service holds (`DOCENTER_PROXY_API_KEY`,
`DOCENTER_USER_TOKEN_SECRET`, `DOCENTER_BROKER_SECRET`). TS↔Python token parity is
byte-for-byte and was verified **live** — a portal-minted `X-DOCenter-User` is
accepted by the deployed MCP and routed per-user. Running the portal locally now
exercises the real per-user path end to end. The remaining step is hosting the app
(Vercel) and pointing a domain at it; see
`docs/components/portal/2026-07-17-per-user-portal-as-built.md`.

**Live via local Docker (2026-07-18).** The portal is
now served from a local container behind the existing Cloudflare tunnel, replacing
the old static Copilot-embed portal. Bring it up with:

```powershell
# builds the image, regenerates the Fortinet-aware CA bundle, runs on host :8080
infra\tunnels\run-actwise-portal.ps1 -Build
# if the tunnels are not already running:
infra\tunnels\start-actwise-tunnels.ps1
```

The container runs **three** processes (`docker-entrypoint.sh`): the eve runtime on
4274, `next start` (UI, `/api/*`, `/healthz`) on 3333, and `front-proxy.mjs` on 8080
(published). The front proxy exists because `next start`'s baked `rewrites()` proxy
buffers the long NDJSON chat stream (hanging the browser at "Working…" even though the
run finishes server-side): it routes `/eve/v1/**` straight to the runtime and, for the
stream, relabels the response `text/event-stream` (+ `x-accel-buffering: no`) so the
**Cloudflare edge** — which buffers non-SSE bodies — flushes each chunk. Everything
else goes to Next.

> **Update (2026-07-30): http2 tunnel de-stream.** The relabel alone is not enough
> under the Fortinet VPN. QUIC/UDP 7844 is blocked, so all three Cloudflare tunnels are
> forced onto `--protocol http2`, and cloudflared's **http2 edge transport buffers the
> entire response until the origin closes the connection**. eve's chat stream is
> long-lived (it stays open after each turn, tailing for the next one), so over http2
> nothing ever reached the browser and `/chat` hung at "Researching…" while the run
> finished server-side (~20 s). Fix: `front-proxy.mjs` now scans the forwarded NDJSON and
> ends the response as soon as a **turn-boundary event** (`session.waiting`,
> `session.completed`, `session.failed` — the same events eve's per-send stream stops
> reading at) has been forwarded. cloudflared then flushes the whole buffered turn, the
> client reads to the boundary and stops, and the next `send()` opens a fresh stream.
> Trade-off: no token-by-token streaming through the tunnel (spinner → full answer at
> ~20 s); direct/local streaming and off-VPN QUIC tunnels are unaffected. See
> `docs/components/portal/2026-07-30-portal-chat-http2-destream-fix.md`.

Secrets come from `.env.local` at runtime via `--env-file`; the
non-secret `DOCENTER_MCP_URL` is a build arg (`eve build` freezes the connection URL).
Because the portal's server routes `fetch` the AWS MCP over TLS and the Fortinet SSL
VPN MITM-re-signs that cert, the run script mounts a CA bundle (Windows roots +
intermediates, incl. the Fortinet CA) as `NODE_EXTRA_CA_CERTS`. See the as-built doc
for the full topology.

## See also

- [Portal bucket README](../README.md)
- [Login broker](../broker/README.md)
- MCP: `docenter-mcp` (`components/docenter/docenter_mcp/`)
- Design/spec: `docs/components/docenter/2026-07-16-docenter-portal-eve-implementation-plan.md`,
  `…-docenter-mcp-per-user-session-spec.md`, `…-docenter-broker-R5-go-no-go.md`
- Auth probe: `docs/2026-07-07-portal-auth-probe.md`
