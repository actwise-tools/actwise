# DOCenter MCP — image-handoff spec (for the platform / Ansible team)

**Audience:** whoever deploys this container into the NICE org AWS account (e.g. via
the Ansible control node `hos-sl-ans03-01.use1.niceondemandaws.internal`).
**Goal:** run the DOCenter MCP as a long-lived HTTPS service inside the org VPC, in
**single-credential mode** (one shared portal login; no per-user identity, no S3, no
login broker). The runtime is env-var driven, so this is an **image handoff** — no
source changes required.

---

## 1. What it is

A stateless Streamable-HTTP **MCP server** (uvicorn + FastMCP) that exposes the live
NICE Actimize documentation portal as tools (`search_docs`, `list_docs`,
`find_bundles`, `get_catalog`, `get_page`, `get_toc`). Clients (Copilot Studio /
Copilot CLI / VS Code / an internal agent) call it over HTTPS with an `X-API-Key`
header. It authenticates to the doc portal with **one shared session cookie** and
**auto-refreshes** that cookie on expiry.

---

## 2. The deliverable — the image

Built from the `actwise` repo (`components/docenter/docenter_mcp/Dockerfile`). Either
we hand you a pushed image, or your playbook builds it. Reference build/push:

```bash
# from the repo root — clean single-arch manifest (App Runner/most runtimes reject
# BuildKit's default attestation manifest list)
docker build --provenance=false --sbom=false --platform linux/amd64 \
  -f components/docenter/docenter_mcp/Dockerfile \
  -t <ORG_REGISTRY>/actwise-docenter-mcp:<tag> .

docker push <ORG_REGISTRY>/actwise-docenter-mcp:<tag>
```

- No secrets are baked into the image (verified: the only secret, the portal cookie,
  is injected at runtime — see §4).
- Image is ~small (no Playwright browser binaries, no `raw_docs/` corpus; only a
  ~1 MB product catalog is included).
- Base: `python:3.12-slim`. Amd64.

---

## 3. Runtime contract

| Property | Value |
|---|---|
| Listen | `0.0.0.0:8765` (override with `DOCENTER_MCP_PORT` / `DOCENTER_MCP_HOST`) |
| MCP endpoint | `POST /mcp` (protocol: MCP Streamable HTTP, `mcp-streamable-1.0`) |
| Health check | `GET /healthz` → `200 {"status":"ok","server":"actwise-docenter-live"}` (no auth) |
| Entrypoint | `entrypoint.sh` → materialises the cookie env var to a file, then `uvicorn docenter_mcp.server:app` |
| Statelessness | `stateless_http=True` — horizontally scalable, no session affinity needed |
| Process model | single container; scale by replicas behind the load balancer |

---

## 4. Environment / secret contract

### Secrets (inject from org Secrets Manager / Vault — values, never in the image)

| Env var | Required | Meaning |
|---|:--:|---|
| `DOCENTER_COOKIES_JSON` | **yes** | The shared portal `_SESSION` cookie **as JSON** (the contents of a `session-cookies.json`). This is *the* credential. `entrypoint.sh` writes it to `/tmp/session-cookies.json` at boot. |
| `DOCENTER_PROXY_API_KEY` | **yes** | The `X-API-Key` value clients must send. Requests without a matching key get `401`. |
| `DOCENTER_EMAIL` | recommended | Portal account email — enables browser-free cookie **self-heal** (§6). |
| `DOCENTER_PASSWORD` | recommended | Portal account password — used with the email for self-heal. Password (non-SSO) account required. |

### Plain env vars (optional tuning; safe defaults)

| Env var | Default | Meaning |
|---|---|---|
| `DOCENTER_MCP_PORT` | `8765` | Listen port. |
| `DOCENTER_MCP_HOST` | `0.0.0.0` | Bind host. |
| `DOCENTER_MCP_MAX_RESULTS` | `50` | Per-call result ceiling for `search_docs`/`find_bundles`. |
| `DOCENTER_MCP_RELOGIN_COOLDOWN` | `60` | Min seconds between self-heal re-login attempts (anti-lockout throttle). |
| `DOCENTER_CATALOG_FILE` | `/app/docs/catalog.yaml` | Baked into the image; leave as-is. |

### DO NOT set these (they would switch on per-user mode / S3 / broker)

`DOCENTER_PER_USER`, `DOCENTER_USER_STORE_S3_BUCKET`, `DOCENTER_BROKER_SECRET`,
`DOCENTER_BROKER_URL`, `DOCENTER_USER_TOKEN_SECRET`. Leaving them unset keeps this a
simple single-credential service (no S3, no extra IAM).

---

## 5. Network / egress requirements

**Outbound (required).** The container calls the **public** doc portal — it needs
internet egress (NAT gateway if in a private subnet). It does **not** need to reach
any internal `10.x` ActOne network.

| Destination | Port | Purpose |
|---|---|---|
| `docs.niceactimize.com` | 443 | portal login priming |
| `docs-be.niceactimize.com` | 443 | documentation search/content API |
| `niceactimize.zoominsoftware.io` | 443 | Zoomin alternate host |

