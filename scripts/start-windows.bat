@echo off
rem IntelliInventory - one-click start for Windows. Double-click this file.
rem First run installs everything (a few minutes). Then open http://localhost:8000
cd /d "%~dp0.."

where uv >nul 2>nul
if errorlevel 1 (
  echo [!] uv is not installed. Open PowerShell and run:
  echo     powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  echo     then close and reopen this window.
  pause
  exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
  echo [!] Node.js is not installed. Download the LTS version from https://nodejs.org and run this again.
  pause
  exit /b 1
)

if not exist "frontend\dist\index.html" (
  echo Building the web app ^(first run only^)...
  pushd frontend
  call npm install --no-audit --no-fund || (popd & pause & exit /b 1)
  call npm run build || (popd & pause & exit /b 1)
  popd
)

echo Starting IntelliInventory on http://localhost:8000  (close this window to stop)
start "" cmd /c "timeout /t 8 >nul & start http://localhost:8000"
cd backend
uv run uvicorn app.main:app --port 8000
pause
