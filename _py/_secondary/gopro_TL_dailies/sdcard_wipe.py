#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sdcard_wipe.py — GoPro SD card verify & wipe

Standalone script that:
1. Resolves which GoPro SD card is mounted (GP_DAILIES_ROLL)
2. Lists every file on the card
3. Verifies that each file already exists in GP_JPGSEQ_POOL_ROOT (by name + size)
4. If any files are missing, copies them to GP_JPGSEQ_POOL_ROOT/_orphan/YYYYMMDD_GP_##
5. Once all files are accounted for, lets the user type "delete" to wipe the card

Config keys (gopro_config.json):
  GP_DAILIES_ROLL      – SD card DCIM path(s)
  GP_JPGSEQ_POOL_ROOT  – pool root to verify against
"""

import os
import re
import sys
import json
import shutil
import subprocess
import datetime
from pathlib import Path
from typing import Dict, List, Tuple

# ---------- Utilities ----------
def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)

def load_cfg() -> dict:
    cfg_path = os.getenv("CONFIG_PATH")
    if not cfg_path:
        script_dir = Path(__file__).parent
        cfg_path = str(script_dir / "gopro_config.json")
    if Path(cfg_path).exists():
        with open(cfg_path, "r") as f:
            return json.load(f)
    return {}

def pretty_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    i = 0
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return f"{size:.1f}{units[i]}"

def is_hidden_or_metadata(p: Path) -> bool:
    return p.name.startswith(".") or p.name.startswith("._")

def list_files_recursive(root: Path) -> List[Path]:
    """List all real files under root, skipping hidden/metadata."""
    return [p for p in root.rglob("*") if p.is_file() and not is_hidden_or_metadata(p)]

def resolve_dailies_roll(cfg_val) -> Path:
    """Resolve GP_DAILIES_ROLL from a string or list of candidate paths."""
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
        # None found — return first candidate (will fail at mount check later)
        return Path(cfg_val[0])
    die(f"GP_DAILIES_ROLL has unexpected type: {type(cfg_val)}")
    return Path()  # unreachable

def index_pool(pool_root: Path) -> Dict[Tuple[str, int], List[Path]]:
    """Build an index of (filename, size) → [paths] for all files under the pool."""
    idx: Dict[Tuple[str, int], List[Path]] = {}
    if not pool_root.exists():
        return idx
    for f in list_files_recursive(pool_root):
        try:
            key = (f.name, f.stat().st_size)
        except FileNotFoundError:
            continue
        idx.setdefault(key, []).append(f)
    return idx

def suggest_orphan_bin(orphan_root: Path) -> str:
    """Generate the next YYYYMMDD_GP_## bin name under _orphan/."""
    ymd = datetime.date.today().strftime("%Y%m%d")
    existing_seqs = []
    if orphan_root.exists():
        pat = re.compile(rf"^{ymd}_GP_(\d{{2}})$")
        for d in orphan_root.iterdir():
            if d.is_dir():
                m = pat.match(d.name)
                if m:
                    existing_seqs.append(int(m.group(1)))
    next_seq = (max(existing_seqs) + 1) if existing_seqs else 1
    return f"{ymd}_GP_{next_seq:02d}"

def copy_files_with_progress(files: List[Path], src_root: Path, dst_root: Path):
    """Copy files preserving relative directory structure, with a progress bar."""
    total_bytes = sum(f.stat().st_size for f in files if f.exists())
    done_bytes = 0
    bar_len = 30

    for src in files:
        rel = src.relative_to(src_root)
        dst = dst_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)

        with src.open("rb") as fi, dst.open("wb") as fo:
            while True:
                buf = fi.read(8 * 1024 * 1024)
                if not buf:
                    break
                fo.write(buf)
                done_bytes += len(buf)
                pct = (done_bytes / total_bytes) * 100 if total_bytes else 100.0
                filled = int(bar_len * pct / 100)
                bar = "█" * filled + "░" * (bar_len - filled)
                sys.stdout.write(
                    f"\r  Copying [{bar}] {pct:5.1f}%  ({pretty_size(done_bytes)}/{pretty_size(total_bytes)})"
                )
                sys.stdout.flush()
        try:
            shutil.copystat(src, dst)
        except Exception:
            pass

    sys.stdout.write("\n")
    sys.stdout.flush()

