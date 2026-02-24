#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import sys
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

# ------------------------ Helpers ------------------------

def die(msg: str, code: int = 1):
    print(f"[ERROR] {msg}", file=sys.stderr)
    sys.exit(code)

def load_config() -> dict:
    script_dir = Path(__file__).resolve().parent
    config_path = script_dir / "config.json"
    if not config_path.exists():
        die(f"Config file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as f:
        return json.load(f)

def choose_user(user_keymap: dict) -> str:
    print("Select user:")
    for k in sorted(user_keymap.keys()):
        print(f"  [{k}] {user_keymap[k]}")
    choice = input("Enter letter (or q to quit): ").strip().lower()
    if choice == "q":
        sys.exit(0)
    if choice not in user_keymap:
        die(f"Invalid choice '{choice}'.")
    return user_keymap[choice]

def list_top_level_dirs(base: Path, exclude_names: List[str]) -> List[Path]:
    if not base.exists():
        die(f"Base directory does not exist: {base}")
    dirs = []
    for p in base.iterdir():
        if p.is_dir():
            name = p.name
            if name in exclude_names:
                continue
            if name.startswith("."):
                continue
            dirs.append(p)
    return sorted(dirs, key=lambda x: x.name.lower())

def next_today_bucket(sent_dir: Path) -> Tuple[str, Path]:
    """Return (bucket_name, bucket_path) for today's YYYYMMDD_## where ## = max+1 or 01."""
    today_str = datetime.now().strftime("%Y%m%d")
    pattern = re.compile(rf"^{today_str}_(\d{{2}})$")
    max_idx = 0
    if sent_dir.exists():
        for p in sent_dir.iterdir():
            if p.is_dir():
                m = pattern.match(p.name)
                if m:
                    try:
                        idx = int(m.group(1))
                        if idx > max_idx:
                            max_idx = idx
                    except ValueError:
                        pass
    next_idx = max_idx + 1
    bucket_name = f"{today_str}_{next_idx:02d}"
    return bucket_name, sent_dir / bucket_name

def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)

def unique_destination(dst_dir: Path, name: str) -> Path:
    """Return a non-colliding path under dst_dir for folder 'name' (append -1, -2, ... if needed)."""
    candidate = dst_dir / name
    if not candidate.exists():
        return candidate
    i = 1
    while True:
        alt = dst_dir / f"{name}-{i}"
        if not alt.exists():
            return alt
        i += 1

def open_finder(path: Path):
    try:
        subprocess.run(["open", str(path)], check=False)
    except Exception as e:
        print(f"[WARN] Could not open Finder at {path}: {e}")

def reveal_in_finder(target: Path):
    """
    Open Finder and select the given file/folder.
    Works for directories too (Finder will open the parent and highlight it).
    """
    try:
        subprocess.run(["open", "-R", str(target)], check=False)
    except Exception as e:
        print(f"[WARN] Could not reveal in Finder: {e}")
        # Fallback: just open the parent folder
        try:
            subprocess.run(["open", str(target.parent if target.exists() else target)], check=False)
        except Exception as e2:
            print(f"[WARN] Fallback open failed: {e2}")

def open_safari(url: str):
    try:
        subprocess.run(["open", "-a", "Safari", url], check=False)
    except Exception:
        subprocess.run(["open", url], check=False)

def folder_already_sent(sent_dir: Path, folder_name: str) -> bool:
    """
    Check if a folder has already been sent by looking in all _sent buckets.
    Returns True if the folder exists in any bucket.
    """
    if not sent_dir.exists():
        return False
    
    for bucket in sent_dir.iterdir():
        if not bucket.is_dir():
            continue
        # Check if this folder exists in this bucket
        if (bucket / folder_name).exists():
            return True
    return False

def choose_mode() -> str:
    """Interactive mode selection."""
    print("\nSelect transfer mode:")
    print("  [1] hardlink - Create hard links (fast, shares disk space)")
    print("  [2] cp - Copy files (default, creates independent copies)")
    print("  [3] rsync - Use rsync (preserves permissions, efficient)")
    choice = input("Enter choice (1-3, default is 2): ").strip()
    if choice == "":
        return "cp"
    mode_map = {"1": "hardlink", "2": "cp", "3": "rsync"}
    if choice in mode_map:
        return mode_map[choice]
    die(f"Invalid choice '{choice}'. Must be 1, 2, or 3.")

def hardlink_directory(src: Path, dst: Path) -> bool:
    """Recursively hardlink files from src to dst (directories are created, files are hardlinked)."""
    try:
        # Create destination directory
        dst.mkdir(parents=True, exist_ok=True)
        
        # Walk through source directory
        for root, dirs, files in os.walk(src):
            # Create relative path from source
            rel_path = Path(root).relative_to(src)
            dst_subdir = dst / rel_path
            dst_subdir.mkdir(parents=True, exist_ok=True)
            
            # Hardlink all files
            for file in files:
                src_file = Path(root) / file
                dst_file = dst_subdir / file
                try:
                    if dst_file.exists():
                        dst_file.unlink()  # Remove existing file if any
                    os.link(str(src_file), str(dst_file))
                except OSError as e:
                    # If hardlink fails (e.g., cross-filesystem), fall back to copy
                    shutil.copy2(str(src_file), str(dst_file))
        return True
    except Exception as e:
        print(f"[WARN] Hardlink operation failed: {e}")
        return False

