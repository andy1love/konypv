#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GoPro Time-Lapse Ingest: Copy JPG files from SD card to pool directory.

- Bin names: YYYYMMDD_GP_## or YYYYMMDD_GP_##_<suffix> (e.g., 20260207_GP_01 or 20260207_GP_01_test)
- Asks ONLY for an optional suffix; base date+seq is fixed by the script.
- Checks for duplicates across the entire GP_JPGSEQ_POOL_ROOT
- Duplicate handling:
    [1] Copy UNIQUE only
    [2] Copy ALL
    [Enter] Abort
- Duplicate reports are stored in GP_JPGSEQ_POOL_ROOT/_reports/

Env/config used (set by launcher or shell):
  CONFIG_PATH (optional, JSON config)
  GP_JPGSEQ_POOL_ROOT  -> e.g., /Volumes/LaCie/GP_JPGSEQ_POOL
  GP_DAILIES_ROLL      -> e.g., /Volumes/Untitled/DCIM/100GOPRO
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
    if not cfg_path:
        # Use gopro_config.json in the same directory as this script
        script_dir = Path(__file__).parent
        cfg_path = str(script_dir / "gopro_config.json")
    
    if Path(cfg_path).exists():
        with open(cfg_path, "r") as f:
            return json.load(f)
    return {}

CFG = load_cfg()

GP_JPGSEQ_POOL_ROOT = Path(os.getenv("GP_JPGSEQ_POOL_ROOT") or CFG.get("GP_JPGSEQ_POOL_ROOT"))
if not GP_JPGSEQ_POOL_ROOT:
    die("GP_JPGSEQ_POOL_ROOT not found in config.json or environment variables")

def resolve_dailies_roll() -> Path:
    """Resolve GP_DAILIES_ROLL from env (single path) or config (string or list of candidates)."""
    env_val = os.getenv("GP_DAILIES_ROLL")
    if env_val:
        return Path(env_val)
    cfg_val = CFG.get("GP_DAILIES_ROLL")
    if not cfg_val:
        die("GP_DAILIES_ROLL not found in config.json or environment variables")
    # Support a single string or a list of candidate paths
    if isinstance(cfg_val, str):
        return Path(cfg_val)
    if isinstance(cfg_val, list):
        found = [Path(p) for p in cfg_val if Path(p).exists()]
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            print("Multiple SD cards detected:")
            for i, p in enumerate(found, 1):
                print(f"  [{i}] {p}")
            while True:
                choice = input("Select SD card number: ").strip()
                if choice.isdigit() and 1 <= int(choice) <= len(found):
                    return found[int(choice) - 1]
                print("Invalid choice. Try again.")
        # None found yet — return first candidate (will fail at mount check later)
        return Path(cfg_val[0])
    die(f"GP_DAILIES_ROLL has unexpected type: {type(cfg_val)}")

GP_DAILIES_ROLL = resolve_dailies_roll()
if not GP_DAILIES_ROLL:
    die("GP_DAILIES_ROLL not found in config.json or environment variables")

# Bin pattern: YYYYMMDD_GP_## or YYYYMMDD_GP_##_<suffix>
BIN_PATTERN = re.compile(r"^(?P<ymd>\d{8})_GP_(?P<seq>\d{2})(?:_.*)?$")
SUFFIX_ALLOWED = re.compile(r"^[A-Za-z0-9_-]+$")  # what we allow as a suffix (no spaces)

# JPG file extensions
JPG_EXTS = {".jpg", ".jpeg", ".JPG", ".JPEG"}

# ---------- Helpers ----------
def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)

def is_hidden_or_metadata(p: Path) -> bool:
    return p.name.startswith(".") or p.name.startswith("._")

def list_jpg_files_recursive(root: Path) -> List[Path]:
    """List all JPG files recursively, skipping hidden/metadata files."""
    files = []
    for p in root.rglob("*"):
        if p.is_file() and not is_hidden_or_metadata(p) and p.suffix in JPG_EXTS:
            files.append(p)
    return files

def index_entire_media_root(root: Path) -> Dict[Tuple[str, int], List[Path]]:
    """
    Build an index of (basename, size) -> [absolute paths] for ALL files under GP_JPGSEQ_POOL_ROOT.
    Skips hidden/AppleDouble. This lets us catch dupes across all bins.
    """
    idx: Dict[Tuple[str, int], List[Path]] = {}
    if not root.exists():
        return idx
    for f in list_jpg_files_recursive(root):
        try:
            key = (f.name, f.stat().st_size)
        except FileNotFoundError:
            continue
        idx.setdefault(key, []).append(f)
    return idx

