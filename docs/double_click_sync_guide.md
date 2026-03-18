# Double-Click Git Sync Feature

A macOS `.command` file that lets a user pull the latest code from GitHub by double-clicking a file in Finder — no Terminal knowledge required.

---

## How It Works

1. User double-clicks `git_pull.command` in Finder
2. macOS opens it in Terminal and runs it as a bash script
3. The script pulls from `origin main`
4. Terminal stays open until the user presses a key

---

## Files to Create

### 1. `git_pull.command`

Place this in the repo (e.g. a `_scripts/` folder or the root).

```bash
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG="$SCRIPT_DIR/_py/config.json"

if [ ! -f "$CONFIG" ]; then
  echo "ERROR: config.json not found at $CONFIG"
  echo "Copy config.template.json to config.json and fill in required values."
  read -n 1
  exit 1
fi

REPO_ROOT="$SCRIPT_DIR"

echo "Pulling latest from GitHub..."
echo "Repo: $REPO_ROOT"
cd "$REPO_ROOT" && git pull origin main

echo ""
echo "Done. Press any key to close."
read -n 1
```

> **Adjust the `CONFIG` path** if your project's config file lives somewhere other than `_py/config.json`. If your project has no config file, remove the `if [ ! -f "$CONFIG" ]` block entirely.

---

### 2. Make It Executable

After creating the file, run this once in Terminal:

```bash
chmod +x git_pull.command
```

Without this step, macOS will refuse to run it.

---

### 3. `config.template.json` (optional but recommended)

If your project uses a config file that should not be committed (e.g. contains local paths or secrets), provide a template so users know what to fill in:

```json
{
  "ROOT": "/absolute/path/to/your/project"
}
```

Commit `config.template.json` to the repo. Add `config.json` to `.gitignore`.

---

### 4. `config_loader.py` (optional — for Python scripts that need config values)

If your Python scripts need to read from `config.json`, use a loader like this:

```python
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"

with open(CONFIG_PATH) as f:
    _config = json.load(f)

ROOT = Path(_config["ROOT"])
```

Import `ROOT` (or other keys) from this module wherever needed. This keeps path resolution centralized.

---

## `.gitignore` Entries to Add

```
_py/config.json
```

---

## Setup Instructions for New Users

Include these steps in your project's README:

1. Clone the repo
2. Copy `config.template.json` → `config.json` and fill in your values
3. Double-click `git_pull.command` to pull updates anytime

---

## Key Constraints

- **macOS only** — `.command` files are a macOS convention; they open in Terminal.app automatically
- The script pulls from `origin main` — change `main` to your default branch name if different
- `SCRIPT_DIR` resolves to the folder containing the `.command` file, so keep the file inside the repo
- The `read -n 1` at the end holds Terminal open so the user can read any output before the window closes