def copy_directory(src: Path, dst: Path) -> bool:
    """Copy directory using shutil.copytree."""
    try:
        shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
        return True
    except Exception as e:
        print(f"[WARN] Copy operation failed: {e}")
        return False

def rsync_directory(src: Path, dst: Path) -> bool:
    """Copy directory using rsync."""
    try:
        # Ensure destination parent exists
        dst.parent.mkdir(parents=True, exist_ok=True)
        # Use rsync with archive mode (preserves permissions, timestamps, etc.)
        # Copy src/ contents into dst (dst will be created if it doesn't exist)
        result = subprocess.run(
            ["rsync", "-a", f"{src}/", f"{dst}/"],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode != 0:
            print(f"[WARN] rsync failed: {result.stderr}")
            return False
        return True
    except FileNotFoundError:
        print("[WARN] rsync not found. Falling back to copy.")
        return copy_directory(src, dst)
    except Exception as e:
        print(f"[WARN] rsync operation failed: {e}")
        return False

# ------------------------ Main flow ------------------------

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Package proxy files for sending")
    parser.add_argument(
        "--mode",
        choices=["hardlink", "cp", "rsync"],
        default=None,
        help="Transfer mode: hardlink, cp (default), or rsync. If not provided, interactive mode will prompt."
    )
    args = parser.parse_args()
    
    # Determine mode: use --mode if provided, otherwise interactive selection
    if args.mode:
        mode = args.mode
    else:
        mode = choose_mode()
    
    cfg = load_config()

    PROXY_POOL_ROOT = Path(cfg["PROXY_POOL_ROOT"])
    user_keymap = cfg["user_keymap"]
    file_request_urls = cfg.get("file_request_urls", {})  # NAME -> URL

    # 1) Choose user
    name = choose_user(user_keymap)

    # 2) Resolve paths
    base_dir = PROXY_POOL_ROOT / name
    sent_dir = base_dir / "_sent"
    ensure_dir(sent_dir)  # create if missing

    # 3) Find candidate directories to send (exclude _reports, _sent, hidden, and already-sent)
    exclude_names = ["_reports", "_sent"]
    all_candidates = list_top_level_dirs(base_dir, exclude_names=exclude_names)

    # Filter out folders that have already been sent
    candidates = []
    already_sent = []
    for candidate in all_candidates:
        if folder_already_sent(sent_dir, candidate.name):
            already_sent.append(candidate.name)
        else:
            candidates.append(candidate)

    if already_sent:
        print(f"\n[INFO] Skipping already-sent folders: {', '.join(already_sent)}")

    if not candidates:
        if already_sent:
            print("All folders have already been sent. Nothing new to package.")
        else:
            print("No folders to send. (Nothing found besides _reports/_sent.)")
        open_finder(sent_dir)
        url = file_request_urls.get(name)
        if url:
            open_safari(url)
        else:
            print(f"[INFO] No file_request_urls entry for {name}. Add it to config.json to auto-open Dropbox.")
        sys.exit(0)

    # 4) Compute today's bucket name (but don't create yet)
    bucket_name, bucket_path = next_today_bucket(sent_dir)

    # ---- NEW YES/NO CONFIRMATION ----
    print("\nFound the following folders:")
    for p in candidates:
        print(f"  - {p.name}")
    prompt = f"\nCreate package {bucket_name} ? Y/n: "
    ans = input(prompt).strip().lower()
    if ans == "n":
        print("Cancelled. No changes made.")
        sys.exit(0)
    # Enter (empty) or 'y' continues
    if ans not in ("", "y"):
        print("Cancelled (unrecognized response). No changes made.")
        sys.exit(0)

    # 5) Create bucket and transfer candidates into it using selected mode
    ensure_dir(bucket_path)
    transferred = []
    
    # Select the appropriate transfer function
    transfer_funcs = {
        "hardlink": hardlink_directory,
        "cp": copy_directory,
        "rsync": rsync_directory
    }
    transfer_func = transfer_funcs[mode]
    
    action_verb = {
        "hardlink": "Linked",
        "cp": "Copied",
        "rsync": "Synced"
    }[mode]
    
    for src in candidates:
        dst = unique_destination(bucket_path, src.name)
        try:
            success = transfer_func(src, dst)
            if success:
                transferred.append((src.name, dst))
                print(f"{action_verb}: {src.name} -> {dst.relative_to(sent_dir)}")
            else:
                print(f"[WARN] Failed to {mode} {src} -> {dst}")
        except Exception as e:
            print(f"[WARN] Failed to {mode} {src} -> {dst}: {e}")

    if not transferred:
        print(f"[WARN] No folders were transferred (unexpected).")
    else:
        print(f"\n✅ {action_verb} {len(transferred)} folder(s) into: {bucket_path}")

    # 6) Open Finder at _sent and Safari at this user's File Request URL
    #open_finder(bucket_path)
    url = file_request_urls.get(name)
    if url:
        open_safari(url)
    else:
        print(f"[INFO] No file_request_urls entry for {name}. Add it to config.json to auto-open Dropbox.")
    open_finder(bucket_path)
    
if __name__ == "__main__":
    main()