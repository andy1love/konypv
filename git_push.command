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
DOCS_DIR="$REPO_ROOT/docs"
ARCHIVE_DIR="$DOCS_DIR/push_log_archive"
CONSOLIDATED_LOG="$DOCS_DIR/push_log.md"
LOG_MAX_BYTES=$((12 * 1024 * 1024))  # 12 MB

mkdir -p "$LOGS_DIR" "$ARCHIVE_DIR"

TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")
TIMESTAMP_FILE=$(date "+%Y%m%d_%H%M%S")
BRANCH=$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null)
PRE_PUSH_HEAD=$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo "")

echo "Branch: $BRANCH"
echo ""
echo "Working tree status:"
GIT_STATUS=$(git -C "$REPO_ROOT" status --short)
if [ -n "$GIT_STATUS" ]; then
  echo "$GIT_STATUS"
else
  echo "(nothing to stage)"
fi
echo ""

COMMIT_MSG=""
EXPLANATION=""
if [ -n "$GIT_STATUS" ]; then
  DEFAULT_MSG="auto: $TIMESTAMP"
  read -p "Commit message [auto: $TIMESTAMP]: " USER_MSG
  if [ -z "$USER_MSG" ]; then
    COMMIT_MSG="$DEFAULT_MSG"
  else
    COMMIT_MSG="$USER_MSG"
  fi

  read -p "What changed in this push? (optional, goes in log): " EXPLANATION
  echo ""
  echo "Staging and committing..."
  git -C "$REPO_ROOT" add -A
  git -C "$REPO_ROOT" commit -m "$COMMIT_MSG"
else
  COMMIT_MSG="(no new commit — working tree was clean)"
fi

echo ""
echo "Pushing to origin/$BRANCH..."
PUSH_OUTPUT=$(git -C "$REPO_ROOT" push origin "$BRANCH" 2>&1)
PUSH_EXIT=$?
echo "$PUSH_OUTPUT"

POST_PUSH_HEAD=$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo "")
PRE_SHORT="${PRE_PUSH_HEAD:0:7}"
POST_SHORT="${POST_PUSH_HEAD:0:7}"

if [ $PUSH_EXIT -eq 0 ]; then
  PUSH_STATUS="✓ SUCCESS"
  PUSH_STATUS_PLAIN="SUCCESS"
else
  PUSH_STATUS="✗ FAILED (exit $PUSH_EXIT)"
  PUSH_STATUS_PLAIN="FAILED"
fi

# Collect diff stats (only if HEAD changed)
DIFF_STAT=""
FILES_CHANGED_LIST=""
COMMITS_PUSHED=""
if [ "$PRE_PUSH_HEAD" != "$POST_PUSH_HEAD" ] && [ -n "$PRE_PUSH_HEAD" ]; then
  DIFF_STAT=$(git -C "$REPO_ROOT" diff --stat "$PRE_PUSH_HEAD" HEAD 2>/dev/null)
  FILES_CHANGED_LIST=$(git -C "$REPO_ROOT" diff --name-only "$PRE_PUSH_HEAD" HEAD 2>/dev/null)
  COMMITS_PUSHED=$(git -C "$REPO_ROOT" log --oneline "$PRE_PUSH_HEAD..HEAD" 2>/dev/null)
fi

# ── Per-push report ──────────────────────────────────────────────────────────
PER_PUSH_FILE="$LOGS_DIR/push_${TIMESTAMP_FILE}.md"

