#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GP_WR_maker.py — Standalone ProRes 422 Working-Resolution renderer

Standalone script (not launched by workflow_launcher.py).
1. Scans every bin under GP_JPGSEQ_POOL_ROOT for take-report CSVs
   (_reports/gp_wr_take_report_*.csv produced by take_maker.py)
2. Builds a master catalogue of all known takes
3. Prompts the user for which takes to render:
   - path to a CSV / text file that lists take names, OR
   - comma-separated take names typed directly, OR
   - numbered selection from the displayed list, OR
   - "all"
4. Renders full-resolution ProRes 422 QuickTime (.mov) for each selected take
5. Output: GP_WR_POOL/{bin_name}/{take_name}.mov

Config keys (gopro_config.json):
  GP_JPGSEQ_POOL_ROOT  – root of JPG-sequence bins
  GP_WR_POOL           – output directory for ProRes 422 renders
  wr.fps               – frame rate (default: 24)
"""

import os
import sys
import csv
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# JPG file extensions
JPG_EXTS = {".jpg", ".jpeg", ".JPG", ".JPEG"}

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

# ---------- Progress display ----------
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
    Two-line progress display: current take and overall batch.
    Uses ANSI escapes to overwrite in place.
    """
    f_frac = min(file_current / file_total, 1.0) if file_total > 0 else 0.0
    f_filled = int(length * f_frac)
    f_bar = '█' * f_filled + '░' * (length - f_filled)

    b_frac = ((batch_current - 1 + f_frac) / batch_total) if batch_total > 0 else 0.0
    b_frac = min(b_frac, 1.0)
    b_filled = int(length * b_frac)
    b_bar = '█' * b_filled + '░' * (length - b_filled)

    file_line  = f"  Take  [{f_bar}] {f_frac*100:5.1f}% {suffix}"
    batch_line = f"  Batch [{b_bar}] {b_frac*100:5.1f}% | {batch_current}/{batch_total} takes"

    sys.stdout.write(f"\r\x1b[K{file_line}\n\x1b[K{batch_line}\x1b[A\r")
    sys.stdout.flush()

def finish_progress():
    """Move cursor past the two progress lines."""
    sys.stdout.write("\n\n")
    sys.stdout.flush()