def find_dups_and_uniques_against_root(src_dir: Path, root_index: Dict[Tuple[str, int], List[Path]]):
    """
    Compare SD card files (src_dir) against global index (GP_JPGSEQ_POOL_ROOT).
    """
    dups = []
    uniques = []
    for f in list_jpg_files_recursive(src_dir):
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
      YYYYMMDD_GP_## or YYYYMMDD_GP_##_<suffix>
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
    return f"{ymd}_GP_{next_seq:02d}"

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

def write_duplicate_report(media_pool_root: Path, roll_name: str, dups):
    """
    Write CSV under GP_JPGSEQ_POOL_ROOT/_reports, including the full
    absolute paths for where duplicates were found.
    """
    reports_dir = media_pool_root / "_reports"
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
    print(f"=== GoPro Time-Lapse Ingest ===")
    print(f"Source (dailies_roll): {GP_DAILIES_ROLL}")
    print(f"GP_JPGSEQ_POOL_ROOT:  {GP_JPGSEQ_POOL_ROOT}")

    if not GP_DAILIES_ROLL.exists():
        die(f"dailies_roll not found: {GP_DAILIES_ROLL}")
    if not GP_DAILIES_ROLL.is_dir():
        die(f"dailies_roll is not a folder: {GP_DAILIES_ROLL}")

    # Ensure GP_JPGSEQ_POOL_ROOT exists
    GP_JPGSEQ_POOL_ROOT.mkdir(parents=True, exist_ok=True)

    # Show latest 3 bins
    existing_bins = parse_existing_bins(GP_JPGSEQ_POOL_ROOT)
    if existing_bins:
        last_three = existing_bins[-3:]
        print("\nRecent bins (alphanumeric, newest at bottom):")
        for (_ymd, _seq, path) in last_three:
            try:
                files = list_jpg_files_recursive(path)
                total = sum(f.stat().st_size for f in files)
                print(f"  • {path.name}   ({len(files)} files, {pretty_size(total)})")
            except Exception:
                print(f"  • {path.name}")
    else:
        print("\nNo existing YYYYMMDD_GP_## bins found in pool.")

    # Index ALL bins under GP_JPGSEQ_POOL_ROOT
    print("\nIndexing ALL bins under GP_JPGSEQ_POOL_ROOT for duplicates...")
    root_index = index_entire_media_root(GP_JPGSEQ_POOL_ROOT)
    print(f"Indexed {sum(len(v) for v in root_index.values())} file instances across all bins.")

    # Compare SD card against global index
    print("Scanning dailies_roll for duplicates (global check)...")
    dups, uniques = find_dups_and_uniques_against_root(GP_DAILIES_ROLL, root_index)

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

    dest = GP_JPGSEQ_POOL_ROOT / dailies_roll_name
    if dest.exists():
        die(f"Destination folder already exists: {dest}")

    # Handle duplicates
    if dups:
        print(f"\n⚠️  Detected {len(dups)} duplicate file(s) somewhere under GP_JPGSEQ_POOL_ROOT.")
        report_path = write_duplicate_report(GP_JPGSEQ_POOL_ROOT, dailies_roll_name, dups)
        print(f"Duplicate report written: {report_path}")

        choice = input("Enter [1] Copy UNIQUE only, [2] Copy ALL, or press Enter to abort: ").strip()
        if choice == "1":
            if not uniques:
                die("No unique files to copy. Exiting.")
            to_copy = uniques
        elif choice == "2":
            to_copy = list_jpg_files_recursive(GP_DAILIES_ROLL)
        else:
            die("Aborted by user.")
    else:
        to_copy = list_jpg_files_recursive(GP_DAILIES_ROLL)

    # Copy only the selected set into destination
    print(f"\nCopying {len(to_copy)} file(s):\n  {GP_DAILIES_ROLL}\n→ {dest}\n")
    copy_selected_files(GP_DAILIES_ROLL, dest, to_copy)

    # Summary
    print("✅ Copy complete.")
    dst_files = list_jpg_files_recursive(dest)
    dst_total = sum(f.stat().st_size for f in dst_files) if dst_files else 0
    print(f"Files copied: {len(dst_files)}")
    print(f"Total size:   {pretty_size(dst_total)}")
    print(f"Destination:  {dest}")

if __name__ == "__main__":
    main()
