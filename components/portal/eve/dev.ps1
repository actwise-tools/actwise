<#
  ActWise eve portal — local dev launcher.

  Handles two environment requirements that plain `eve dev` does not:

  1. Corporate TLS interception. Node's TLS stack does not trust the corporate
     root CA, so outbound HTTPS to the Vercel AI Gateway fails with
     UNABLE_TO_GET_ISSUER_CERT_LOCALLY. We point NODE_EXTRA_CA_CERTS at a PEM
     exported from the Windows trust store (generated on first run).

  2. Node runtime. eve 0.24.5 requires Node >= 24. If a suitable node is not the
     default, set $env:EVE_NODE_DIR to a folder containing node.exe before running.

  See also: src/internal/authored-module-map-loader.ts (eve 0.24.5 dev-host shim).

  Usage:
    ./dev.ps1                 # eve dev --no-ui on the default port
    ./dev.ps1 -Port 3333      # pick a port
    ./dev.ps1 -Ui             # run the terminal UI instead of --no-ui
#>
param(
  [int]$Port = 3333,
  [switch]$Ui
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# --- 1. Corporate CA bundle for Node -----------------------------------------
$caPath = Join-Path $env:USERPROFILE ".actwise\corp-ca-bundle.pem"
if (-not (Test-Path $caPath)) {
  Write-Host "Exporting Windows trust store to $caPath ..."
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $caPath) | Out-Null
  $sb = New-Object System.Text.StringBuilder
  foreach ($store in @('Cert:\LocalMachine\Root','Cert:\LocalMachine\CA','Cert:\CurrentUser\Root','Cert:\CurrentUser\CA')) {
    Get-ChildItem $store -ErrorAction SilentlyContinue | ForEach-Object {
      try {
        $b = [Convert]::ToBase64String($_.RawData, 'InsertLineBreaks')
        [void]$sb.AppendLine("# " + $_.Subject)
        [void]$sb.AppendLine("-----BEGIN CERTIFICATE-----")
        [void]$sb.AppendLine($b)
        [void]$sb.AppendLine("-----END CERTIFICATE-----")
      } catch {}
    }
  }
  Set-Content -Path $caPath -Value $sb.ToString() -Encoding ascii
}
$env:NODE_EXTRA_CA_CERTS = $caPath

# --- 2. Node runtime (eve needs >= 24) ---------------------------------------
function Get-NodeMajor([string]$dir) {
  $exe = if ($dir) { Join-Path $dir "node.exe" } else { "node" }
  try { $v = (& $exe --version) 2>$null } catch { return 0 }
  if ($v -match 'v(\d+)\.') { return [int]$Matches[1] } else { return 0 }
}
# Prefer an explicit override, else the default node, else known local 24+ installs.
$candidates = @($env:EVE_NODE_DIR, $null, "$env:USERPROFILE\scoop\apps\nodejs\current", "C:\temp\node24\node-v24.18.0-win-x64")
$nodeDir = $null
foreach ($c in $candidates) {
  if ($c -and -not (Test-Path (Join-Path $c "node.exe"))) { continue }
  if ((Get-NodeMajor $c) -ge 24) { $nodeDir = $c; break }
}
if ($null -eq $nodeDir -and (Get-NodeMajor $null) -lt 24) {
  throw "eve requires Node >= 24. Set `$env:EVE_NODE_DIR to a Node 24+ folder."
}
if ($nodeDir) { $env:PATH = "$nodeDir;" + $env:PATH }
Write-Host "Using node $(& node --version)"

# --- 3. Run the Next.js frontend (withEve boots the eve agent alongside) ------
Set-Location $here
$nextBin = Join-Path $here "node_modules\next\dist\bin\next"
& node $nextBin dev -p $Port
