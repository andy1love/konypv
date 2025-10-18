#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wipe_sdcard.py

Checks that ALL files in DEFAULT_DAILIES_ROLL (from config.json) exist somewhere
under MEDIA_POOL_ROOT (all users). If all exist, optionally wipes the card.
If some are missing, offers to copy the missing ones into MEDIA_POOL_ROOT/NAME/_orphan.

Config (JSON):
  MEDIA_POOL_ROOT
  DEFAULT_DAILIES_ROLL
  user_keymap { letter: NAME }
"""

import os
import sys
import json
import shutil
from pathlib import Path
from typing import Dict, List, Tuple

# ---------------- Helpers ----------------
def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)

def load_cfg() -> dict:
    cfg_path = os.getenv("CONFIG_PATH")
    if not cfg_path:
        # Use config.json in the same directory as this script
        script_dir = Path(__file__).parent
        cfg_path = str(script_dir / "config.json")
    
    cfg_file = Path(cfg_path)
    if not cfg_file.exists():
        die(f"Config not found: {cfg_file}")
    with cfg_file.open() as f:
        return json.load(f)

def pick_user(keymap: dict) -> str:
    print("Select user:")
    for letter in sorted(keymap.keys()):
        print(f"  [{letter}] {keymap[letter]}")
    while True:
        choice = input("Enter letter (or q to quit): ").strip().lower()
        if choice == "q":
            die("Aborted.", code=0)
        if choice in keymap:
            return keymap[choice]
        print("Invalid choice. Try again.")

def is_hidden_or_metadata(p: Path) -> bool:
    return p.name.startswith(".") or p.name.startswith("._")

def list_files_recursive(root: Path) -> List[Path]:
    return [p for p in root.rglob("*") if p.is_file() and not is_hidden_or_metadata(p)]

def index_media_root(root: Path) -> Dict[Tuple[str, int], List[Path]]:
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

def pretty_size(num_bytes: int) -> str:
    units = ["B","KB","MB","GB","TB"]
    size = float(num_bytes)
    i = 0
    while size >= 1024 and i < len(units)-1:
        size /= 1024
        i += 1
    return f"{size:.1f}{units[i]}"

def copy_with_progress(srcs: List[Path], dst_dir: Path):
    dst_dir.mkdir(parents=True, exist_ok=True)
    total = sum(p.stat().st_size for p in srcs if p.exists())
    done = 0
    bar_len = 30

    def show():
        pct = (done / total) * 100 if total else 100.0
        filled = int(bar_len * pct / 100)
        bar = "#" * filled + "-" * (bar_len - filled)
        sys.stdout.write(f"\rCopying… [{bar}] {pct:6.2f}%  ({pretty_size(done)}/{pretty_size(total)})")
        sys.stdout.flush()

    show()
    for s in srcs:
        target = dst_dir / s.name
        if target.exists():
            stem, suf = target.stem, target.suffix
            i = 1
            while True:
                alt = dst_dir / f"{stem}__dup{i}{suf}"
                if not alt.exists():
                    target = alt
                    break
                i += 1
        with s.open("rb") as fi, target.open("wb") as fo:
            while True:
                buf = fi.read(8 * 1024 * 1024)
                if not buf:
                    break
                fo.write(buf)
                done += len(buf)  # type: ignore
                show()
        try:
            shutil.copystat(s, target)
        except Exception:
            pass
    sys.stdout.write("\n"); sys.stdout.flush()

def wipe_directory_contents(root: Path):
    for p in root.iterdir():
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
        except Exception as e:
            print(f"⚠️  Could not remove {p}: {e}")

# ---------------- Main ----------------
def main():
    CFG = load_cfg()
    # Fail fast for required config keys
    if "MEDIA_POOL_ROOT" not in CFG:
        die("Config missing 'MEDIA_POOL_ROOT' key.")
    if "DEFAULT_DAILIES_ROLL" not in CFG:
        die("Config missing 'DEFAULT_DAILIES_ROLL' key.")

    MEDIA_POOL_ROOT = Path(CFG["MEDIA_POOL_ROOT"])
    DAILIES_ROLL = Path(CFG["DEFAULT_DAILIES_ROLL"])
    keymap = CFG.get("user_keymap", {})

    if not keymap:
        die("Config missing user_keymap.")

    NAME = pick_user(keymap)

    print("=== SD Card Verify & Wipe ===")
    print(f"MEDIA_POOL_ROOT: {MEDIA_POOL_ROOT}")
    print(f"DEFAULT_DAILIES_ROLL: {DAILIES_ROLL}")
    print(f"NAME (for _orphan): {NAME}")

    if not MEDIA_POOL_ROOT.exists():
        die(f"MEDIA_POOL_ROOT not found: {MEDIA_POOL_ROOT}")
    if not DAILIES_ROLL.exists():
        die(f"DEFAULT_DAILIES_ROLL not found: {DAILIES_ROLL}")
    if not DAILIES_ROLL.is_dir():
        die(f"DEFAULT_DAILIES_ROLL is not a folder: {DAILIES_ROLL}")

    card_files = list_files_recursive(DAILIES_ROLL)
    if not card_files:
        die("No files found on the card (after skipping hidden/metadata).")

    total_card = sum(p.stat().st_size for p in card_files)
    print(f"\nCard contains {len(card_files)} files, {pretty_size(total_card)}.")

    print("\nIndexing MEDIA_POOL_ROOT (all users)…")
    root_index = index_media_root(MEDIA_POOL_ROOT)
    print(f"Indexed {sum(len(v) for v in root_index.values())} file instances under media pool.")

    missing, present = [], []
    for f in card_files:
        try:
            key = (f.name, f.stat().st_size)
        except FileNotFoundError:
            continue
        if key in root_index:
            present.append(f)
        else:
            missing.append(f)

    print("\n=== Summary ===")
    print(f"Present in media pool: {len(present)}")
    print(f"Missing from pool:     {len(missing)}")

    if missing:
        miss_size = sum(p.stat().st_size for p in missing)
        print(f"Missing total size:    {pretty_size(miss_size)}")

        orphan_dir = MEDIA_POOL_ROOT / NAME / "_orphan"
        print(f"\nSome files are missing. You can copy them to: {orphan_dir}")
        choice = input("Copy missing files to _orphan? [y/N]: ").strip().lower()
        if choice in ("y", "yes"):
            print("\nCopying missing files…")
            copy_with_progress(missing, orphan_dir)
            print("✅ Copy complete.")
        else:
            print("Skipped copying missing files.")
        print("\nNo destructive action taken. You can run this script again after review.")
        return

    print("\n✅ All files from the card exist somewhere in the media pool.")
    confirm = input("Type 'delete' to WIPE ALL CONTENTS of the card folder (or press Enter to abort): ").strip()
    if confirm.lower() == "delete":
        print("\nWiping card contents…")
        wipe_directory_contents(DAILIES_ROLL)
        print("🧹 SD card folder cleaned (contents deleted).")
    else:
        print("Aborted. Card was NOT modified.")

if __name__ == "__main__":
    main()
