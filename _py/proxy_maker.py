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
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from config_loader import load_config

VIDEO_EXTS = {".mp4"}  # extend if needed: {".mp4", ".mov", ...}

# ---------------- Utilities ----------------
def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)

def pick_user(keymap: dict) -> str:
    print("Select user:")
    print("  [0] All users")
    for letter in sorted(keymap.keys()):
        print(f"  [{letter}] {keymap[letter]}")
    while True:
        choice = input("Enter letter (or 0 for all, q to quit): ").strip().lower()
        if choice == "q":
            die("Aborted.", code=0)
        if choice == "0":
            return "ALL"
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

def find_existing_proxy(src: Path, dst_root: Path, src_root: Path) -> Optional[Path]:
    """
    Find existing proxy file in either original location or _sent directories.
    Since proxy_packager.py creates hard links at the folder level, we need to
    check both the original location and all _sent buckets.
    Returns the path to the existing proxy, or None if not found.
    """
    rel = src.relative_to(src_root)
    original_proxy = dst_root / rel.parent / src.name
    
    # Check original location first (fast path)
    if original_proxy.exists():
        return original_proxy
    
    # Check _sent directory recursively
    # Since proxy_packager.py hard-links entire folders, the relative path
    # structure should be preserved within each bucket
    sent_dir = dst_root / "_sent"
    if sent_dir.exists():
        for sent_bucket in sent_dir.iterdir():
            if not sent_bucket.is_dir():
                continue
            # Construct the path within this bucket
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

# ---------------- Progress display ----------------
def get_duration_seconds(input_path: Path) -> Optional[float]:
    """Get video duration in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(input_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        return None

def format_time(seconds: float) -> str:
    """Format seconds as H:MM:SS or M:SS."""
    s = max(0, int(seconds))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h > 0 else f"{m:d}:{s:02d}"

def print_progress(file_current: float, file_total: float,
                   batch_current: int, batch_total: int,
                   suffix: str = '', length: int = 30):
    """
    Two-line progress display: current file and overall batch.
    Uses ANSI escapes to overwrite in place.
    """
    f_frac = min(file_current / file_total, 1.0) if file_total > 0 else 0.0
    f_filled = int(length * f_frac)
    f_bar = '█' * f_filled + '░' * (length - f_filled)

    b_frac = ((batch_current - 1 + f_frac) / batch_total) if batch_total > 0 else 0.0
    b_frac = min(b_frac, 1.0)
    b_filled = int(length * b_frac)
    b_bar = '█' * b_filled + '░' * (length - b_filled)

    file_line  = f"  File  [{f_bar}] {f_frac*100:5.1f}% {suffix}"
    batch_line = f"  Batch [{b_bar}] {b_frac*100:5.1f}% | {batch_current}/{batch_total} files"

    sys.stdout.write(f"\r\x1b[K{file_line}\n\x1b[K{batch_line}\x1b[A\r")
    sys.stdout.flush()

def finish_progress():
    """Move cursor past the two progress lines."""
    sys.stdout.write("\n\n")
    sys.stdout.flush()

# ---------------- Encoding ----------------
def run_ffmpeg(input_path: Path, output_path: Path, task_idx: int = 0, total_tasks: int = 0):
    """
    Downscale to 1080p, encode H.264 (AVC) with Apple/Quick Look–friendly settings.
    Keeps aspect ratio and letterboxes/pillarboxes to exactly 1920x1080.
    Shows a two-line progress bar for the current file and overall batch.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    duration = get_duration_seconds(input_path)

    cmd = [
        "ffmpeg", "-y",
        "-loglevel", "warning",
        "-nostats",
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

        # Structured progress output on stdout
        "-progress", "pipe:1",

        str(output_path)
    ]

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8',
        errors='replace'
    )

    current_time_us = 0
    total_time_us = int(duration * 1_000_000) if duration else 0
    speed_str = ""

    try:
        for line in process.stdout:
            line = line.strip()
            if line.startswith("out_time_us="):
                try:
                    val = line.split("=", 1)[1].strip()
                    if val != "N/A":
                        current_time_us = max(0, int(val))
                except (ValueError, IndexError):
                    pass
            elif line.startswith("speed="):
                speed_str = line.split("=", 1)[1].strip()
            elif line in ("progress=continue", "progress=end"):
                if total_time_us > 0:
                    elapsed = format_time(current_time_us / 1_000_000)
                    dur_str = format_time(duration)
                    sfx = f"| {elapsed}/{dur_str}"
                    if speed_str and speed_str != "N/A":
                        sfx += f" | {speed_str}"
                    print_progress(
                        current_time_us, total_time_us,
                        task_idx, total_tasks,
                        suffix=sfx
                    )
    except Exception:
        pass

    process.wait()
    finish_progress()

    if process.returncode != 0:
        stderr_output = process.stderr.read()
        print(f"❌ ffmpeg error output:\n{stderr_output}", file=sys.stderr)
        raise subprocess.CalledProcessError(process.returncode, cmd)

    print(f"✅ Proxy created: {output_path}")

# ---------------- All-users snapshot ----------------

