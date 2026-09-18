<#
.SYNOPSIS
  One-time: migrate the DOCenter MCP App Runner secrets from AWS Secrets Manager to
  SSM Parameter Store SecureString (Standard tier = free) - the "$0 setup".

.DESCRIPTION
  For each mapping below, reads the value from the existing Secrets Manager secret and
  writes it to an SSM SecureString parameter (same value, cheaper home). The shared
  portal cookie (actwise/docenter-cookie) is intentionally NOT migrated: the server now
  cold-start bootstraps the shared cookie from DOCENTER_EMAIL / DOCENTER_PASSWORD (and
  self-heals on expiry), so it no longer needs to be stored.

  Secret VALUES are only ever passed to the AWS CLI via a temp JSON file (file://), never
  on the command line, and the temp file is deleted immediately - nothing lands in shell
  history or process args.

  DRY-RUN BY DEFAULT (prints what it would do). Pass -Apply to actually write the params.

  Order of operations:
    1. .\migrate-secrets-to-ssm.ps1                 # dry-run - review the plan
    2. .\migrate-secrets-to-ssm.ps1 -Apply          # create the 5 SSM SecureString params
    3. Attach the printed policy to the App Runner INSTANCE role (grants ssm:GetParameters
       + kms:Decrypt via the aws/ssm key). The role name is looked up and printed for you.
    4. .\deploy.ps1                                  # already points at the SSM ARNs
    5. Verify /healthz + a real search, then delete the old Secrets Manager secrets to stop
       billing (delete commands are printed at the end; this script does NOT delete them).

.NOTES
  Requires: aws CLI v2, an AWS profile with read on the secrets + write on SSM + read on
  App Runner. Windows PowerShell 5.1 compatible (no pwsh-only syntax).
#>
[CmdletBinding()]
param(
  [string] $AwsProfile = "iamuser-general",
  [string] $Region     = "us-east-1",
  [string] $Account    = "432124802878",
  [string] $ServiceArn = "arn:aws:apprunner:us-east-1:432124802878:service/actwise-docenter/7b64f15bf7c74d7987cc19ecd47723ee",
  [switch] $Apply
)

$ErrorActionPreference = "Stop"
$Aws = @("--region", $Region)
if ($AwsProfile) { $Aws += @("--profile", $AwsProfile) }

function Step([string]$m) { Write-Host "==> $m" -ForegroundColor Cyan }

# Secrets Manager secret-id  ->  SSM SecureString parameter name.
# (Cookie deliberately excluded - bootstrap replaces it.)
$map = [ordered]@{
  "actwise/api-key"                    = "/actwise/docenter/api-key"
  "actwise/docenter-email"             = "/actwise/docenter/email"
  "actwise/docenter-password"          = "/actwise/docenter/password"
  "actwise/docenter-user-token-secret" = "/actwise/docenter/user-token-secret"
  "actwise/docenter-broker-secret"     = "/actwise/docenter/broker-secret"
}

Step "Preflight: AWS identity"
$who = (aws sts get-caller-identity @Aws --query "Arn" --output text)
if ($LASTEXITCODE -ne 0) { throw "aws sts get-caller-identity failed" }
Write-Host "    identity: $who"
if (-not $Apply) { Write-Host "    MODE: DRY-RUN (pass -Apply to write params)" -ForegroundColor Yellow }
else             { Write-Host "    MODE: APPLY (will create/overwrite SSM params)" -ForegroundColor Yellow }

foreach ($sm in $map.Keys) {
  $ssm = $map[$sm]
  Step "$sm  ->  SSM SecureString $ssm"
  $val = (aws secretsmanager get-secret-value @Aws --secret-id $sm --query "SecretString" --output text)
  if ($LASTEXITCODE -ne 0 -or -not $val) { throw "could not read Secrets Manager secret '$sm'" }

  if (-not $Apply) {
    Write-Host ("    [dry-run] would put SecureString ({0} chars)" -f $val.Length)
    continue
  }

  # Pass the value via a temp JSON file so it never appears on the command line.
  $payload = [ordered]@{ Name = $ssm; Type = "SecureString"; Value = $val; Overwrite = $true }
  $tmp = New-TemporaryFile
  try {
    $json = ($payload | ConvertTo-Json -Depth 3)
    # PS 5.1 Set-Content -Encoding utf8 writes a BOM the AWS CLI JSON parser rejects; write BOM-less.
    [System.IO.File]::WriteAllText($tmp.FullName, $json, (New-Object System.Text.UTF8Encoding($false)))
    aws ssm put-parameter @Aws --cli-input-json "file://$($tmp.FullName)" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "put-parameter $ssm failed" }
    Write-Host "    written." -ForegroundColor Green
  } finally {
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
  }
}

# --- Instance role: what to grant -------------------------------------------
Step "Resolving the App Runner INSTANCE role (needs ssm:GetParameters on the new params)"
$instanceRoleArn = (aws apprunner describe-service @Aws --service-arn $ServiceArn --query "Service.InstanceConfiguration.InstanceRoleArn" --output text 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $instanceRoleArn -or $instanceRoleArn -eq "None") {
  Write-Host "    (could not read InstanceRoleArn - set one on the service first)" -ForegroundColor Yellow
  $instanceRoleArn = "YOUR_APP_RUNNER_INSTANCE_ROLE"
}
Write-Host "    instance role: $instanceRoleArn"

$resourceArns = @()
foreach ($ssm in $map.Values) { $resourceArns += "arn:aws:ssm:${Region}:${Account}:parameter$ssm" }
$policy = [ordered]@{
  Version   = "2012-10-17"
  Statement = @(
    [ordered]@{ Sid = "ReadDocenterSsmParams"; Effect = "Allow"; Action = "ssm:GetParameters"; Resource = $resourceArns },
    [ordered]@{ Sid = "DecryptSsmDefaultKey";  Effect = "Allow"; Action = "kms:Decrypt"; Resource = "*";
                Condition = @{ StringEquals = @{ "kms:ViaService" = "ssm.${Region}.amazonaws.com" } } }
  )
}
$policyJson = ($policy | ConvertTo-Json -Depth 6)

Write-Host ""
Step "NEXT - grant the instance role read access to the new params:"
Write-Host "  Save this as ssm-read-policy.json, then:" -ForegroundColor DarkGray
$roleName = ($instanceRoleArn -split "/")[-1]
Write-Host "  aws iam put-role-policy --role-name $roleName --policy-name DocenterSsmRead --policy-document file://ssm-read-policy.json" -ForegroundColor Gray
Write-Host ""
Write-Host $policyJson
Write-Host ""

Step "AFTER a verified deploy - delete the old Secrets Manager secrets to stop billing:"
foreach ($sm in $map.Keys) {
  Write-Host "  aws secretsmanager delete-secret --region $Region --secret-id $sm --force-delete-without-recovery" -ForegroundColor DarkGray
}
Write-Host "  aws secretsmanager delete-secret --region $Region --secret-id actwise/docenter-cookie --force-delete-without-recovery" -ForegroundColor DarkGray
Write-Host "  (the cookie secret is no longer used - bootstrap replaces it)" -ForegroundColor DarkGray

if (-not $Apply) { Write-Host "`nDRY-RUN complete. Re-run with -Apply to write the SSM params." -ForegroundColor Yellow }
else             { Write-Host "`nSSM params written. Attach the policy above, then run .\deploy.ps1." -ForegroundColor Green }


