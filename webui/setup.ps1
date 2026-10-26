param([switch]$VerifyOnly)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$root = Split-Path $PSScriptRoot -Parent
try {
    if (![Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { throw 'Requires Windows x64 and an NVIDIA CUDA GPU.' }
    $python = $null
    $candidates = @((Join-Path $root 'venv\Scripts\python.exe'), (Join-Path $root 'tools\python312\python.exe'))
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $ErrorActionPreference = 'Continue'
        $detected = & $launcher.Source -3.12 -c 'import sys; print(sys.executable)' 2>$null
        $ErrorActionPreference = 'Stop'
        if ($LASTEXITCODE -eq 0) { $candidates += $detected }
    }
    $systemPython = Get-Command python -ErrorAction SilentlyContinue
    if ($systemPython -and $systemPython.Source -notlike '*WindowsApps*') { $candidates += $systemPython.Source }
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            & $candidate -c 'import sys,struct; sys.exit(0 if sys.version_info[:2]==(3,12) and struct.calcsize(chr(80))==8 else 1)'
            if ($LASTEXITCODE -eq 0) { $python = $candidate; break }
        }
    }
    if (!$python) {
        if ($VerifyOnly) { throw 'Python 3.12 x64 not installed. Run without -VerifyOnly first.' }
        Write-Host 'Installing official Python 3.12.10 (current user only)...'
        $tools = Join-Path $root 'tools'
        New-Item -ItemType Directory -Force $tools | Out-Null
        $installer = Join-Path $tools 'python-3.12.10-amd64.exe'
        Invoke-WebRequest -UseBasicParsing 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $installer -TimeoutSec 180
        $signature = Get-AuthenticodeSignature -LiteralPath $installer
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') { throw 'Python installer signature verification failed.' }
        $target = Join-Path $tools 'python312'
        $process = Start-Process -FilePath $installer -ArgumentList @('/quiet','InstallAllUsers=0',('TargetDir="'+$target+'"'),'PrependPath=0','Include_launcher=0','Include_test=0','Include_pip=1','Shortcuts=0','AssociateFiles=0') -PassThru -Wait -WindowStyle Hidden
        if ($process.ExitCode -ne 0 -and $process.ExitCode -ne 3010) { throw ('Python installation failed: '+$process.ExitCode) }
        $python = Join-Path $target 'python.exe'
        if (!(Test-Path -LiteralPath $python)) { throw 'Python executable not found after installation.' }
    }
    $env:PYTHONUTF8 = '1'
    $arguments = @((Join-Path $PSScriptRoot 'setup_runtime.py'),'--root',$root)
    if ($VerifyOnly) { $arguments += '--verify-only' }
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Setup or verification failed. Fix the error shown above and run again.' }
    exit 0
} catch { Write-Host ('ERROR: '+$_.Exception.Message) -ForegroundColor Red; exit 1 }
