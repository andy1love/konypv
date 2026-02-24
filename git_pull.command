#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG="$SCRIPT_DIR/_py/config.json"

if [ ! -f "$CONFIG" ]; then
  echo "ERROR: config.json not found at $CONFIG"
  echo "Copy config.template.json to config.json and set ROOT."
  read -n 1
  exit 1
fi

REPO_ROOT="$SCRIPT_DIR"
OLD_HEAD=$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo "")

echo "Pulling latest from GitHub..."
echo "Repo: $REPO_ROOT"
cd "$REPO_ROOT" && git pull origin main

# Apply Finder color tags to changed .py files
if [ -n "$OLD_HEAD" ]; then
  git -C "$REPO_ROOT" diff --name-only "$OLD_HEAD" HEAD \
    | python3 -c "
import sys, plistlib, subprocess, os

SCRIPT_DIR = '$REPO_ROOT'

FILE_TAGS = {
    'proxy_maker.py':       ('Blue',   4),
    'proxy_packager.py':    ('Purple', 3),
    'sync_pools.py':        ('Yellow', 5),
    'wipe_sdcard.py':       ('Red',    6),
    'workflow_launcher.py': ('Green',  2),
}

def tag(path, name, idx):
    data = plistlib.dumps([f'{name}\n{idx}'], fmt=plistlib.FMT_BINARY)
    subprocess.run(
        ['xattr', '-wx', 'com.apple.metadata:_kMDItemUserTags', data.hex(), path],
        check=True
    )
    print(f'  tagged {os.path.basename(path)} -> {name}')

tagged_any = False
for line in sys.stdin:
    base = os.path.basename(line.strip())
    if base in FILE_TAGS:
        full = os.path.join(SCRIPT_DIR, '_py', base)
        if os.path.exists(full):
            name, idx = FILE_TAGS[base]
            tag(full, name, idx)
            tagged_any = True

if tagged_any:
    tag(os.path.join(SCRIPT_DIR, '_py'), 'Green', 2)
"
fi

echo ""
echo "Done. Press any key to close."
read -n 1
