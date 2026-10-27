#!/usr/bin/env bash
# FINN one-command start for macOS / Linux.
#   ./start.sh          real data (Yahoo, BSE/NSE, Gemini if a key is set)
#   ./start.sh sample   clearly-labelled synthetic data, no internet sources needed
#   ./start.sh check    test which data sources are reachable from this machine
set -euo pipefail
cd "$(dirname "$0")"
ROOT=$(pwd)

say() { printf "\n\033[1m%s\033[0m\n" "$*"; }

command -v python3 >/dev/null || { echo "Python 3.10+ is required: https://www.python.org/downloads/"; exit 1; }
command -v node >/dev/null || { echo "Node.js 20+ is required: https://nodejs.org/"; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || { echo "Python 3.10 or newer is required (you have $(python3 --version))."; exit 1; }
node -e 'process.exit(parseInt(process.versions.node) >= 20 ? 0 : 1)' || { echo "Node.js 20 or newer is required (you have $(node -v))."; exit 1; }

# --- backend ------------------------------------------------------------------------------
cd "$ROOT/backend"
if [ ! -d .venv ]; then
  say "Setting up the backend (first run only, about a minute)…"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
if [ ! -f .venv/.installed ] || [ requirements.txt -nt .venv/.installed ]; then
  pip install -q --upgrade pip
  pip install -q -r requirements.txt
  touch .venv/.installed
fi
[ -f .env ] || { cp .env.example .env; echo "Created backend/.env. Add your GEMINI_API_KEY there to enable the AI features."; }

if [ "${1:-}" = "check" ]; then
  python -m scripts.refresh check
  exit 0
fi

# --- frontend -----------------------------------------------------------------------------
cd "$ROOT/frontend"
if [ ! -d node_modules ]; then
  say "Installing the frontend (first run only)…"
  npm install --no-audit --no-fund
fi

MODE=0
[ "${1:-}" = "sample" ] && MODE=1

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

say "Starting FINN…"
( cd "$ROOT/backend" && FINN_SAMPLE_MODE=$MODE python -m uvicorn finn.api:app --host 0.0.0.0 --port 8000 ) &
( cd "$ROOT/frontend" && npm run dev ) &

IP=$( (ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}') || true)
sleep 6
say "FINN is running"
echo "  On this computer:  http://localhost:3000"
[ -n "$IP" ] && echo "  On your phone:     http://$IP:3000   (same Wi-Fi network)"
echo "  Backend API:       http://localhost:8000/docs"
[ "$MODE" = "1" ] && echo "  Mode: SAMPLE DATA (synthetic, labelled in the app)"
echo "  Press Ctrl+C to stop."
wait
