$ErrorActionPreference = 'Stop'

$watchPartyRoot = 'C:\Users\Dnord\Documents\Codex\2026-08-01\computer-plugin-computer-use-openai-bundled\work\emby-watchparty'
$watchPartyPython = Join-Path $watchPartyRoot '.venv\Scripts\python.exe'

# Avoid starting a second instance when port 5000 is already healthy.
try {
    $healthResponse = Invoke-RestMethod -Uri 'http://127.0.0.1:5000/api/health' -TimeoutSec 3
    if ($healthResponse.status -eq 'ok') {
        exit 0
    }
} catch {
    # Expected when WatchParty is not running yet.
}

Set-Location -LiteralPath $watchPartyRoot
& $watchPartyPython -m backend.app
exit $LASTEXITCODE