{
  echo "# Push Report — $TIMESTAMP"
  echo ""
  echo "| Field         | Value                         |"
  echo "|---------------|-------------------------------|"
  echo "| Branch        | $BRANCH                       |"
  echo "| Commit Before | $PRE_SHORT                    |"
  echo "| Commit After  | $POST_SHORT                   |"
  echo "| Message       | $COMMIT_MSG                   |"
  echo "| Status        | $PUSH_STATUS                  |"
  echo ""

  if [ -n "$EXPLANATION" ]; then
    echo "## Summary"
    echo ""
    echo "$EXPLANATION"
    echo ""
  fi

  if [ -n "$DIFF_STAT" ]; then
    echo "## Files Changed"
    echo '```diff'
    echo "$DIFF_STAT"
    echo '```'
    echo ""
  fi

  if [ -n "$COMMITS_PUSHED" ]; then
    echo "## Commits Pushed"
    while IFS= read -r line; do
      echo "- $line"
    done <<< "$COMMITS_PUSHED"
    echo ""
  fi

  echo "## Push Output"
  echo '```'
  echo "$PUSH_OUTPUT"
  echo '```'
} > "$PER_PUSH_FILE"

# ── Consolidated log (with rotation) ─────────────────────────────────────────
if [ -f "$CONSOLIDATED_LOG" ]; then
  LOG_SIZE=$(stat -f%z "$CONSOLIDATED_LOG" 2>/dev/null || stat -c%s "$CONSOLIDATED_LOG" 2>/dev/null || echo 0)
  if [ "$LOG_SIZE" -ge "$LOG_MAX_BYTES" ]; then
    ARCHIVE_NAME="push_log_${TIMESTAMP_FILE}.md"
    mv "$CONSOLIDATED_LOG" "$ARCHIVE_DIR/$ARCHIVE_NAME"
    echo "# Push Log (archive: $ARCHIVE_NAME)" > "$CONSOLIDATED_LOG"
    echo "" >> "$CONSOLIDATED_LOG"
  fi
fi

if [ ! -f "$CONSOLIDATED_LOG" ]; then
  echo "# Push Log" > "$CONSOLIDATED_LOG"
  echo "" >> "$CONSOLIDATED_LOG"
fi

# Build the files-changed bullet list for the consolidated entry
FILES_BULLET=""
if [ -n "$FILES_CHANGED_LIST" ]; then
  while IFS= read -r fname; do
    [ -z "$fname" ] && continue
    # Extract +/- numbers from diff --stat for this file
    STAT_LINE=$(git -C "$REPO_ROOT" diff --stat "$PRE_PUSH_HEAD" HEAD -- "$fname" 2>/dev/null | head -1)
    INS=$(echo "$STAT_LINE" | grep -oE '[0-9]+ insertion' | grep -oE '[0-9]+' || echo "")
    DEL=$(echo "$STAT_LINE" | grep -oE '[0-9]+ deletion'  | grep -oE '[0-9]+' || echo "")
    DETAIL=""
    [ -n "$INS" ] && DETAIL="+$INS"
    [ -n "$DEL" ] && DETAIL="$DETAIL / -$DEL"
    if [ -n "$DETAIL" ]; then
      FILES_BULLET="${FILES_BULLET}- \`$fname\` ($DETAIL)\n"
    else
      FILES_BULLET="${FILES_BULLET}- \`$fname\`\n"
    fi
  done <<< "$FILES_CHANGED_LIST"
fi

{
  echo "---"
  echo ""
  echo "## $TIMESTAMP · $PUSH_STATUS"
  echo ""
  echo "**Branch:** $BRANCH"
  echo "**Commit:** $PRE_SHORT → $POST_SHORT"
  echo "**Message:** $COMMIT_MSG"
  echo ""
  if [ -n "$EXPLANATION" ]; then
    echo "**Summary:** $EXPLANATION"
    echo ""
  fi
  if [ -n "$FILES_BULLET" ]; then
    echo "**Files changed:**"
    printf "%b" "$FILES_BULLET"
    echo ""
  fi
  echo "---"
  echo ""
} >> "$CONSOLIDATED_LOG"

echo ""
echo "Done. Push log saved to:"
echo "  Per-push:    $PER_PUSH_FILE"
echo "  Consolidated: $CONSOLIDATED_LOG"
echo ""
echo "Press any key to close."
read -n 1
