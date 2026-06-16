#!/bin/bash
# Launch the local task farm dashboard
set -e

DASHBOARD_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$DASHBOARD_DIR/.venv"

echo "════════════════════════════════════════"
echo " Fluidity Marine — Task Farm Dashboard"
echo "════════════════════════════════════════"

# Create venv if missing
if [ ! -d "$VENV_DIR" ]; then
    echo "→ Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Activate and install deps
source "$VENV_DIR/bin/activate"
pip install -q flask flask-cors psutil

echo "→ Starting dashboard server..."
echo "→ Open http://localhost:8080 in Brave"
echo ""

cd "$DASHBOARD_DIR"
python3 dashboard_server.py
