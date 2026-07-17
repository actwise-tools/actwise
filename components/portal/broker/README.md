# DOCenter login broker (Phase 4)

Turns the per-user MCP's `SessionRequired` into a real per-user login. The broker
mints a one-time login link, drives a **hosted interactive browser** to the real
DOCenter SSO/password page, captures the user's own `_SESSION` cookie (the exact
same success signal as `docenter/cli.py:_browser_login` —
`ZD__userAuthenticated=="true"` **and** `_SESSION` present), and writes it to the
Phase-3 per-user store. Everything is **additive** and does not touch the shared
cookie the Copilot agent uses (R3).

It is packaged inside the `actwise` distribution as the `docenter-broker` console
script (package `docenter_broker`, dir `components/portal/broker`).

## Why it exists

Per-user Entra/OBO auth to `docs-be.niceactimize.com` is **not viable** (no Entra
app registration — see `docs/2026-07-07-portal-auth-probe.md`). A hosted browser
that the user logs into themselves is the only per-user path.

## Flow

```
MCP  --POST /links {user} (X-Broker-Secret)-->  broker      # R1′: broker owns state
broker  --{login_url, state}-->  MCP  --login_url-->  end user
user   --GET /connect?state=…-->  broker  --two-door login page (SSO | password)
  Door 1 (SSO):      POST /connect/sso      --> hosted browser --> DOCenter SSO
  Door 2 (password): POST /connect/password --> Zoomin login API (no browser)
broker polls ZD__userAuthenticated+_SESSION (SSO) / http_login (password)
broker  --save_user_cookie_data(user, payload)-->  Phase-3 per-user store
```

The single `login_url` opens a **two-door page**, so the chat/agent only ever
surfaces ONE link. Both doors authorize with the signed `state` the broker minted
(no broker secret in the browser); passwords are entered only on that page, never
in the chat. The broker **owns** state signing, TTL, and one-time use (R1′). The MCP
never signs state — it only forwards the `login_url` the broker returns.

## Endpoints

| Method | Path               | Auth              | Purpose                                             |
|--------|--------------------|-------------------|-----------------------------------------------------|
| GET    | `/healthz`         | none              | liveness                                            |
| POST   | `/links`           | `X-Broker-Secret` | mint a one-time `login_url` for a user               |
| GET    | `/connect?state`   | signed state      | render the two-door login page (idempotent)         |
| POST   | `/connect/sso`     | signed state      | **Door 1:** consume state, open hosted browser      |
| POST   | `/connect/password`| signed state      | **Door 2:** browser-free password login (browser UI)|
| GET    | `/status?nonce`    | none (nonce)      | poll an in-flight SSO login (for the connect page)  |
| POST   | `/password-login`  | `X-Broker-Secret` | **Door 2 (server-to-server):** password login       |

## Two doors (which login path a user takes)

DOCenter has two account types, and each has its own door — both write the **same**
per-user store, so the MCP serves them identically. The `/connect` page presents both:

- **Door 1 — SSO (`/connect` → `/connect/sso`):** NICE-employee accounts federated to
  Entra. Redirects through Microsoft login and is subject to **Conditional Access**,
  so the hosted browser must be **Edge (or Chrome + the Microsoft SSO extension) on
  a managed, compliant device** with a persistent work-account profile (see R5).
- **Door 2 — password:** customer/partner accounts registered directly on Zoomin with
  email+password (NOT federated). Authenticates against the Zoomin login API via
  `docenter.cli.http_login` — **no browser, no Entra, no Conditional Access** — so it
  works from any host, including a plain datacenter server. Two surfaces:
  - `POST /connect/password` — from the browser login page; authorized by the signed
    `state` (the `user_id` comes from the state, R2 — a form field cannot impersonate).
    Body: `{state, email, password}`.
  - `POST /password-login` — server-to-server (e.g. a future portal backend); authorized
    by `X-Broker-Secret`. Body: `{user, email, password}`.

## Configuration (env)

| Var                        | Required | Default                              | Notes                                  |
|----------------------------|----------|--------------------------------------|----------------------------------------|
| `DOCENTER_BROKER_SECRET`   | yes      | —                                    | MCP→broker shared secret (R1′). Secret. |
| `BROKER_PUBLIC_BASE`       | no       | request base URL                     | public base for building `login_url`   |
| `BROKER_BACKEND`           | no       | `self-hosted`                        | `self-hosted` \| `browserbase`         |
| `BROKER_HOST`/`BROKER_PORT`| no       | `127.0.0.1` / `8099`                 | bind address                           |
| `BROKER_HEADLESS`          | no       | `false`                              | self-hosted: headed so noVNC can show it|
| `BROKER_BROWSER_CHANNEL`   | for SSO  | bundled Chromium                     | set `msedge` (or `chrome` + SSO extension) — **required** to pass Entra Conditional Access (vanilla Chromium → CA error 53000) |
| `BROKER_USER_DATA_DIR`     | for SSO  | fresh temp profile                   | persistent Edge/Chrome profile carrying the managed-device + work-account PRT; **required** for real employee SSO (see R5) |
| `BROKER_NOVNC_URL`         | no       | `http://localhost:6080/vnc.html`     | self-hosted interactive URL            |
| `BROWSERBASE_API_KEY`      | for BB   | —                                    | **USER-gated** (Browserbase trial)     |
| `BROWSERBASE_PROJECT_ID`   | for BB   | —                                    | **USER-gated**                         |
| `DOCENTER_USER_STORE_DIR`  | no       | `~/.docenter/docenter-users`         | where captured per-user cookies land   |

The MCP side reads `DOCENTER_BROKER_URL` + `DOCENTER_BROKER_SECRET` to mint links;
if unset it falls back to a plain `SessionRequired` (Phase-3 behavior).

## Run

Local (self-hosted backend, headless for a smoke test):

```powershell
$env:DOCENTER_BROKER_SECRET = "<shared-secret>"
docenter-broker            # serves on 127.0.0.1:8099
```

Self-hosted noVNC (interactive login) via Docker — the Conditional-Access fallback:

```bash
export DOCENTER_BROKER_SECRET=<shared-secret>
docker compose -f components/portal/broker/docker-compose.yml up --build
# broker:  http://localhost:8099   noVNC: http://localhost:6080/vnc.html
```

## Backends & the R5 decision point

- **self-hosted** (`SelfHostedBackend`) — Playwright Chromium shown over noVNC.
  Runs where you control the network → the fallback if Entra Conditional Access
  blocks datacenter browsers.
- **browserbase** (`BrowserbaseBackend`) — a datacenter cloud browser. Convenient,
  but Entra CA may block it. Guarded: raises unless `BROWSERBASE_*` are set.

**R5 is a go/no-go:** does a real employee SSO login succeed inside a hosted
browser? See `docs/components/docenter/2026-07-16-...-R5-go-no-go.md`.

## USER-gated steps (flag, don't auto-run)

1. A **real employee SSO login** through the hosted browser (the decisive R5 test).
2. **Browserbase** trial signup + `BROWSERBASE_API_KEY` / `BROWSERBASE_PROJECT_ID`.
3. Running the **Docker noVNC** container for a real interactive login.

## Proof

Deterministic, no real browser or login:

```powershell
py components\portal\broker\_broker_proof.py
```

Covers state signing/TTL/tamper, `/links` auth matrix, capture→store (R3), the
two-door `/connect` page + `/connect/sso` one-time nonce, `/connect/password` and
`/password-login` (both Door-2 surfaces), and MCP `_mint_login_url` wiring.
