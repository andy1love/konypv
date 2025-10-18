#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
proxy_maker.py

Prompts for user NAME via config.json's user_keymap, then:
- Scans MEDIA_POOL_ROOT/NAME recursively for .mp4 files (case-insensitive)
- Ignores hidden/metadata files (names starting with "." or "._")
- Mirrors the folder structure into PROXY_POOL_ROOT/NAME
- Creates 1920x1080 H.264 proxies with the SAME filename as the source
- Skips outputs that already exist AND are newer than the source
- Writes a CSV report of proxies generated in PROXY_POOL_ROOT/NAME/_reports/

Config (JSON) expected keys:
  MEDIA_POOL_ROOT
  PROXY_POOL_ROOT
  user_keymap { letter: NAME }
Optional env:
  CONFIG_PATH -> path to config.json (default: /Volumes/LaCie/_scripts/config.json)
"""

import os
import sys
import csv
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime

VIDEO_EXTS = {".mp4"}  # extend if needed: {".mp4", ".mov", ...}

# ---------------- Utilities ----------------
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

def pretty_size(num_bytes: int) -> str:
    units = ["B","KB","MB","GB","TB"]
    size = float(num_bytes)
    i = 0
    while size >= 1024 and i < len(units)-1:
        size /= 1024
        i += 1
    return f"{size:.1f}{units[i]}"

def newer_than(src: Path, dst: Path) -> bool:
    """True if src is newer than dst, or dst missing."""
    try:
        return src.stat().st_mtime > dst.stat().st_mtime
    except FileNotFoundError:
        return True

def find_existing_proxy(src: Path, dst_root: Path, src_root: Path) -> Path:
    """
    Find existing proxy file in either original location or _sent directories.
    Returns the path to the existing proxy, or None if not found.
    """
    rel = src.relative_to(src_root)
    original_proxy = dst_root / rel.parent / src.name
    
    # Check original location first
    if original_proxy.exists():
        return original_proxy
    
    # Check _sent directory recursively
    sent_dir = dst_root / "_sent"
    if sent_dir.exists():
        for sent_bucket in sent_dir.iterdir():
            if sent_bucket.is_dir():
                sent_proxy = sent_bucket / rel.parent / src.name
                if sent_proxy.exists():
                    return sent_proxy
    
    return None

def is_hidden_or_metadata(p: Path) -> bool:
    """
    Treat as hidden/metadata if:
      - the filename starts with '.' (e.g., .DS_Store)
      - the filename starts with '._' (AppleDouble sidecar like ._C0454.MP4)
      - ANY parent directory starts with '.'
    """
    if p.name.startswith(".") or p.name.startswith("._"):
        return True
    return any(part.startswith(".") for part in p.parts)

def discover_sources(src_root: Path) -> List[Path]:
    files: List[Path] = []
    for p in src_root.rglob("*"):
        if not p.is_file():
            continue
        if is_hidden_or_metadata(p):
            continue
        if p.suffix.lower() in VIDEO_EXTS:
            files.append(p)
    return files

def run_ffmpeg(input_path: Path, output_path: Path):
    """
    Downscale to 1080p, encode H.264 (AVC) with Apple/Quick Look–friendly settings.
    Keeps aspect ratio and letterboxes/pillarboxes to exactly 1920x1080.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),

        # Scale to fit within 1920x1080 (preserve AR), pad to exact 1920x1080, force square pixels
        "-vf", "scale=1920:1080:flags=lanczos:force_original_aspect_ratio=decrease,"
               "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1",

        # Very compatible H.264
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-profile:v", "high",
        "-level:v", "4.1",

        # Size/speed tradeoff
        "-preset", "fast",
        "-crf", "23",

        # Audio: AAC LC @48k
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "48000",

        # Put moov atom at start for Quick Look / progressive playback
        "-movflags", "+faststart",

        str(output_path)
    ]
    print(f"\n⏳ ffmpeg: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    print(f"✅ Proxy created: {output_path}")

# ---------------- Main ----------------
def main():
    cfg = load_cfg()

    # Fail fast if required config keys are missing
    if "MEDIA_POOL_ROOT" not in cfg:
        die("Config missing 'MEDIA_POOL_ROOT' key.")
    if "PROXY_POOL_ROOT" not in cfg:
        die("Config missing 'PROXY_POOL_ROOT' key.")

    media_pool_root = Path(cfg["MEDIA_POOL_ROOT"])
    proxy_pool_root = Path(cfg["PROXY_POOL_ROOT"])
    keymap = cfg.get("user_keymap", {})

    if not keymap:
        die("Config missing 'user_keymap'.")
    if not media_pool_root.exists():
        die(f"MEDIA_POOL_ROOT does not exist: {media_pool_root}")
    if not proxy_pool_root.exists():
        print(f"Creating PROXY_POOL_ROOT: {proxy_pool_root}")
        proxy_pool_root.mkdir(parents=True, exist_ok=True)

    NAME = pick_user(keymap)

    src_root = media_pool_root / NAME
    dst_root = proxy_pool_root / NAME
    if not src_root.exists():
        die(f"User media pool not found: {src_root}")
    dst_root.mkdir(parents=True, exist_ok=True)

    print(f"\n=== Proxy Generation ===")
    print(f"User:           {NAME}")
    print(f"Source (media): {src_root}")
    print(f"Dest (proxies): {dst_root}")
    print("Scanning for video files…")

    src_files: List[Path] = discover_sources(src_root)
    if not src_files:
        print("No matching files found under the user's media pool. Nothing to do.")
        return

    # Plan work: mirror structure, SAME filename (no _proxy suffix)
    tasks: List[Tuple[Path, Path]] = []
    total_size = 0
    for src in src_files:
        rel = src.relative_to(src_root)
        out = dst_root / rel.parent / src.name
        
        # Check if proxy exists in original location or _sent directories
        existing_proxy = find_existing_proxy(src, dst_root, src_root)
        if existing_proxy and not newer_than(src, existing_proxy):
            continue
        
        tasks.append((src, out))
        try:
            total_size += src.stat().st_size
        except FileNotFoundError:
            pass

    print(f"Found {len(src_files)} source file(s).")
    print(f"Planned {len(tasks)} encode(s). Estimated input size: {pretty_size(total_size)}")
    if len(tasks) == 0:
        print("All proxies appear up-to-date. ✅")
        return

    proceed = input("Proceed with encoding? [Y/n]: ").strip().lower()
    if proceed not in ("", "y", "yes"):
        die("Aborted by user.", code=0)

    generated: List[Tuple[str, str]] = []  # (source_path, proxy_path)
    errors = 0
    for i, (src, out) in enumerate(tasks, 1):
        print(f"\n[{i}/{len(tasks)}] {src} -> {out}")
        try:
            run_ffmpeg(src, out)
            generated.append((str(src), str(out)))
        except subprocess.CalledProcessError as e:
            errors += 1
            print(f"❌ ffmpeg failed for {src} (exit {e.returncode})")

    # --- CSV report of proxies generated this run ---
    reports_dir = dst_root / "_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = reports_dir / f"proxies_{ts}.csv"

    if generated:
        with csv_path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["source_path", "proxy_path"])
            w.writerows(generated)
        print(f"\n📝 Report written: {csv_path}")
    else:
        print("\n(No new proxies were generated; no CSV report written.)")

    if errors:
        print(f"\nDone with {errors} error(s).")
    else:
        print("\n🎬 All proxies generated successfully.")

if __name__ == "__main__":
    main()
