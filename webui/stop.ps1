$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$server = Join-Path $PSScriptRoot 'server.py'
$modelPath = Join-Path (Split-Path $root -Parent) 'models\Breeze-TTS-2'
$processes = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' }
foreach ($process in $processes) {
    if ($process.CommandLine -like ('*' + $server + '*') -or ($process.CommandLine -like '*-m breeze_infer.api*' -and $process.CommandLine -like ('*' + $modelPath + '*'))) {
        Stop-Process -Id $process.ProcessId -ErrorAction SilentlyContinue
    }
}
Write-Host 'Breeze Studio 已停止。'
