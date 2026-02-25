# セットアップガイド / Setup Guide

## 前提条件 / Prerequisites

- macOS
- Python 3 installed — check by opening Terminal and running: `python3 --version`
- Git installed — check by running: `git --version`
- DaVinci Resolve installed (required for import scripts)
- The LaCie drive (or whatever drive you are setting up) is plugged in and mounted

---

## Step 1 — Clone the repo onto the drive

The scripts must live at `_scripts/` directly on the ROOT directory (the root of your ext hdd like: /Volumes/LaCie/_scripts).
Open Terminal and run:

```bash
git clone https://github.com/andy1love/konypv.git /Volumes/LaCie/_scripts
```

> Replace `/Volumes/LaCie` with the ROOT (the actual mount name of your drive if it is different.
> You can check the name in Finder under Locations in the sidebar.

---

## Step 2 — Create your config.json

The repo includes a template. Copy it:

```bash
cp /Volumes/LaCie/_scripts/_py/config.template.json /Volumes/LaCie/_scripts/_py/config.json
```

Then open `config.json` in any text editor and fill in the values below.

---

## Step 3 — Edit config.json

### `ROOT` (required)
Set this to the root path of your drive exactly as it appears in `/Volumes/`:

```json
"ROOT": "/Volumes/LaCie"
```

This one value automatically derives:
- `MEDIA_POOL_ROOT` → `ROOT/MEDIA_POOL`
- `PROXY_POOL_ROOT` → `ROOT/PROXY_POOL`
- Script paths for ingest and import

### `DEFAULT_DAILIES_ROLL` (required)
The path to the SD card's clip folder. For Sony cameras this is usually:

```json
"DEFAULT_DAILIES_ROLL": "/Volumes/Untitled/PRIVATE/M4ROOT/CLIP"
```

Leave this as-is unless your camera card mounts under a different name.

### `user_dest_roots` (required for sync)
Each person's personal backup drive. Set the volume name for each user
as it appears in Finder:

```json
"user_dest_roots": {
  "ANDY": "/Volumes/MY_DRIVE_NAME",
  ...
}
```

Leave entries for users whose drives you don't have — they will simply fail
gracefully when sync is attempted.

---

## Step 4 — Apply Finder color tags (one-time)

Right-click `apply_tags.command` → **Open** (required the first time on a new Mac —
macOS will otherwise block it as an unidentified app).

This tags each script with its color in Finder so they are easy to identify:

| Script | Color |
|---|---|
| `workflow_launcher.py` | Green |
| `proxy_maker.py` | Blue |
| `proxy_packager.py` | Purple |
| `sync_pools.py` | Yellow |
| `wipe_sdcard.py` | Red |
| `_py/` folder | Green |

You only need to run this once. Future pulls via `git_pull.command` will re-apply
tags automatically to any scripts that were updated.

---

## Step 5 — You're done

Run any script directly:

```bash
python3 /Volumes/LaCie/_scripts/_py/workflow_launcher.py
```

Or double-click it from Finder.

`MEDIA_POOL` and `PROXY_POOL` folders will be created automatically on first run
if they don't exist yet.

---

## Updating scripts in the future

Right-click `git_pull.command` → **Open** the very first time (same Gatekeeper
reason as above). After that, double-clicking works permanently.

This will pull the latest changes from GitHub and automatically apply
color tags in Finder to any scripts that were updated.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `.command` file blocked by macOS | Right-click → Open instead of double-clicking |
| `config.json not found` | Complete Step 2 |
| `ROOT volume not mounted` | Plug in the drive before running |
| `python3: command not found` | Install Python 3 from python.org |
| `git: command not found` | Install Xcode Command Line Tools: `xcode-select --install` |
| SD card not found | Check `DEFAULT_DAILIES_ROLL` path — card may mount under a different name |
