# DOCenter MCP — team deployment (single shared credential)

Deploy the DOCenter MCP so your whole team can search the live NICE Actimize
documentation portal through one HTTPS endpoint, backed by **one shared DOCenter
credential**. No per-user identity, **no S3**, no login broker.

> This is the simple mode. The richer per-user variant (each end user's own portal
> login, backed by S3 + a login broker) is a separate opt-in — see
> `deploy.ps1` and `docs/components/portal/`. Everything here deliberately leaves
> that untouched.

---

## 1. How single-credential mode works (and why no S3)

The server (`docenter_mcp/server.py`) is built so the per-user machinery is **inert
unless you opt in** with env vars:

| Env var | Set it? | Effect when unset |
|---|---|---|
| `DOCENTER_PER_USER` | **no** | `_resolve_session()` always uses the one shared cookie ("byte-for-byte the shared-cookie server") |
| `DOCENTER_USER_STORE_S3_BUCKET` | **no** | the S3 backend in `user_store.py` is never reached — **no S3 needed** |
| `DOCENTER_BROKER_SECRET` | **no** | the embedded login broker never mounts |

So single-credential mode is simply: **don't set those.** `deploy-shared.ps1`
enforces this (it sends an empty `RuntimeEnvironmentVariables` and only the
shared-mode secrets).

**The one credential** = a shared portal `_SESSION` cookie (`DOCENTER_COOKIES_JSON`).
Optionally add the portal email/password so the server **auto-refreshes** that cookie
on expiry (~monthly) without anyone re-minting it.

```
  MCP clients ──HTTPS + X-API-Key──►  App Runner (uvicorn+FastMCP, stateless)
  (Copilot Studio / CLI / VS Code)         │ shared _SESSION cookie
                                           ▼ (auto self-heals on 403)
                                   NICE Actimize / Zoomin doc portal
```

---

## 2. Sharing the code

Everything needed is in the `actwise` repo — **no secrets are committed**. The image
is built from:

- `pyproject.toml`, `README.md`
- `components/` (pulls `docenter_mcp` + its deps `docenter`, `extractor`, `core/actwise`)
- `docs/catalog.yaml` (the ~1 MB product catalog; the 352 MB `raw_docs/` corpus is **not** shipped — the live server queries the portal)

Give teammates repo access (or a git bundle/zip of those paths). They never receive
your credentials — those live only in their own AWS Secrets Manager (§4).

---

## 3. Prerequisites

- **Docker** with buildx
- **AWS CLI v2**, authenticated to the target account (a profile, or CI OIDC creds)
- **PowerShell 7** (`pwsh`)
- A **DOCenter portal account** (password-based, so self-heal works). SSO-only
  accounts can't auto-refresh headless.

---

## 4. Configure DOCenter credentials safely

**Rule:** credential *values* live **only** in AWS Secrets Manager. Code, scripts,
and CI logs reference **ARNs only**. Never paste a cookie/password inline in a shell
(it lands in history) — always pass it via `file://`.

### 4.1 Mint the shared portal cookie (browser-free)

On any machine with the repo installed, put the portal creds in `.env`
(`DOCENTER_EMAIL`, `DOCENTER_PASSWORD`) and run:

```powershell
docenter auth login --http      # writes browser-profile/session-cookies.json
```

### 4.2 Create the secrets (values via file, never inline)

```powershell
$P = @("--region","us-east-1")   # add ("--profile","<your-profile>") if not using ambient creds

# The shared cookie (the single credential):
aws secretsmanager create-secret @P --name docenter/cookie `
  --secret-string ("file://" + (Resolve-Path browser-profile/session-cookies.json))

# The X-API-Key gate (generate a strong random value into a file first):
$key = [Convert]::ToBase64String((1..32 | ForEach-Object { Get-Random -Max 256 }))
Set-Content -NoNewline -Path .\_apikey.txt -Value $key
aws secretsmanager create-secret @P --name docenter/api-key --secret-string file://_apikey.txt
Remove-Item .\_apikey.txt

# Optional but recommended — enable auto self-heal of the cookie:
Set-Content -NoNewline -Path .\_email.txt -Value "svc-docenter@example.com"
aws secretsmanager create-secret @P --name docenter/email --secret-string file://_email.txt
Remove-Item .\_email.txt
Set-Content -NoNewline -Path .\_pw.txt -Value "<portal-password>"
aws secretsmanager create-secret @P --name docenter/password --secret-string file://_pw.txt
Remove-Item .\_pw.txt
```

Record the returned **ARNs** — you pass them to `deploy-shared.ps1`.

> **Rotating the cookie later:** `aws secretsmanager put-secret-value --secret-id docenter/cookie --secret-string file://...new.json`, then redeploy (or `aws apprunner start-deployment`). With self-heal on, you rarely need to.

---

