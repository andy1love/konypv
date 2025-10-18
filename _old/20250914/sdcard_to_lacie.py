#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ingest dailies roll into user media_pool with date-based folder naming.

- Bin names: YYYYMMDD_## or YYYYMMDD_##_<suffix> (e.g., 20250906_05 or 20250906_05_ya)
- Asks ONLY for an optional suffix; base date+seq is fixed by the script.
- Checks for duplicates across the entire MEDIA_POOL_ROOT (all users)
- Duplicate handling:
    [1] Copy UNIQUE only
    [2] Copy ALL
    [Enter] Abort
- Duplicate reports are stored in MEDIA_POOL/_reports/

Env/config used (set by launcher or shell):
  CONFIG_PATH (optional, JSON config)
  NAME                  -> user name in ALL CAPS (e.g., ANDY)
  MEDIA_POOL_ROOT       -> e.g., /Volumes/LaCie/MEDIA_POOL
  DAILIES_ROLL          -> e.g., /Volumes/Untitled/PRIVATE/M4ROOT/CLIP
"""

import os
import re
import sys
import csv
import json
import shutil
import datetime
from pathlib import Path
from typing import Dict, Tuple, List, Optional

# ---------- Config / Environment ----------
def load_cfg() -> dict:
    cfg_path = os.getenv("CONFIG_PATH")
    if cfg_path and Path(cfg_path).exists():
        with open(cfg_path, "r") as f:
            return json.load(f)
    return {}

CFG = load_cfg()

NAME = os.getenv("NAME") or "ANDY"
MEDIA_POOL_ROOT = Path(os.getenv("MEDIA_POOL_ROOT") or CFG.get("MEDIA_POOL_ROOT", "/Volumes/LaCie/MEDIA_POOL"))
MEDIA_POOL = MEDIA_POOL_ROOT / NAME
DAILIES_ROLL = Path(os.getenv("DAILIES_ROLL") or CFG.get("DEFAULT_DAILIES_ROLL", "/Volumes/Untitled/PRIVATE/M4ROOT/CLIP"))

# Accept optional suffix after seq, e.g. 20250906_05_ya
BIN_PATTERN = re.compile(r"^(?P<ymd>\d{8})_(?P<seq>\d{2})(?:_.*)?$")
SUFFIX_ALLOWED = re.compile(r"^[A-Za-z0-9_-]+$")  # what we allow as a suffix (no spaces)

# ---------- Helpers ----------
def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)

def is_hidden_or_metadata(p: Path) -> bool:
    return p.name.startswith(".") or p.name.startswith("._")

def list_files_recursive(root: Path) -> List[Path]:
    return [p for p in root.rglob("*") if p.is_file() and not is_hidden_or_metadata(p)]

def index_entire_media_root(root: Path) -> Dict[Tuple[str, int], List[Path]]:
    """
    Build an index of (basename, size) -> [absolute paths] for ALL files under MEDIA_POOL_ROOT.
    Skips hidden/AppleDouble. This lets us catch dupes in any user's pool.
    """
    idx: Dict[Tuple[str, int], List[Path]] = {}
    if not root.exists():
        return idx
    for f in list_files_recursive(root):
        try:
            key = (f.name, f.stat().st_size)
        except FileNotFoundError:
            continue
        idx.setdefault(key, []).append(f)
    return idx

def find_dups_and_uniques_against_root(src_dir: Path, root_index: Dict[Tuple[str, int], List[Path]]):
    """
    Compare SD card files (src_dir) against global index (MEDIA_POOL_ROOT).
    """
    dups = []
    uniques = []
    for f in list_files_recursive(src_dir):
        try:
            key = (f.name, f.stat().st_size)
        except FileNotFoundError:
            continue
        if key in root_index:
            dups.append((f, root_index[key]))
        else:
            uniques.append(f)
    return dups, uniques

def parse_existing_bins(pool: Path) -> List[Tuple[str, int, Path]]:
    """
    Return list of tuples: (ymd, seq, path) for folders matching:
      YYYYMMDD_## or YYYYMMDD_##_<suffix>
    Sorted ascending so newest is last.
    """
    out: List[Tuple[str, int, Path]] = []
    if not pool.exists():
        return out
    for p in pool.iterdir():
        if p.is_dir():
            m = BIN_PATTERN.match(p.name)
            if m:
                ymd = m.group("ymd")
                seq = int(m.group("seq"))
                out.append((ymd, seq, p))
    out.sort(key=lambda t: (t[0], t[1]))
    return out

def suggest_next_bin_name(today: datetime.date, existing: List[Tuple[str, int, Path]]) -> str:
    ymd = today.strftime("%Y%m%d")
    todays = [seq for (d, seq, _) in existing if d == ymd]
    next_seq = (max(todays) + 1) if todays else 1
    return f"{ymd}_{next_seq:02d}"

def pretty_size(num_bytes: int) -> str:
    units = ["B","KB","MB","GB","TB"]
    size = float(num_bytes)
    i = 0
    while size >= 1024 and i < len(units)-1:
        size /= 1024
        i += 1
    return f"{size:.1f}{units[i]}"

# ---------- Copy with progress ----------
def copy_file_with_progress(src: Path, dst: Path, total_bytes: int, progress_state: dict, bufsize: int = 8 * 1024 * 1024):
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open("rb") as fsrc, dst.open("wb") as fdst:
        while True:
            buf = fsrc.read(bufsize)
            if not buf:
                break
            fdst.write(buf)
            progress_state['done_bytes'] += len(buf)
            done = progress_state['done_bytes']
            pct = (done / total_bytes) * 100 if total_bytes > 0 else 100.0
            bar_len = 30
            filled = int(bar_len * pct / 100)
            bar = "#" * filled + "-" * (bar_len - filled)
            sys.stdout.write(f"\rCopying… [{bar}] {pct:6.2f}%  ({pretty_size(done)}/{pretty_size(total_bytes)})")
            sys.stdout.flush()
    try:
        shutil.copystat(src, dst)
    except Exception:
        pass

def copy_selected_files(src_root: Path, dst_root: Path, files: List[Path]):
    if dst_root.exists():
        die(f"Destination already exists: {dst_root}")
    total_bytes = sum(f.stat().st_size for f in files if f.exists())
    progress_state = {'done_bytes': 0}
    for s in files:
        rel = s.relative_to(src_root)
        d = dst_root / rel
        copy_file_with_progress(s, d, total_bytes, progress_state)
    sys.stdout.write("\n")
    sys.stdout.flush()

def write_duplicate_report(media_pool_for_user: Path, roll_name: str, dups):
    """
    Write CSV under the SELECTED USER's MEDIA_POOL/_reports, but include the full
    absolute paths for where duplicates were found (across all users).
    """
    reports_dir = media_pool_for_user / "_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    csv_path = reports_dir / f"duplicate_report_{roll_name}.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source_name","source_size","source_path","existing_paths"])
        for src, matches in dups:
            try:
                size = src.stat().st_size
            except FileNotFoundError:
                size = 0
            w.writerow([src.name, size, str(src), " | ".join(str(m.resolve()) for m in matches)])
    return csv_path

# ---------- Main ----------
def main():
    print(f"=== Dailies Ingest for {NAME} ===")
    print(f"Source (dailies_roll): {DAILIES_ROLL}")
    print(f"MEDIA_POOL_ROOT:       {MEDIA_POOL_ROOT}")
    print(f"User media_pool:       {MEDIA_POOL}")

    if not DAILIES_ROLL.exists():
        die(f"dailies_roll not found: {DAILIES_ROLL}")
    if not DAILIES_ROLL.is_dir():
        die(f"dailies_roll is not a folder: {DAILIES_ROLL}")

    # Ensure user MEDIA_POOL exists
    MEDIA_POOL.mkdir(parents=True, exist_ok=True)

    # Show latest 3 bins for THIS user (suffix-aware)
    existing_bins = parse_existing_bins(MEDIA_POOL)
    if existing_bins:
        last_three = existing_bins[-3:]
        print("\nRecent bins (alphanumeric, newest at bottom):")
        for (_ymd, _seq, path) in last_three:
            try:
                files = list_files_recursive(path)
                total = sum(f.stat().st_size for f in files)
                print(f"  • {path.name}   ({len(files)} files, {pretty_size(total)})")
            except Exception:
                print(f"  • {path.name}")
    else:
        print("\nNo existing YYYYMMDD_## bins found in user media_pool.")

    # Index ALL users under MEDIA_POOL_ROOT
    print("\nIndexing ALL media pools under MEDIA_POOL_ROOT for duplicates...")
    root_index = index_entire_media_root(MEDIA_POOL_ROOT)
    print(f"Indexed {sum(len(v) for v in root_index.values())} file instances across all users.")

    # Compare SD card against global index
    print("Scanning dailies_roll for duplicates (global check)...")
    dups, uniques = find_dups_and_uniques_against_root(DAILIES_ROLL, root_index)

    # Suggest base folder name and ask ONLY for optional suffix
    suggestion_base = suggest_next_bin_name(datetime.date.today(), existing_bins)
    print(f"\nSuggested base FOLDER NAME: {suggestion_base}")
    print("Enter optional suffix. Example: test  → becomes  "
          f"{suggestion_base}_test")
    print("Press Enter for no suffix.")
    while True:
        suffix = input("Suffix: ").strip()
        if suffix == "":
            dailies_roll_name = suggestion_base
            break
        if SUFFIX_ALLOWED.match(suffix):
            dailies_roll_name = f"{suggestion_base}_{suffix}"
            break
        print("Invalid suffix. Use letters, numbers, underscore, or hyphen only (no spaces). Try again.")

    dest = MEDIA_POOL / dailies_roll_name
    if dest.exists():
        die(f"Destination folder already exists: {dest}")

    # Handle duplicates
    if dups:
        print(f"\n⚠️  Detected {len(dups)} duplicate file(s) somewhere under MEDIA_POOL_ROOT.")
        report_path = write_duplicate_report(MEDIA_POOL, dailies_roll_name, dups)
        print(f"Duplicate report written: {report_path}")

        choice = input("Enter [1] Copy UNIQUE only, [2] Copy ALL, or press Enter to abort: ").strip()
        if choice == "1":
            if not uniques:
                die("No unique files to copy. Exiting.")
            to_copy = uniques
        elif choice == "2":
            to_copy = list_files_recursive(DAILIES_ROLL)
        else:
            die("Aborted by user.")
    else:
        to_copy = list_files_recursive(DAILIES_ROLL)

    # Copy only the selected set into THIS user's destination
    print(f"\nCopying {len(to_copy)} file(s):\n  {DAILIES_ROLL}\n→ {dest}\n")
    copy_selected_files(DAILIES_ROLL, dest, to_copy)

    # Summary
    print("✅ Copy complete.")
    dst_files = list_files_recursive(dest)
    dst_total = sum(f.stat().st_size for f in dst_files) if dst_files else 0
    print(f"Files copied: {len(dst_files)}")
    print(f"Total size:   {pretty_size(dst_total)}")
    print(f"Destination:  {dest}")

if __name__ == "__main__":
    main()
