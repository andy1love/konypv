#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG="$SCRIPT_DIR/_py/config.json"

if [ ! -f "$CONFIG" ]; then
  echo "ERROR: config.json not found at $CONFIG"
  echo "Copy config.template.json to config.json and set repo_root."
  read -n 1
  exit 1
fi

REPO_ROOT=$(python3 -c "import json; print(json.load(open('$CONFIG'))['repo_root'])")

echo "Pulling latest from GitHub..."
echo "Repo: $REPO_ROOT"
cd "$REPO_ROOT" && git pull origin main
echo ""
echo "Done. Press any key to close."
read -n 1
