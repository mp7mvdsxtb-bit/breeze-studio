$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$url = 'http://127.0.0.1:7861'
try {
    $state = Invoke-RestMethod "$url/api/state" -TimeoutSec 2
    if ($state.app -ne 'breeze-studio') { throw 'Port in use' }
    Start-Process $url
    exit 0
} catch {}
$env:PYTHONUTF8 = '1'
# Updates only run while the studio is stopped.
& (Join-Path $root 'venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'updater.py')
Start-Process -FilePath (Join-Path $root 'venv\Scripts\python.exe') -ArgumentList @('-u', ('"' + (Join-Path $PSScriptRoot 'server.py') + '"')) -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $root 'webui.log') -RedirectStandardError (Join-Path $root 'webui-error.log')
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    Start-Sleep -Milliseconds 500
    try {
        $state = Invoke-RestMethod "$url/api/state" -TimeoutSec 2
        if ($state.app -eq 'breeze-studio') {
            Start-Process $url
            exit 0
        }
    } catch {}
}
Write-Host '启动失败，请查看 breeze-runtime\webui-error.log。'
exit 1
