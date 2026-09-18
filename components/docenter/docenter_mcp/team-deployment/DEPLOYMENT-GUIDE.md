# DOCenter MCP — deployment guide

Deploy the DOCenter MCP as a long-lived HTTPS service in **your own** infrastructure,
in **single-credential mode**: one shared portal login, no per-user identity, no S3, no
login broker. The runtime is entirely env-var driven, so this is an **image handoff** —
no source changes required.

Works on any container runtime. Concrete recipes below for **AWS App Runner**, **AWS ECS
Fargate**, **Kubernetes**, and a **plain `docker run`** smoke test.

---

## 1. Prerequisites

- **Docker** with buildx (to build the image), or a pre-built image you were handed.
- Access to a **container registry** your runtime can pull from (ECR, ACR, GHCR, …).
- Your cloud's **secret store** (AWS Secrets Manager, Azure Key Vault, k8s Secrets, …).
- A **DOCenter portal account**. For automatic cookie self-heal it must be a
  **password (non-SSO)** account — SSO-only accounts cannot re-login headless.
- The repository (to build the image) — or the image itself.

---

## 2. Build and push the image

The image is built from the repo root (it installs the `actwise` distribution and bakes
in only the ~1 MB product catalog, which **ships in this repo** at `docs/catalog.yaml`;
the large offline corpus and browser binaries are **not** included).

```bash
# From the repository root. --provenance=false --sbom=false yields a clean
# single-arch manifest; many runtimes reject BuildKit's default attestation list.
docker build --provenance=false --sbom=false --platform linux/amd64 \
  -f components/docenter/docenter_mcp/Dockerfile \
  -t <your-registry>/actwise-docenter-mcp:v1 .

docker push <your-registry>/actwise-docenter-mcp:v1
```

No secrets are baked in — the only secret (the portal cookie) is injected at runtime
(§4). Reference compute: **0.25 vCPU / 0.5 GB** is plenty; scale by replica count.

> **Security patching.** The Dockerfile runs `apt-get update && apt-get -y upgrade` on
> the Debian base so the OS packages (perl, glibc, sqlite3, …) pick up upstream security
> fixes **at build time**. These OS-base CVEs are not in ActWise Python code. Because a
> fix only lands when you rebuild, **rebuild + redeploy on a schedule** (e.g. weekly, or
> on a scanner alert) so freshly-published patches reach the running image. A rebuild is
> the whole remediation — no code change is needed.

---

## 3. Mint the shared portal cookie

On any machine with the repo installed, put the portal creds in `.env`
(`DOCENTER_EMAIL`, `DOCENTER_PASSWORD`) and mint the cookie **browser-free**:

```bash
docenter auth login --http     # writes browser-profile/session-cookies.json
```

That JSON file's contents become the `DOCENTER_COOKIES_JSON` secret below.

---

## 4. Create the secrets (values via file, never inline)

**Rule:** credential *values* live **only** in your secret store. Scripts, manifests, and
CI logs reference **names/ARNs only**. Never paste a cookie or password inline in a shell
(it lands in shell history) — always pass it from a file, then delete the file.

The service reads these secrets (2 required, plus creds that are required-or-recommended):

| Secret env var | Required | Meaning |
|---|:--:|---|
| `DOCENTER_PROXY_API_KEY` | **yes** | The `X-API-Key` value clients must send. Requests without a matching key get `401`. |
| `DOCENTER_COOKIES_JSON` | cookie **or** creds | The shared portal `_SESSION` cookie **as JSON** (contents of `session-cookies.json`). `entrypoint.sh` writes it to `/tmp/session-cookies.json` at boot. **Optional** when `DOCENTER_EMAIL`+`DOCENTER_PASSWORD` are set — see cold-start below. |
| `DOCENTER_EMAIL` | see note | Portal account email. **Required** (with password) when you omit the cookie; otherwise recommended for cookie **self-heal** (§7). |
| `DOCENTER_PASSWORD` | see note | Portal account password. Used with the email. Non-SSO account required. |

### Cold start — cookie-free bootstrap (recommended)

