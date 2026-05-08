# TODO

## Preflight: ensure Homebrew rsync 3.x before sync runs

**Problem.** macOS ships `/usr/bin/rsync` (openrsync), which crashes mid-clone with `Assertion failed: blk_match, blocks.c:303` when `--append` is used. `sync_pools.py:106-111` (`pick_rsync_bin`) prefers `/opt/homebrew/bin/rsync` when present and silently falls back to `/usr/bin/rsync` when not — so a fresh machine without `brew install rsync` will hit the crash on first full clone, with the destination left in a partial state.

**Goal.** A user who clones this repo on a new machine should never reach `sync_pools.py` without Homebrew rsync 3.x installed.

### Option A — Auto-install at repo install time (preferred)

When we build the `install.command` / `install.bat` (see `docs/installer_guide.md`), have it:

1. Check for Homebrew (`command -v brew`). If missing, install it.
2. Run `brew install rsync` (idempotent — does nothing if already installed).
3. Verify `/opt/homebrew/bin/rsync --version` reports `3.x`.
4. Fail loudly with a clear message if any of the above doesn't succeed.

This makes rsync 3.x a guaranteed precondition of a successful repo install.

### Option B — Runtime preflight in `sync_pools.py`

Tighten `pick_rsync_bin()` so that when `/opt/homebrew/bin/rsync` is missing, the script:

1. Prints a clear error explaining why openrsync is unsafe.
2. Offers to run `brew install rsync` for the user (or aborts with the exact command to run).
3. Exits non-zero — does **not** silently fall through to `/usr/bin/rsync`.

Cheaper than Option A, but only catches the problem the first time someone tries to sync, after the install is already "done."

### Recommendation

Do **both**: Option A is the real fix; Option B is the safety net for any path that bypasses the installer (e.g., `git clone` by hand).

### Related context

- `docs/DEPENDENCIES.md` now lists `rsync 3.x (Homebrew)` as required.
- The bug was first hit on 2026-05-07: `/usr/bin/rsync` exit code -6 (SIGABRT) during `[0] All users — full clone to CLONE_ROOT`. After `brew install rsync`, the next run picked up `/opt/homebrew/bin/rsync` automatically and synced cleanly.