# ---------- Take discovery ----------
def discover_all_takes(pool_root: Path) -> Dict[str, dict]:
    """
    Scan every bin folder under pool_root for take-report CSVs.
    Returns { take_name: { bin_name, bin_folder, first_path, last_path, frame_count } }
    """
    takes: Dict[str, dict] = {}
    for bin_dir in sorted(pool_root.iterdir()):
        if not bin_dir.is_dir() or bin_dir.name.startswith((".", "_")):
            continue
        reports_dir = bin_dir / "_reports"
        if not reports_dir.exists():
            continue
        for csv_file in reports_dir.glob("gp_wr_take_report_*.csv"):
            try:
                with csv_file.open("r", newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        take_name = row["take_name"]
                        takes[take_name] = {
                            "bin_name": bin_dir.name,
                            "bin_folder": bin_dir,
                            "first_path": Path(row["first_frame_path"]),
                            "last_path": Path(row["last_frame_path"]),
                            "frame_count": int(row["frames_total"]),
                        }
            except Exception as e:
                print(f"  Warning: could not read {csv_file.name}: {e}", file=sys.stderr)
    return takes

def is_hidden_or_metadata(p: Path) -> bool:
    return p.name.startswith(".") or p.name.startswith("._")

def get_frame_files_in_range(first_path: Path, last_path: Path, bin_folder: Path) -> List[Path]:
    """Get all JPG files between first_path and last_path (inclusive), sorted by name."""
    all_files = []
    for p in bin_folder.rglob("*"):
        if p.is_file() and not is_hidden_or_metadata(p) and p.suffix in JPG_EXTS:
            all_files.append(p)
    all_files.sort(key=lambda p: p.name)

    first_idx = None
    last_idx = None
    for i, p in enumerate(all_files):
        if p == first_path:
            first_idx = i
        if p == last_path:
            last_idx = i

    if first_idx is not None and last_idx is not None:
        return all_files[first_idx:last_idx + 1]
    return []

# ---------- User input ----------
def parse_take_file(file_path: Path, available: Dict[str, dict]) -> List[str]:
    """
    Parse a CSV or plain-text file for take names.
    Supports:
      - CSV with a 'take_name' column header
      - Plain text with one take name per line
      - Comma-separated names on a single line
    Lines starting with '#' are ignored.
    """
    selected: List[str] = []
    try:
        with file_path.open("r", newline="") as f:
            sample = f.read(4096)
            f.seek(0)

            if "take_name" in sample:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get("take_name", "").strip()
                    if name in available:
                        selected.append(name)
            else:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    for part in line.split(","):
                        part = part.strip()
                        if part in available:
                            selected.append(part)
    except Exception as e:
        print(f"  Warning: could not parse {file_path}: {e}", file=sys.stderr)
    return selected

def prompt_for_takes(available: Dict[str, dict]) -> List[str]:
    """
    Show the catalogue and let the user choose which takes to render.
    Accepts a CSV/text file path, comma-separated names, numbered selection, or 'all'.
    """
    # Build a stable numbered list
    numbered = list(sorted(available.keys()))

    print("\nAvailable takes:")
    current_bin = ""
    for i, take_name in enumerate(numbered, 1):
        info = available[take_name]
        if info["bin_name"] != current_bin:
            current_bin = info["bin_name"]
            print(f"\n  {current_bin}")
        print(f"    [{i:3d}] {take_name}  ({info['frame_count']} frames)")

    print(f"\nOptions:")
    print(f"  • Path to a CSV or text file listing take names")
    print(f"  • Comma-separated take names  (e.g. 20260207_GP_01_tk001,20260207_GP_01_tk002)")
    print(f"  • Comma-separated numbers     (e.g. 1,3,5)")
    print(f"  • 'all'  to render everything")
    print(f"  • 'q'    to quit")

    while True:
        user_input = input("\nSelect takes: ").strip()
        # Strip surrounding quotes (common when dragging files into terminal)
        if (user_input.startswith("'") and user_input.endswith("'")) or \
           (user_input.startswith('"') and user_input.endswith('"')):
            user_input = user_input[1:-1]

        if not user_input or user_input.lower() == "q":
            die("Aborted by user.", code=0)

        if user_input.lower() == "all":
            return numbered

        # Is it a file path?
        candidate = Path(user_input)
        if candidate.exists() and candidate.is_file():
            selected = parse_take_file(candidate, available)
            if selected:
                return selected
            print("No matching take names found in that file. Try again.")
            continue

        # Comma-separated tokens
        parts = [p.strip() for p in user_input.split(",")]

        # All numbers?  → numbered selection
        if all(p.isdigit() for p in parts if p):
            indices = [int(p) - 1 for p in parts if p]
            selected = [numbered[i] for i in indices if 0 <= i < len(numbered)]
            if selected:
                return selected
            print("Invalid number(s). Try again.")
            continue

        # Try as literal take names
        selected = [p for p in parts if p in available]
        if selected:
            return selected

        print("No matching takes found. Try again.")

# ---------- ProRes 422 rendering ----------
def generate_prores422(take_name: str, frame_files: List[Path], output_path: Path, fps: int,
                       task_idx: int = 0, total_tasks: int = 0):
    """
    Render full-resolution ProRes 422 QuickTime from a JPG frame sequence.
    Uses ffmpeg's concat demuxer with a temp file list.
    Shows a two-line progress bar (take + batch).
    """
    if not frame_files:
        die(f"No frame files for take {take_name}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    total_frames = len(frame_files)

    # Build a concat file list
    list_file: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            for frame in frame_files:
                f.write(f"file '{frame.resolve()}'\n")
                f.write(f"duration {1.0 / fps}\n")
            list_file = Path(f.name)

        cmd = [
            "ffmpeg", "-y",
            "-loglevel", "warning",
            "-nostats",
            "-f", "concat",
            "-safe", "0",
            "-r", str(fps),
            "-i", str(list_file),
            "-c:v", "prores_ks",
            "-profile:v", "2",       # ProRes 422
            "-pix_fmt", "yuv422p10le",
            "-r", str(fps),
            "-progress", "pipe:1",
            str(output_path)
        ]

        batch_label = f"[{task_idx}/{total_tasks}] " if total_tasks > 0 else ""
        print(f"\n⏳ {batch_label}Rendering ProRes 422: {take_name}")
        print(f"   Input:  {total_frames} frames")
        print(f"   Output: {output_path}")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace"
        )

        current_frame = 0
        speed_str = ""

        try:
            for line in process.stdout:
                line = line.strip()
                if line.startswith("frame="):
                    try:
                        val = line.split("=", 1)[1].strip()
                        if val != "N/A":
                            current_frame = max(0, int(val))
                    except (ValueError, IndexError):
                        pass
                elif line.startswith("speed="):
                    speed_str = line.split("=", 1)[1].strip()
                elif line in ("progress=continue", "progress=end"):
                    sfx = f"| Frame {current_frame}/{total_frames}"
                    if speed_str and speed_str != "N/A":
                        sfx += f" | {speed_str}"
                    print_progress(
                        current_frame, total_frames,
                        task_idx, total_tasks,
                        suffix=sfx
                    )
        except Exception:
            pass

        process.wait()
        finish_progress()

        if process.returncode != 0:
            stderr_output = process.stderr.read()
            print(f"❌ ffmpeg failed: {stderr_output}", file=sys.stderr)
            raise subprocess.CalledProcessError(process.returncode, cmd)

        print(f"✅ ProRes 422 created: {output_path}")

    finally:
        if list_file:
            try:
                list_file.unlink()
            except Exception:
                pass

# ---------- Main ----------
def main():
    cfg = load_cfg()

    gp_pool_root = Path(cfg.get("GP_JPGSEQ_POOL_ROOT", ""))
    gp_wr_pool   = Path(cfg.get("GP_WR_POOL", ""))
    fps          = cfg.get("wr", {}).get("fps", 24)

    if not gp_pool_root or not gp_pool_root.exists():
        die(f"GP_JPGSEQ_POOL_ROOT not found or does not exist: {gp_pool_root}")
    if not gp_wr_pool:
        die("GP_WR_POOL not set in gopro_config.json. Add it and try again.")

    print("=== GoPro ProRes 422 WR Renderer ===")
    print(f"GP_JPGSEQ_POOL_ROOT: {gp_pool_root}")
    print(f"GP_WR_POOL:          {gp_wr_pool}")
    print(f"Frame rate:          {fps} fps")

    # Ensure output root exists
    if not gp_wr_pool.exists():
        print(f"Creating GP_WR_POOL: {gp_wr_pool}")
        gp_wr_pool.mkdir(parents=True, exist_ok=True)

    # Discover every take across all bins
    print("\nScanning for take reports…")
    available = discover_all_takes(gp_pool_root)

    if not available:
        die("No takes found. Run take_maker.py on a bin folder first.")

    bin_count = len(set(v["bin_name"] for v in available.values()))
    print(f"Found {len(available)} take(s) across {bin_count} bin(s)")

    # Let user choose
    selected_names = prompt_for_takes(available)

    print(f"\nWill render {len(selected_names)} take(s):")
    for name in selected_names:
        info = available[name]
        print(f"  • {name}  ({info['frame_count']} frames, bin: {info['bin_name']})")

    proceed = input("\nProceed? [Y/n]: ").strip().lower()
    if proceed in ("n", "no"):
        die("Aborted by user.", code=0)

    # Render
    total = len(selected_names)
    errors = 0

    for i, take_name in enumerate(selected_names, 1):
        info = available[take_name]
        bin_folder = info["bin_folder"]

        frame_files = get_frame_files_in_range(info["first_path"], info["last_path"], bin_folder)

        if not frame_files:
            print(f"⚠️  Skipping {take_name}: no frame files found")
            errors += 1
            continue

        output_path = gp_wr_pool / info["bin_name"] / f"{take_name}.mov"

        if output_path.exists():
            overwrite = input(f"Output exists: {output_path}\nOverwrite? [y/N]: ").strip().lower()
            if overwrite not in ("y", "yes"):
                print(f"Skipping {take_name}")
                continue

        try:
            generate_prores422(take_name, frame_files, output_path, fps,
                               task_idx=i, total_tasks=total)
        except Exception as e:
            print(f"❌ Failed to render {take_name}: {e}", file=sys.stderr)
            errors += 1
            continue

    if errors:
        print(f"\n⚠️  Rendering complete with {errors} error(s).")
    else:
        print("\n✅ All ProRes 422 renders complete.")

if __name__ == "__main__":
    main()