**Inbound.** HTTPS to `/mcp` and `/healthz` on the service port (8765) via the load
balancer. TLS terminates at the ALB (ACM cert). Restrict as appropriate:
- Internal-only ALB → reachable by corp-network / VPN clients and internal agents.
- **Note:** Copilot Studio's custom connector needs a **publicly reachable** HTTPS
  URL; an internal-only ALB will not work for Copilot Studio (fine for CLI/VS
  Code/internal agents). Confirm which clients must reach it.

---

## 6. Session auto self-heal (operational behaviour)

The portal `_SESSION` cookie expires (~monthly). On a portal **403**, the server does
**one** browser-free HTTP re-login using `DOCENTER_EMAIL`/`DOCENTER_PASSWORD`, rewrites
the local cookie file, and retries the call once — so expiry heals transparently.
Implications for hosting:

- The container needs a **writable `/tmp`** (self-heal rewrites `/tmp/session-cookies.json`).
  If you enforce a read-only root filesystem, mount a writable volume at `/tmp`.
- Self-heal state is **per replica** (in-memory + local file). With N replicas, each
  re-logs in independently on its first 403; the per-instance cooldown throttles it.
- If `DOCENTER_EMAIL`/`DOCENTER_PASSWORD` are omitted, there is no self-heal — you must
  rotate the `DOCENTER_COOKIES_JSON` secret manually (~monthly) and redeploy/restart.

---

## 7. Suggested compute

Small. Reference production runs at **0.25 vCPU / 0.5 GB** (App Runner `256`/`512`).
Fargate task `256`/`512` or a small pod request is plenty; scale by replica count.

---

## 8. Deployment shape (templates the Ansible role can fill)

The service just needs: image + port 8765 + the 2–4 env/secret values + a health
check + egress. Two equivalent target shapes:

**ECS Fargate — container definition (essential fields):**

```jsonc
{
  "name": "docenter-mcp",
  "image": "<ORG_REGISTRY>/actwise-docenter-mcp:<tag>",
  "portMappings": [{ "containerPort": 8765, "protocol": "tcp" }],
  "secrets": [
    { "name": "DOCENTER_COOKIES_JSON",  "valueFrom": "<cookie-secret-arn>" },
    { "name": "DOCENTER_PROXY_API_KEY", "valueFrom": "<apikey-secret-arn>" },
    { "name": "DOCENTER_EMAIL",         "valueFrom": "<email-secret-arn>" },
    { "name": "DOCENTER_PASSWORD",      "valueFrom": "<password-secret-arn>" }
  ],
  "healthCheck": {
    "command": ["CMD-SHELL", "python -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8765/healthz').status==200 else 1)\""],
    "interval": 30, "timeout": 5, "retries": 3, "startPeriod": 10
  }
}
```
(ALB target group health check path: `/healthz`, expect `200`.)

**Kubernetes — Deployment (essential fields):**

```yaml
spec:
  containers:
    - name: docenter-mcp
      image: <ORG_REGISTRY>/actwise-docenter-mcp:<tag>
      ports: [{ containerPort: 8765 }]
      envFrom: []                      # (leave per-user/S3/broker vars UNSET)
      env:
        - name: DOCENTER_COOKIES_JSON
          valueFrom: { secretKeyRef: { name: docenter-mcp, key: cookies_json } }
        - name: DOCENTER_PROXY_API_KEY
          valueFrom: { secretKeyRef: { name: docenter-mcp, key: api_key } }
        - name: DOCENTER_EMAIL
          valueFrom: { secretKeyRef: { name: docenter-mcp, key: email } }
        - name: DOCENTER_PASSWORD
          valueFrom: { secretKeyRef: { name: docenter-mcp, key: password } }
      readinessProbe:  { httpGet: { path: /healthz, port: 8765 }, initialDelaySeconds: 10 }
      livenessProbe:   { httpGet: { path: /healthz, port: 8765 }, periodSeconds: 30 }
      volumeMounts: [{ name: tmp, mountPath: /tmp }]   # writable /tmp for self-heal
  volumes: [{ name: tmp, emptyDir: {} }]
```

---

## 9. Verification (post-deploy)

```bash
# 1. Health (no auth)
curl -fsS https://<internal-url>/healthz
# -> {"status":"ok","server":"actwise-docenter-live"}

# 2. Auth gate rejects a missing/wrong key
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://<internal-url>/mcp   # -> 401

# 3. A real MCP call with the key returns tool results (initialize/list or a search).
#    Easiest end-to-end check: point an MCP client at https://<internal-url>/mcp
#    with header  X-API-Key: <value>  and run search_docs("DART").
```

Also confirm in logs after a forced/expired cookie: `portal session auto-refreshed
via HTTP re-login` (proves self-heal works in this environment).

---

## 10. What we need back from the platform team

1. The **internal (or public) HTTPS URL** the service is published on.
2. Confirmation the 2–4 secrets are wired from the org secret store.
3. Confirmation **outbound 443** to the three portal hosts (§5) is allowed.
4. Whether the endpoint is **internet-reachable** (needed if Copilot Studio must use it).

---

## References (in the repo)

- `components/docenter/docenter_mcp/Dockerfile`, `entrypoint.sh` — image + cookie shim.
- `components/docenter/docenter_mcp/README.md` — tools, all env vars, self-heal detail.
- `components/docenter/docenter_mcp/README-team-deploy.md` — the single-credential deploy guide (App Runner variant).
- `docs/runbooks/2026-07-11-docenter-mcp-aws-deployment-runbook.md` — the reference AWS deployment + self-heal verification.