## 5. One-time AWS bootstrap (create the separate service)

`deploy-shared.ps1` **updates** an existing App Runner service, so create it once.

```powershell
$P = @("--region","us-east-1")

# 5.1 ECR repo for the image
aws ecr create-repository @P --repository-name actwise-docenter-mcp

# 5.2 IAM roles
#   - AppRunnerECRAccessRole : lets App Runner PULL the image (trust: build.apprunner.amazonaws.com)
#   - AppRunnerInstanceRole  : lets the CONTAINER read the 2-4 secrets (trust: tasks.apprunner.amazonaws.com)
# The instance-role policy MUST list each secret ARN explicitly (ARN-scoped, not a wildcard),
# or the container gets AccessDenied at startup. Reuse existing roles if you already have them.

# 5.3 Build + push the first image (no service yet):
pwsh components/docenter/docenter_mcp/deploy-shared.ps1 `
  -Account <ACCT> -ServiceArn "PLACEHOLDER" -AccessRoleArn "PLACEHOLDER" `
  -HealthUrl "PLACEHOLDER" -CookieSecretArn <ARN> -ApiKeySecretArn <ARN> -NoDeploy

# 5.4 Create the service pointing at that image + secrets:
aws apprunner create-service @P `
  --service-name docenter-mcp-shared `
  --source-configuration (build the ImageRepository JSON: ImageIdentifier=<ecr>:<tag>,
     ImageRepositoryType=ECR, ImageConfiguration.Port=8765,
     RuntimeEnvironmentSecrets={DOCENTER_COOKIES_JSON,DOCENTER_PROXY_API_KEY[,EMAIL,PASSWORD]},
     AuthenticationConfiguration.AccessRoleArn=<ECR access role>)
```

Grab the resulting **Service ARN** and **public URL** from the `create-service`
output — those become `-ServiceArn` and `-HealthUrl` for all future deploys.

> Prefer clicking? You can also create the service in the App Runner console: source
> = your ECR image, port 8765, add the 2–4 secrets as runtime env **secrets**, attach
> the instance role. Then use the CLI/script for subsequent rollouts.

---

## 6. Deploy / update

```powershell
pwsh components/docenter/docenter_mcp/deploy-shared.ps1 `
  -Account 111122223333 -Region us-east-1 -AwsProfile my-team `
  -ServiceArn    arn:aws:apprunner:us-east-1:111122223333:service/docenter-mcp-shared/abc123 `
  -AccessRoleArn arn:aws:iam::111122223333:role/AppRunnerECRAccessRole `
  -HealthUrl     https://<your-service-host>/healthz `
  -CookieSecretArn   <cookie ARN> `
  -ApiKeySecretArn   <api-key ARN> `
  -EmailSecretArn    <email ARN> `      # optional (self-heal)
  -PasswordSecretArn <password ARN>     # optional (self-heal)
```

It runs: preflight → resolve next image tag → `docker build --provenance=false
--sbom=false --platform linux/amd64` → ECR push → `apprunner update-service` (empty
env vars + the shared secrets) → wait for `RUNNING` → `GET /healthz` must be 200.

Rollback: `-Tag <previous> -SkipBuild`.

---

## 7. Point clients at it

Health: `GET https://<your-url>/healthz` → `200 {"status":"ok",...}`.

**Copilot CLI / VS Code / Claude Code** (`~/.copilot/mcp-config.json` or `.vscode/mcp.json`):

```jsonc
{ "mcpServers": { "DOCenterLive": {
    "type": "http",
    "url": "https://<your-url>/mcp",
    "headers": { "X-API-Key": "<the api-key value>" }
} } }
```

**Copilot Studio → Add MCP server** (the dialog in the screenshot):

| Field | Value |
|---|---|
| Server URL | `https://<your-url>/mcp` |
| Authentication | **API key** |
| Parameter type | **Header** |
| Header name | `X-API-Key` |
| Key value | the `DOCENTER_PROXY_API_KEY` secret value (share over a secure channel) |

---

## 8. Verify

- [ ] `aws apprunner describe-service … --query Service.Status` → `RUNNING`
- [ ] `RuntimeEnvironmentVariables` is empty (single-credential mode) and
      `RuntimeEnvironmentSecrets` lists only the 2–4 shared secrets
- [ ] `GET /healthz` → 200
- [ ] one authenticated `search_docs` / `find_bundles` call returns real results

---

## References

- `deploy-shared.ps1` — this mode's deploy wrapper (reuses `deploy.ps1`).
- `README.md` — tools, env vars, and the session auto self-heal detail.
- `Dockerfile`, `entrypoint.sh` — image + cookie materialisation.
- `docs/runbooks/2026-07-11-docenter-mcp-aws-deployment-runbook.md` — the full
  operational runbook (self-heal verification, IAM notes, CI/CD path).
