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
LOGS_DIR="$REPO_ROOT/_logs"
mkdir -p "$LOGS_DIR"

TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")
TIMESTAMP_FILE=$(date "+%Y%m%d_%H%M%S")
BRANCH=$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null)
OLD_HEAD=$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo "")

echo "Pulling latest from GitHub..."
echo "Repo: $REPO_ROOT"
PULL_OUTPUT=$(cd "$REPO_ROOT" && git pull origin main 2>&1)
PULL_EXIT=$?
echo "$PULL_OUTPUT"

# Write pull log
NEW_HEAD=$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo "")
OLD_SHORT="${OLD_HEAD:0:7}"
NEW_SHORT="${NEW_HEAD:0:7}"

if [ $PULL_EXIT -eq 0 ]; then
  PULL_STATUS="✓ SUCCESS"
else
  PULL_STATUS="✗ FAILED (exit $PULL_EXIT)"
fi

DIFF_STAT=""
FILES_CHANGED=""
COMMITS_PULLED=""
if [ -n "$OLD_HEAD" ] && [ "$OLD_HEAD" != "$NEW_HEAD" ]; then
  DIFF_STAT=$(git -C "$REPO_ROOT" diff --stat "$OLD_HEAD" HEAD 2>/dev/null)
  FILES_CHANGED=$(git -C "$REPO_ROOT" diff --name-only "$OLD_HEAD" HEAD 2>/dev/null)
  COMMITS_PULLED=$(git -C "$REPO_ROOT" log --oneline "$OLD_HEAD..HEAD" 2>/dev/null)
fi

LATEST_COMMIT_HASH=$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null)
LATEST_COMMIT_MSG=$(git -C "$REPO_ROOT" log -1 --pretty="%s" 2>/dev/null)
LATEST_COMMIT_DATE=$(git -C "$REPO_ROOT" log -1 --pretty="%ci" 2>/dev/null)

{
  echo "# Pull Report — $TIMESTAMP"
  echo ""
  echo "## Repo Version"
  echo ""
  echo "| Field          | Value                                        |"
  echo "|----------------|----------------------------------------------|"
  echo "| Branch         | $BRANCH                                      |"
  echo "| HEAD           | $LATEST_COMMIT_HASH                          |"
  echo "| Latest commit  | $LATEST_COMMIT_MSG                           |"
  echo "| Committed      | $LATEST_COMMIT_DATE                          |"
  echo "| Pull status    | $PULL_STATUS                                 |"
  echo ""

  if [ "$OLD_HEAD" = "$NEW_HEAD" ]; then
    echo "> Already up to date — no new commits."
    echo ""
  else
    echo "**Before:** \`$OLD_SHORT\`  →  **After:** \`$NEW_SHORT\`"
    echo ""
    if [ -n "$COMMITS_PULLED" ]; then
      echo "## Commits Pulled"
      while IFS= read -r line; do
        echo "- $line"
      done <<< "$COMMITS_PULLED"
      echo ""
    fi
    if [ -n "$DIFF_STAT" ]; then
      echo "## Files Changed"
      echo '```diff'
      echo "$DIFF_STAT"
      echo '```'
      echo ""
    fi
  fi

  echo "## Pull Output"
  echo '```'
  echo "$PULL_OUTPUT"
  echo '```'
} > "$LOGS_DIR/pull_${TIMESTAMP_FILE}.md"

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
echo "Done. Pull log saved to:"
echo "  $LOGS_DIR/pull_${TIMESTAMP_FILE}.md"
echo ""
echo "Press any key to close."
read -n 1