You can deploy with **only `DOCENTER_PROXY_API_KEY` + `DOCENTER_EMAIL` + `DOCENTER_PASSWORD`** and **no cookie at all**. On the first portal call the server sees there is no cookie, performs one browser-free HTTP login from the creds, writes `/tmp/session-cookies.json`, and serves the request — then self-heals on every later expiry the same way (§7). This means you never have to mint or rotate a cookie by hand: the account password is the single source of truth. (SSO-only accounts can't log in headless — for those you must still inject `DOCENTER_COOKIES_JSON` and rotate it manually.)

### AWS Secrets Manager example

```bash
R="--region us-east-1"   # add --profile <name> if you don't use ambient creds

# The shared cookie (the single credential):
aws secretsmanager create-secret $R --name docenter/cookie \
  --secret-string "file://$(pwd)/browser-profile/session-cookies.json"

# A strong random X-API-Key, generated into a file first:
python -c "import secrets;open('_apikey.txt','w').write(secrets.token_urlsafe(32))"
aws secretsmanager create-secret $R --name docenter/api-key --secret-string file://_apikey.txt
rm _apikey.txt

# Optional but recommended — enable cookie auto self-heal:
printf '%s' 'svc-docenter@example.com' > _email.txt
aws secretsmanager create-secret $R --name docenter/email --secret-string file://_email.txt && rm _email.txt
printf '%s' '<portal-password>' > _pw.txt
aws secretsmanager create-secret $R --name docenter/password --secret-string file://_pw.txt && rm _pw.txt
```

Record the returned **ARNs** — you reference them when creating the service.

### Where to store the values — and how to avoid Secrets Manager billing

**The container never calls a secret store itself** — it only reads plain **environment
variables**. Your platform is what pulls values from wherever you put them and injects
them as env. So *where* the values live is a free deployment choice with **no code or
image change**. Pick by cost/fit:

| Option | Cost | When to use |
|---|---|---|
| **AWS Systems Manager Parameter Store** (`SecureString`, Standard tier) | **free** (KMS `aws/ssm`, no per-secret fee) | Cheapest AWS option. App Runner and ECS both source env from SSM the same way as Secrets Manager — just reference the parameter ARN. |
| **AWS Secrets Manager** | ~$0.40 / secret / month + API calls | Only if you want its rotation/versioning. To cut the bill, **consolidate all values into one JSON secret** and reference per-key (`arn:…:secret:docenter:api_key::`) → **1 secret billed**, not four. |
| **Kubernetes `Secret`** | **free** (etcd) | On k8s, use native `Secret`s (as in §6d) — no AWS Secrets Manager at all. Optionally sync from a cloud store with External Secrets Operator. |
| **Plain env / ConfigMap** for **non-secrets** | free | Only for genuinely non-sensitive values (host/port, catalog path). **Never** put the email, password, API key, or cookie here. |

**Recommended low-cost setup:** with cold-start bootstrap you only need to store the
**email**, **password**, and **API key** (the cookie is regenerated, so you don't store it).
Put all three in **SSM Parameter Store `SecureString` (free)** — keeping the email and
password credential pair together — and you pay **$0** for secret storage on AWS. On
Kubernetes, put the same three in a native `Secret`.

> Classification: **store in the secret store** (SSM SecureString / Secrets Manager /
> k8s `Secret`) = `DOCENTER_EMAIL`, `DOCENTER_PASSWORD`, `DOCENTER_PROXY_API_KEY`,
> `DOCENTER_COOKIES_JSON` (if used) — keep the email with its password. **Not sensitive** =
> host/port, catalog path. Keep credentials out of the image, out of git, and out of shell history.

### Provisioning the secrets in SSM Parameter Store (console + CLI)

You add the credential **values** once in SSM; the deployment only ever references the
parameter **names**, so no cleartext password lands in a manifest, in git, or in the image.

**AWS console:** *Systems Manager -> Parameter Store -> Create parameter*, three times:

| Name | Type | Value |
|---|---|---|
| `/actwise/docenter/api-key` | **SecureString** | your `X-API-Key` |
| `/actwise/docenter/email` | **SecureString** | portal login email |
| `/actwise/docenter/password` | **SecureString** | portal password |

Leave the KMS key as the default `alias/aws/ssm` (free). That is the entire "add the
values" step. To **rotate** later, just edit the parameter value in the console -- no
redeploy: App Runner/ECS pick it up on the next restart, and on k8s the External Secrets
Operator re-syncs on its `refreshInterval`.

**CLI equivalent** (value via file so it never lands in shell history):

```bash
R="--region us-east-1"   # add --profile <name> if you don't use ambient creds
printf '%s' '<your-api-key>'  > _v.txt; aws ssm put-parameter $R --name /actwise/docenter/api-key  --type SecureString --value file://_v.txt --overwrite; rm _v.txt
printf '%s' '<login-email>'   > _v.txt; aws ssm put-parameter $R --name /actwise/docenter/email    --type SecureString --value file://_v.txt --overwrite; rm _v.txt
printf '%s' '<login-password>'> _v.txt; aws ssm put-parameter $R --name /actwise/docenter/password --type SecureString --value file://_v.txt --overwrite; rm _v.txt
```

**How the value reaches the container (no cleartext in the deployment):**

- **App Runner / ECS** read SSM natively -- map each env var to the parameter **ARN**
  (App Runner `RuntimeEnvironmentSecrets`, ECS container `secrets[].valueFrom`); the
  instance/execution role needs `ssm:GetParameter` + `kms:Decrypt`.
- **Kubernetes** uses **IRSA + External Secrets Operator**: a `ServiceAccount` is granted
  `ssm:GetParameter*`+`kms:Decrypt` on `/actwise/docenter/*` (IRSA), an `ExternalSecret`
  names the three params, and ESO materialises the native `Secret` that Section 6d consumes.
  Names are just a convention -- to use your own prefix, change the `ExternalSecret`
  `remoteRef.key`s and the IAM policy ARN wildcard to match. A worked EKS example lives in
  the internal runbook `docs/runbooks/2026-07-28-docenter-mcp-eks-irsa-ssm-reference.md`.

The cleartext only ever exists encrypted at rest in SSM, in the in-cluster/platform secret,
and in pod memory -- never in a file you commit.

---

## 5. Runtime contract (applies to every platform)

| Property | Value |
|---|---|
| Listen | `0.0.0.0:8765` (override with `DOCENTER_MCP_PORT` / `DOCENTER_MCP_HOST`) |
| MCP endpoint | `POST /mcp` (MCP Streamable HTTP) — auth via `X-API-Key` header |
| Health check | `GET /healthz` → `200 {"status":"ok","server":"actwise-docenter-live"}` (no auth) |
| Filesystem | needs a **writable `/tmp`** (self-heal rewrites `/tmp/session-cookies.json`) |
| Egress | outbound **443** to the portal hosts in §8 (NAT gateway if in a private subnet) |

### Do NOT set these (they switch on per-user mode / S3 / broker)

Leaving them unset is what keeps this simple single-credential mode:
`DOCENTER_PER_USER`, `DOCENTER_USER_STORE_S3_BUCKET`, `DOCENTER_BROKER_SECRET`,
`DOCENTER_BROKER_URL`, `DOCENTER_USER_TOKEN_SECRET`.

---

## 6. Run it — pick your platform

### 6a. Plain `docker run` (local smoke test)

```bash
docker run --rm -p 8765:8765 \
  -e DOCENTER_PROXY_API_KEY="<your-api-key>" \
  -e DOCENTER_COOKIES_JSON="$(cat browser-profile/session-cookies.json)" \
  <your-registry>/actwise-docenter-mcp:v1
# endpoint: http://localhost:8765/mcp   health: http://localhost:8765/healthz
```

### 6b. AWS App Runner

Create the service once (source = your ECR image, port `8765`, the 2–4 secrets wired as
runtime **secrets**, an instance role that can read exactly those secret ARNs). You can
do this in the App Runner console or with `aws apprunner create-service`. Note the
resulting **Service ARN** and **public URL** — those drive future rollouts.

> If you build on AWS App Runner and have the source repo, a convenience PowerShell
> wrapper (`deploy-shared.ps1`, in the component directory of the private source repo)
> automates build → ECR push → `update-service` → wait for `RUNNING` → verify `/healthz`.
> The manual steps here work on any account without it.

The App Runner instance role policy **must list each secret ARN explicitly**
(ARN-scoped, not a wildcard) or the container gets `AccessDenied` at startup.

### 6c. AWS ECS Fargate — container definition (essential fields)

```jsonc
{
  "name": "docenter-mcp",
  "image": "<your-registry>/actwise-docenter-mcp:v1",
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

Point the ALB target group health check at `/healthz` (expect `200`). TLS terminates at
the ALB (ACM cert).

### 6d. Kubernetes — Deployment (essential fields)

```yaml
spec:
  # A Service named `docenter-mcp` makes k8s inject DOCENTER_MCP_PORT=tcp://<ip>:8765,
  # which would override the app's own DOCENTER_MCP_PORT and crash uvicorn. Disable
  # the legacy service-link env injection to avoid the collision.
  enableServiceLinks: false
  containers:
    - name: docenter-mcp
      image: <your-registry>/actwise-docenter-mcp:v1
      ports: [{ containerPort: 8765 }]
      env:
        - name: DOCENTER_COOKIES_JSON
          valueFrom: { secretKeyRef: { name: docenter-mcp, key: cookies_json } }
        - name: DOCENTER_PROXY_API_KEY
          valueFrom: { secretKeyRef: { name: docenter-mcp, key: api_key } }
        - name: DOCENTER_EMAIL
          valueFrom: { secretKeyRef: { name: docenter-mcp, key: email } }
        - name: DOCENTER_PASSWORD
          valueFrom: { secretKeyRef: { name: docenter-mcp, key: password } }
      readinessProbe: { httpGet: { path: /healthz, port: 8765 }, initialDelaySeconds: 10 }
      livenessProbe:  { httpGet: { path: /healthz, port: 8765 }, periodSeconds: 30 }
      volumeMounts: [{ name: tmp, mountPath: /tmp }]   # writable /tmp for self-heal
  volumes: [{ name: tmp, emptyDir: {} }]
```

---

## 7. Session auto self-heal & cookie rotation

The portal `_SESSION` cookie expires (~monthly). On a portal **403**, the server does
**one** browser-free HTTP re-login using `DOCENTER_EMAIL` / `DOCENTER_PASSWORD`, rewrites
`/tmp/session-cookies.json`, and retries the call once — so expiry heals transparently.

- Requires a **writable `/tmp`** (see §5). Self-heal state is **per replica**; the
  per-instance cooldown (`DOCENTER_MCP_RELOGIN_COOLDOWN`, default 60s) throttles re-login.
- After a forced/expired cookie, logs show: `portal session auto-refreshed via HTTP
  re-login` — that confirms self-heal works in your environment.
- **No email/password?** Then there is no self-heal: rotate the cookie manually (~monthly)
  and restart/redeploy:

  ```bash
  aws secretsmanager put-secret-value --secret-id docenter/cookie \
    --secret-string file://new-session-cookies.json
  # then trigger a new deployment / restart the tasks so the new value is read
  ```

---

## 8. Network / egress

**Outbound (required).** The container calls the **public** doc portal — it needs
internet egress. It does **not** need to reach any internal ActOne network.

| Destination | Port | Purpose |
|---|---|---|
| `docs.niceactimize.com` | 443 | portal login priming |
| `docs-be.niceactimize.com` | 443 | documentation search / content API |
| `niceactimize.zoominsoftware.io` | 443 | Zoomin alternate host |

**Inbound.** HTTPS to `/mcp` and `/healthz` on port 8765 behind your load balancer.
**Note:** Copilot Studio requires a **publicly reachable** HTTPS URL — an internal-only
load balancer works for CLI / VS Code / internal agents but not for Copilot Studio.

---

## 9. Verify

```bash
# 1. Health (no auth)
curl -fsS https://<your-service-host>/healthz
# -> {"status":"ok","server":"actwise-docenter-live"}

# 2. Auth gate rejects a missing/wrong key
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://<your-service-host>/mcp   # -> 401

# 3. A real tool call with the key returns results — easiest end-to-end check is to
#    point an MCP client at https://<your-service-host>/mcp with header
#    X-API-Key: <value> and run search_docs("DART").  (See USER-GUIDE.md.)
```

Checklist:

- [ ] Service status is `RUNNING`/`Ready`.
- [ ] Runtime env exposes only the 2–4 shared **secrets** (no per-user/S3/broker vars).
- [ ] `GET /healthz` → 200.
- [ ] One authenticated `search_docs` / `find_bundles` call returns real portal results.

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Container exits at startup with `AccessDenied` reading a secret | instance/task role not scoped to the secret ARNs | grant the role `secretsmanager:GetSecretValue` on **each** ARN explicitly |
| All tool calls fail with a "refresh with `docenter auth login`" error | cookie expired and no self-heal creds set (or SSO-only account) | set `DOCENTER_EMAIL`/`DOCENTER_PASSWORD` (non-SSO), or rotate the cookie secret (§7) |
| Self-heal never fires; read-only-fs errors in logs | root filesystem is read-only | mount a **writable volume at `/tmp`** |
| Image won't run on the platform ("manifest list" error) | BuildKit attestation manifest | rebuild with `--provenance=false --sbom=false --platform linux/amd64` |
| Copilot Studio can't reach the server | endpoint is internal-only | expose a **public** HTTPS URL for Copilot Studio clients |
| Clients get `401` with the right key | key mismatch / trailing whitespace in the secret | write the API key with no trailing newline; compare secret value to client header |

---

Next: hand your teammates **[USER-GUIDE.md](./USER-GUIDE.md)** to connect their clients.
