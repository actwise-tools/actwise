<#
  push-to-postman.ps1
  Pushes the hand-built collection + environment to the Postman workspace.
  Reads credentials from postman/.env (gitignored). Creates on first run,
  updates (PUT) on subsequent runs when a UID is recorded in .env.

  Usage:  pwsh -File ./push-to-postman.ps1
#>
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

# --- load .env ---
$envVars = @{}
Get-Content (Join-Path $root '.env') | ForEach-Object {
  if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
  $k, $v = $_ -split '=', 2
  $envVars[$k.Trim()] = $v.Trim()
}
$apiKey = $envVars['POSTMAN_API_KEY']
$ws     = $envVars['POSTMAN_WORKSPACE_ID']
if (-not $apiKey) { throw 'POSTMAN_API_KEY missing in postman/.env' }

function Invoke-Postman($method, $url, $body) {
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
  $req = [System.Net.HttpWebRequest]::Create($url)
  $req.Method = $method
  $req.ContentType = 'application/json'
  $req.Headers.Add('X-API-Key', $apiKey)
  $req.ContentLength = $bytes.Length
  $s = $req.GetRequestStream(); $s.Write($bytes, 0, $bytes.Length); $s.Close()
  try {
    $resp = $req.GetResponse()
    return (New-Object IO.StreamReader($resp.GetResponseStream())).ReadToEnd()
  } catch [System.Net.WebException] {
    $err = (New-Object IO.StreamReader($_.Exception.Response.GetResponseStream())).ReadToEnd()
    throw "Postman API error: $err"
  }
}

# --- collection ---
$colRaw = Get-Content (Join-Path $root 'ActOne.postman_collection.json') -Raw
$colUid = $envVars['POSTMAN_COLLECTION_UID']
if ($colUid) {
  Write-Host "Updating collection $colUid ..."
  $r = Invoke-Postman 'PUT' "https://api.getpostman.com/collections/$colUid" ('{"collection":' + $colRaw + '}')
} else {
  Write-Host 'Creating collection ...'
  $r = Invoke-Postman 'POST' "https://api.getpostman.com/collections?workspace=$ws" ('{"collection":' + $colRaw + '}')
}
Write-Host $r

# --- environment ---
$envRaw = Get-Content (Join-Path $root 'ActOne.local.postman_environment.json') -Raw
$envUid = $envVars['POSTMAN_ENVIRONMENT_UID']
if ($envUid) {
  Write-Host "Updating environment $envUid ..."
  $r = Invoke-Postman 'PUT' "https://api.getpostman.com/environments/$envUid" ('{"environment":' + $envRaw + '}')
} else {
  Write-Host 'Creating environment ...'
  $r = Invoke-Postman 'POST' "https://api.getpostman.com/environments?workspace=$ws" ('{"environment":' + $envRaw + '}')
}
Write-Host $r
