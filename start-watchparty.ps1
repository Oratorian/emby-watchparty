$ErrorActionPreference = 'Stop'

$watchPartyRoot = $PSScriptRoot
$watchPartyPython = Join-Path $watchPartyRoot '.venv\Scripts\python.exe'

function Get-WatchPartyDotEnvValue([string] $Name) {
    $envPath = Join-Path $watchPartyRoot '.env'
    if (-not (Test-Path -LiteralPath $envPath)) { return $null }
    $line = Get-Content -LiteralPath $envPath | Where-Object {
        $_ -match "^$([regex]::Escape($Name))="
    } | Select-Object -First 1
    if ($null -eq $line) { return $null }
    return ($line -split '=', 2)[1].Trim()
}

$watchPartyPort = $env:WATCH_PARTY_PORT
if ([string]::IsNullOrWhiteSpace($watchPartyPort)) {
    $watchPartyPort = Get-WatchPartyDotEnvValue 'WATCH_PARTY_PORT'
}
if ([string]::IsNullOrWhiteSpace($watchPartyPort)) { $watchPartyPort = '5000' }
$parsedPort = 0
if (-not [int]::TryParse($watchPartyPort, [ref]$parsedPort) -or $parsedPort -lt 1 -or $parsedPort -gt 65535) {
    $watchPartyPort = '5000'
}

$watchPartyPrefix = $env:APP_PREFIX
if ([string]::IsNullOrWhiteSpace($watchPartyPrefix)) {
    $watchPartyPrefix = Get-WatchPartyDotEnvValue 'APP_PREFIX'
}
if ([string]::IsNullOrWhiteSpace($watchPartyPrefix)) {
    $bootstrapPath = Join-Path $watchPartyRoot 'data\bootstrap.json'
    if (Test-Path -LiteralPath $bootstrapPath) {
        try { $watchPartyPrefix = (Get-Content -Raw -LiteralPath $bootstrapPath | ConvertFrom-Json).APP_PREFIX } catch { }
    }
}
if ($null -eq $watchPartyPrefix) { $watchPartyPrefix = '' }
$watchPartyPrefix = $watchPartyPrefix.TrimEnd('/')
$watchPartyBaseUrl = "http://localhost:$watchPartyPort$watchPartyPrefix"

# Avoid starting a second instance when configured endpoint is already healthy.
try {
    $healthResponse = Invoke-RestMethod -Uri "$watchPartyBaseUrl/api/health" -TimeoutSec 3
    if ($healthResponse.status -eq 'ok') {
        Write-Host "Emby Watch Party already running: $watchPartyBaseUrl/"
        exit 0
    }
} catch {
    # Expected when WatchParty is not running yet.
}

Set-Location -LiteralPath $watchPartyRoot
Write-Host "Web UI: $watchPartyBaseUrl/"
Write-Host "If setup is required, open $watchPartyBaseUrl/setup and use token printed below."
& $watchPartyPython -m backend.app
exit $LASTEXITCODE
