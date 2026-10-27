@echo off
REM FINN start for Windows.  start.bat          real data
REM                          start.bat sample   synthetic, labelled sample data
REM                          start.bat check    test data sources
cd /d %~dp0
cd backend
if not exist .venv (
  echo Setting up the backend (first run only)...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
if not exist .env copy .env.example .env
if "%1"=="check" (
  python -m scripts.refresh check
  goto :eof
)
set FINN_SAMPLE_MODE=0
if "%1"=="sample" set FINN_SAMPLE_MODE=1
start "FINN backend" cmd /k "call .venv\Scripts\activate.bat && python -m uvicorn finn.api:app --host 0.0.0.0 --port 8000"
cd ..\frontend
if not exist node_modules call npm install --no-audit --no-fund
start "FINN frontend" cmd /k "npm run dev"
echo.
echo FINN is starting. Open http://localhost:3000 in a minute.
echo Close the two FINN windows to stop it.