def offer_eject(dailies_roll: Path):
    """Offer to eject the SD card volume containing dailies_roll."""
    volume_path = dailies_roll
    while volume_path != volume_path.parent:
        if volume_path.parent == Path("/Volumes"):
            break
        volume_path = volume_path.parent

    if volume_path.parent == Path("/Volumes"):
        eject = input(f"\nEject {volume_path.name}? [Y/n]: ").strip().lower()
        if eject not in ("n", "no"):
            try:
                subprocess.run(["diskutil", "eject", str(volume_path)], check=True)
                print(f"⏏️  {volume_path.name} ejected.")
            except subprocess.CalledProcessError:
                print(f"⚠️  Could not eject {volume_path.name}. Eject manually.")

def wipe_directory_contents(root: Path):
    """Delete every item inside root (files and subdirectories)."""
    for p in root.iterdir():
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
        except Exception as e:
            print(f"⚠️  Could not remove {p}: {e}")

# ---------- Main ----------
def main():
    cfg = load_cfg()

    if "GP_JPGSEQ_POOL_ROOT" not in cfg:
        die("Config missing 'GP_JPGSEQ_POOL_ROOT'.")
    if "GP_DAILIES_ROLL" not in cfg:
        die("Config missing 'GP_DAILIES_ROLL'.")

    pool_root = Path(cfg["GP_JPGSEQ_POOL_ROOT"])
    dailies_roll = resolve_dailies_roll(cfg["GP_DAILIES_ROLL"])

    print("=== GoPro SD Card Verify & Wipe ===")
    print(f"SD card (GP_DAILIES_ROLL):  {dailies_roll}")
    print(f"Pool (GP_JPGSEQ_POOL_ROOT): {pool_root}")

    if not pool_root.exists():
        die(f"GP_JPGSEQ_POOL_ROOT not found: {pool_root}")
    if not dailies_roll.exists():
        die(f"SD card not mounted or path not found: {dailies_roll}")
    if not dailies_roll.is_dir():
        die(f"GP_DAILIES_ROLL is not a directory: {dailies_roll}")

    # List everything on the card
    print("\nScanning SD card…")
    card_files = list_files_recursive(dailies_roll)
    if not card_files:
        print("SD card is already empty (no files found).")
        offer_eject(dailies_roll)
        return

    card_total = sum(f.stat().st_size for f in card_files)
    print(f"Card contains {len(card_files)} file(s), {pretty_size(card_total)}")

    # Index the pool
    print("Indexing GP_JPGSEQ_POOL_ROOT…")
    pool_index = index_pool(pool_root)
    pool_instances = sum(len(v) for v in pool_index.values())
    print(f"Indexed {pool_instances} file instance(s) across the pool")

    # Compare
    print("\nVerifying card contents against pool…")
    present: List[Path] = []
    missing: List[Path] = []
    for f in card_files:
        try:
            key = (f.name, f.stat().st_size)
        except FileNotFoundError:
            continue
        if key in pool_index:
            present.append(f)
        else:
            missing.append(f)

    print(f"\n{'─' * 40}")
    print(f"  Verified in pool:  {len(present)}/{len(card_files)}")
    print(f"  Missing from pool: {len(missing)}")
    print(f"{'─' * 40}")

    if missing:
        miss_size = sum(f.stat().st_size for f in missing)
        print(f"\n⚠️  {len(missing)} file(s) ({pretty_size(miss_size)}) NOT found in pool:")
        for f in missing[:20]:
            print(f"    {f.relative_to(dailies_roll)}")
        if len(missing) > 20:
            print(f"    … and {len(missing) - 20} more")

        # Offer to copy missing files into _orphan/
        orphan_root = pool_root / "_orphan"
        orphan_bin = suggest_orphan_bin(orphan_root)
        orphan_dest = orphan_root / orphan_bin

        print(f"\nThese files will be copied to:")
        print(f"  {orphan_dest}")
        proceed = input("Copy missing files to _orphan? [Y/n]: ").strip().lower()
        if proceed in ("n", "no"):
            print("Aborted. SD card was NOT modified.")
            return

        print()
        copy_files_with_progress(missing, dailies_roll, orphan_dest)
        print(f"✅ {len(missing)} file(s) copied to {orphan_dest}")

    # All files now accounted for (either already in pool or just copied)
    print(f"\n✅ All {len(card_files)} file(s) on the card are accounted for.")
    print(f"\n⚠️  This will permanently delete all contents of:")
    print(f"   {dailies_roll}")
    confirm = input("\nType 'delete' to WIPE the SD card (or press Enter to abort): ").strip()

    if confirm.lower() == "delete":
        print("\nWiping SD card contents…")
        wipe_directory_contents(dailies_roll)
        print("🧹 SD card wiped. All contents deleted.")
        offer_eject(dailies_roll)
    else:
        print("Aborted. SD card was NOT modified.")

if __name__ == "__main__":
    main()
