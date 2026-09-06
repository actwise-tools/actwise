# DOCenter MCP — team deployment kit

A self-contained kit for standing up the **DOCenter MCP** as a shared HTTPS service so
your whole team can search the live NICE Actimize documentation portal through one
endpoint, backed by **one shared portal credential** — no per-user identity, no S3, no
login broker.

> **What this is not:** the DOCenter MCP does not ship any NICE Actimize content,
> catalog, or credential. It queries the **live** public documentation portal at runtime
> using **your own** authenticated portal session. See the repository `NOTICE`.

---

## Who each doc is for

| If you are… | Read | You will… |
|---|---|---|
| **Deploying** the service into your team's cloud (AWS, Azure, k8s, …) | **[DEPLOYMENT-GUIDE.md](./DEPLOYMENT-GUIDE.md)** | build the image, wire the 2–4 secrets, run it, and verify it |
| **Using** the service from an MCP client (Copilot, Claude, VS Code, Copilot Studio) | **[USER-GUIDE.md](./USER-GUIDE.md)** | point your client at the URL + API key and call the doc tools |

Deep references also live alongside this kit in the component:

- [`../README.md`](../README.md) — the server itself: all env vars + session self-heal.
- [`../TOOLS.md`](../TOOLS.md) — full tool parameter/return reference.
- [`../HANDOFF-image-spec.md`](../HANDOFF-image-spec.md) — image-handoff contract for a
  platform/Ansible team dropping the container into an existing org VPC.
- [`../Dockerfile`](../Dockerfile), [`../entrypoint.sh`](../entrypoint.sh) — the image.

---

## What you hand a teammate

Everything needed to build and run the service is in this repository — **no secrets are
committed**. Give a teammate:

1. **Repo access** (or a zip/git-bundle of the repo). The image builds from repo root:
   `pyproject.toml`, `README.md`, `components/`, and `docs/catalog.yaml`.
2. **Two secret values, over a secure channel** (never in git, chat history, or CI logs) —
   the credential pair that is the single source of truth for the shared session:
   - the portal account **email + password** (`DOCENTER_EMAIL` / `DOCENTER_PASSWORD`) —
     the server mints the shared cookie from these on first use and self-heals on expiry
   - the `X-API-Key` clients must send (`DOCENTER_PROXY_API_KEY`)
3. Optionally a pre-minted shared `_SESSION` cookie (`DOCENTER_COOKIES_JSON`) — only for
   **SSO-only** accounts that cannot log in headless; then rotate it manually (~monthly).

The teammate stores those values in **their own** cloud secret store (SSM Parameter Store
`SecureString` is free — see the deployment guide) and never receives your AWS account or
infrastructure.

---

## 60-second mental model

```
  MCP clients ── HTTPS + X-API-Key ─►  DOCenter MCP  (uvicorn + FastMCP, stateless)
  (Copilot / Claude / VS Code /            │  one shared portal _SESSION cookie
   Copilot Studio / your agent)            ▼  (self-mints on cold start, self-heals on 403)
                                    NICE Actimize / Zoomin documentation portal
```

- **Stateless** (`stateless_http=True`) → scale by replicas, no session affinity.
- **One credential pair** → email + password mint and self-heal the shared cookie
  (cookie injection optional, for SSO-only accounts).
- **Read-only** → six documentation search/read tools; no writes anywhere.

Next: **[DEPLOYMENT-GUIDE.md](./DEPLOYMENT-GUIDE.md)**.
