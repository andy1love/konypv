#!/usr/bin/env python3
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

# ------------------------ Main flow ------------------------

def main():
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

    # 3) Find candidate directories to send (exclude _reports, _sent, hidden)
    exclude_names = ["_reports", "_sent"]
    candidates = list_top_level_dirs(base_dir, exclude_names=exclude_names)

    if not candidates:
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

    # 5) Create bucket and link candidates into it
    ensure_dir(bucket_path)
    linked = []
    for src in candidates:
        dst = unique_destination(bucket_path, src.name)
        try:
            # Create hard link instead of moving
            os.link(str(src), str(dst))
            linked.append((src.name, dst))
            print(f"Linked: {src.name} -> {dst.relative_to(sent_dir)}")
        except Exception as e:
            print(f"[WARN] Failed to create hard link {src} -> {dst}: {e}")

    if not linked:
        print("[WARN] No folders were linked (unexpected).")
    else:
        print(f"\n✅ Linked {len(linked)} folder(s) into: {bucket_path}")

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