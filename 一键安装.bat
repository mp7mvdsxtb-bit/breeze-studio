@echo off
chcp 65001 >nul
set PYTHONUTF8=1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0webui\setup.ps1" %*
if errorlevel 1 (
  echo.
  echo Installation failed. See the error above, then run this file again to resume.
  pause
  exit /b 1
)
echo.
echo Installation verified. Run the studio launcher to start.
pause
