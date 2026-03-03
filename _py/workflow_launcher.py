#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Launcher: choose user, optionally run ingest, then run Resolve import (newest bin or manual).
Suffix-aware newest bin detection: matches YYYYMMDD_## and YYYYMMDD_##_<suffix>.
"""

import os
import re
import sys
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional

from config_loader import load_config

# suffix-aware: 20250906_04 or 20250906_04_ya
BIN_PATTERN = re.compile(r"^(?P<ymd>\d{8})_(?P<seq>\d{2})(?:_.*)?$")

def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr); sys.exit(code)

def pick_user(keymap: dict) -> str:
    print("Select user:")
    for letter in sorted(keymap.keys()):
        print(f"  [{letter}] {keymap[letter]}")
    while True:
        choice = input("Enter letter (or q to quit): ").strip().lower()
        if choice == "q":
            die("Aborted.", code=0)
        if choice in keymap:
            return keymap[choice]  # returns NAME (e.g., "ANDY")
        print("Invalid choice. Try again.")

def newest_bin(media_pool: Path) -> Optional[Path]:
    if not media_pool.exists():
        return None
    candidates: List[Tuple[str, int, Path]] = []
    for p in media_pool.iterdir():
        if p.is_dir():
            m = BIN_PATTERN.match(p.name)
            if m:
                candidates.append((m.group("ymd"), int(m.group("seq")), p))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1]))  # ascending by date then seq
    return candidates[-1][2]

def confirm(prompt: str, default_yes: bool = True) -> bool:
    resp = input(prompt + (" [Y/n]: " if default_yes else " [y/N]: ")).strip().lower()
    return default_yes if resp == "" else resp in ("y", "yes")

def normalize_dragged_path(p: str) -> str:
    """Handle paths dragged into terminal that may have escaped spaces."""
    p = p.strip()
    if Path(p).exists():
        return p
    if p.startswith("/") and (" " in p or "\\ " in p):
        unescaped = p.replace("\\ ", " ")
        if Path(unescaped).exists():
            return unescaped
    return p

def collect_multiple_paths() -> List[Path]:
    """Prompt the user to drag in folders one at a time. Blank line ends input."""
    folders: List[Path] = []
    print("Enter folders one at a time (blank line when done):")
    while True:
        raw = input(f"  Folder {len(folders) + 1}: ").strip()
        if not raw:
            if not folders:
                print("  No folders entered. Try again.")
                continue
            break
        raw = normalize_dragged_path(raw)
        p = Path(raw)
        if not p.exists():
            print(f"  Path not found: {raw}  — skipping.")
            continue
        folders.append(p)
        print(f"  Added: {p}")
    return folders

def main():
    # 1) Load config (allow custom path as argv[1], or use default in same directory)
    if len(sys.argv) > 1:
        cfg_path = Path(sys.argv[1])
    else:
        # Use config.json in the same directory as this script
        script_dir = Path(__file__).parent
        cfg_path = script_dir / "config.json"
    cfg = load_config(cfg_path)

    if "python_exec" not in cfg:
        die("Config missing 'python_exec' key.")
    if "DEFAULT_DAILIES_ROLL" not in cfg:
        die("Config missing 'DEFAULT_DAILIES_ROLL' key.")

    python_exec = cfg["python_exec"]
    dailies_roll = Path(cfg["DEFAULT_DAILIES_ROLL"])

    keymap = cfg.get("user_keymap", {})
    scripts = cfg.get("scripts")
    if not keymap:
        die("Missing 'user_keymap' in config.json")
    if not scripts or "ingest" not in scripts:
        die("Missing 'scripts.ingest' entry in config.json")
    if "import" not in scripts:
        die("Missing 'scripts.import' entry in config.json")

    ingest_script = Path(scripts["ingest"])
    import_script = Path(scripts["import"])
    if not ingest_script.exists():
        die(f"Ingest script not found at {ingest_script}")
    if not import_script.exists():
        die(f"Import script not found at {import_script}")

    # 2) Pick NAME (e.g., "ANDY")
    NAME = pick_user(keymap)

    # 3) Derive paths from config
    media_pool_root = Path(cfg["MEDIA_POOL_ROOT"])
    media_pool = media_pool_root / NAME

    print(f"\nHello {NAME} 👋")
    print(f"MEDIA_POOL_ROOT: {media_pool_root}")
    print(f"MEDIA_POOL:      {media_pool}")
    print(f"DAILIES_ROLL:    {dailies_roll}")

    # Ensure MEDIA_POOL_ROOT exists
    if not media_pool_root.exists():
        print(f"Creating MEDIA_POOL_ROOT: {media_pool_root}")
        media_pool_root.mkdir(parents=True, exist_ok=True)

    # 4) Shared environment for child scripts
    env = os.environ.copy()
    env["CONFIG_PATH"] = str(cfg_path)
    env["NAME"] = NAME
    env["MEDIA_POOL_ROOT"] = str(media_pool_root)
    env["DAILIES_ROLL"] = str(dailies_roll)
    env["RESOLVE_PROJECT"] = NAME  # import script can LoadProject(NAME)

    # 5) Ask whether to run ingest first
    run_ingest_first = confirm("\nRun ingest (copy mp4s from SDcard to LACIE media_pool)?", default_yes=True)

    if run_ingest_first:
        ingest_cmd = [python_exec, str(ingest_script)]
        print(f"\n— Running ingest: {' '.join(ingest_cmd)}")
        try:
            subprocess.run(ingest_cmd, check=True, env=env)
        except subprocess.CalledProcessError as e:
            die(f"Ingest failed with exit code {e.returncode}")
        print("\n✅ Ingest finished.")

    # 6) Determine folder(s) to import (suffix-aware)
    def pick_import_mode() -> List[Path]:
        """Ask whether to import one or multiple folders; return list of validated paths."""
        print("\nImport mode:")
        print("  [1] Single folder")
        print("  [2] Multiple folders (one timeline per folder)")
        while True:
            choice = input("Choice [1]: ").strip()
            if choice in ("", "1"):
                raw = input("Drag in the folder path you want to import: ").strip()
                if not raw:
                    die("No folder provided.")
                raw = normalize_dragged_path(raw)
                p = Path(raw)
                if not p.exists():
                    die(f"Folder not found: {p}")
                return [p]
            if choice == "2":
                return collect_multiple_paths()
            print("  Invalid choice. Enter 1 or 2.")

    latest = newest_bin(media_pool)
    if latest:
        print(f"\nLatest bin detected: {latest.name}")
        use_latest = confirm("Use this folder for Resolve import?", default_yes=True)
        if use_latest:
            folders_to_import = [latest]
        else:
            folders_to_import = pick_import_mode()
    else:
        print(f"\nNo YYYYMMDD_##[_suffix] folders found in {media_pool}.")
        folders_to_import = pick_import_mode()

    # 7) Run import for each folder
    for folder in folders_to_import:
        import_cmd = [python_exec, str(import_script), str(folder)]
        print(f"\n— Running import: {' '.join(import_cmd)}")
        try:
            subprocess.run(import_cmd, check=True, env=env)
        except subprocess.CalledProcessError as e:
            die(f"Import failed for {folder} with exit code {e.returncode}")

    print("\n✅ Import finished.")
    print("\n🎬 Pipeline complete.")

if __name__ == "__main__":
    main()