def snapshot_all_users(media_pool_root: Path, proxy_pool_root: Path, keymap: dict):
    """
    Scan both pools for all users, write 3 timestamped CSVs to
    <script_dir>/output/pool_snapshot/, and print a summary.
    """
    out_dir = Path(__file__).parent / "output" / "pool_snapshot"
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    media_csv_path   = out_dir / f"media_pool_{ts}.csv"
    proxy_csv_path   = out_dir / f"proxy_pool_{ts}.csv"
    missing_csv_path = out_dir / f"missing_proxies_{ts}.csv"

    names = list(dict.fromkeys(keymap.values()))  # dedupe, preserve order

    all_media_rows:   List[Tuple[str, str, str, int]] = []  # (user, rel, full, size)
    all_proxy_rows:   List[Tuple[str, str, str, int]] = []
    all_missing_rows: List[Tuple[str, str, str, str]] = []  # (user, rel, media_full, expected_proxy)

    for name in names:
        src_root = media_pool_root / name
        dst_root = proxy_pool_root / name

        # --- media pool ---
        if src_root.exists():
            for p in discover_sources(src_root):
                rel = str(p.relative_to(src_root))
                try:
                    size = p.stat().st_size
                except FileNotFoundError:
                    size = 0
                all_media_rows.append((name, rel, str(p), size))

                # check if proxy is missing or stale
                existing_proxy = find_existing_proxy(p, dst_root, src_root)
                if existing_proxy is None or newer_than(p, existing_proxy):
                    expected = str(dst_root / p.relative_to(src_root).parent / p.name)
                    all_missing_rows.append((name, rel, str(p), expected))

        # --- proxy pool ---
        if dst_root.exists():
            for p in dst_root.rglob("*"):
                if not p.is_file():
                    continue
                if is_hidden_or_metadata(p):
                    continue
                if p.suffix.lower() not in VIDEO_EXTS:
                    continue
                rel = str(p.relative_to(dst_root))
                try:
                    size = p.stat().st_size
                except FileNotFoundError:
                    size = 0
                all_proxy_rows.append((name, rel, str(p), size))

    # write CSVs
    with media_csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["user", "relative_path", "full_path", "size_bytes"])
        w.writerows(all_media_rows)

    with proxy_csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["user", "relative_path", "full_path", "size_bytes"])
        w.writerows(all_proxy_rows)

    with missing_csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["user", "relative_path", "media_full_path", "expected_proxy_path"])
        w.writerows(all_missing_rows)

    print(f"\n=== Pool Snapshot ===")
    print(f"Media pool files:  {len(all_media_rows)}")
    print(f"Proxy pool files:  {len(all_proxy_rows)}")
    print(f"Missing proxies:   {len(all_missing_rows)}")
    print(f"\nSnapshot CSVs written to: {out_dir}")
    print(f"  {media_csv_path.name}")
    print(f"  {proxy_csv_path.name}")
    print(f"  {missing_csv_path.name}")


# ---------------- Per-user encode ----------------

def encode_user(NAME: str, media_pool_root: Path, proxy_pool_root: Path, ask_confirm: bool = True):
    """Scan, plan, and encode proxies for a single user. Returns (generated_count, error_count)."""
    src_root = media_pool_root / NAME
    dst_root = proxy_pool_root / NAME

    if not src_root.exists():
        print(f"[SKIP] Media pool not found for {NAME}: {src_root}")
        return 0, 0

    dst_root.mkdir(parents=True, exist_ok=True)

    print(f"\n=== Proxy Generation ===")
    print(f"User:           {NAME}")
    print(f"Source (media): {src_root}")
    print(f"Dest (proxies): {dst_root}")
    print("Scanning for video files…")

    src_files: List[Path] = discover_sources(src_root)
    if not src_files:
        print("No matching files found under the user's media pool. Nothing to do.")
        return 0, 0

    tasks: List[Tuple[Path, Path]] = []
    total_size = 0
    for src in src_files:
        rel = src.relative_to(src_root)
        out = dst_root / rel.parent / src.name

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
        return 0, 0

    if ask_confirm:
        proceed = input("Proceed with encoding? [Y/n]: ").strip().lower()
        if proceed not in ("", "y", "yes"):
            die("Aborted by user.", code=0)

    generated: List[Tuple[str, str]] = []
    errors = 0
    for i, (src, out) in enumerate(tasks, 1):
        print(f"\n⏳ [{i}/{len(tasks)}] Encoding: {src.name}")
        try:
            run_ffmpeg(src, out, task_idx=i, total_tasks=len(tasks))
            generated.append((str(src), str(out)))
        except subprocess.CalledProcessError as e:
            errors += 1
            print(f"❌ ffmpeg failed for {src} (exit {e.returncode})")

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

    return len(generated), errors


# ---------------- Main ----------------
def main():
    cfg = load_config()

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

    if NAME == "ALL":
        snapshot_all_users(media_pool_root, proxy_pool_root, keymap)
        proceed = input("\nProceed with encoding all missing proxies? [y/N]: ").strip().lower()
        if proceed not in ("y", "yes"):
            die("Aborted.", code=0)
        names_to_process = list(dict.fromkeys(keymap.values()))
        total_generated = 0
        total_errors = 0
        for name in names_to_process:
            gen, err = encode_user(name, media_pool_root, proxy_pool_root, ask_confirm=False)
            total_generated += gen
            total_errors += err
        print(f"\n{'='*50}")
        print(f"All users complete. Generated: {total_generated}  Errors: {total_errors}")
    else:
        encode_user(NAME, media_pool_root, proxy_pool_root, ask_confirm=True)

if __name__ == "__main__":
    main()
