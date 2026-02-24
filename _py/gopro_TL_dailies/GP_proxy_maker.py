#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GoPro Time-Lapse Proxy Maker
Generates H.264 proxy files with burn-in metadata from takes listed in CSV report.

- Reads CSV report from take_maker.py
- Generates H.264 MP4 proxies for each take
- Width: 1920 pixels (maintains aspect ratio)
- Frame rate: 24fps
- Output: GP_JPGSEQ_POOL_ROOT/{bin_name}/_proxies/{take_name}.mp4

Burn-in includes:
- Proxy filename (top-left)
- Camera type (top-right)
- Source JPG filename (bottom-left)
- Frame counter / Timecode (bottom-right)

Env/config used:
  CONFIG_PATH (optional, JSON config)
  GP_BIN_FOLDER -> path to bin folder
"""

import os
import sys
import csv
import json
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import List, Tuple, Optional, Dict
try:
    import exifread
except ImportError:
    print("ERROR: exifread not installed. Install with: pip install exifread", file=sys.stderr)
    sys.exit(1)

# ---------- Config / Environment ----------
def load_cfg() -> dict:
    cfg_path = os.getenv("CONFIG_PATH")
    if not cfg_path:
        script_dir = Path(__file__).parent
        cfg_path = str(script_dir / "gopro_config.json")
    
    if Path(cfg_path).exists():
        with open(cfg_path, "r") as f:
            return json.load(f)
    return {}

CFG = load_cfg()

GP_BIN_FOLDER = os.getenv("GP_BIN_FOLDER")
if not GP_BIN_FOLDER:
    die("GP_BIN_FOLDER environment variable not set. This script must be run via workflow_launcher.py")

GP_PROXY_POOL = os.getenv("GP_PROXY_POOL")
if not GP_PROXY_POOL:
    die("GP_PROXY_POOL environment variable not set. This script must be run via workflow_launcher.py")

BIN_FOLDER = Path(GP_BIN_FOLDER)
if not BIN_FOLDER.exists():
    die(f"Bin folder not found: {BIN_FOLDER}")

PROXY_POOL_ROOT = Path(GP_PROXY_POOL)
if not PROXY_POOL_ROOT.exists():
    print(f"Creating GP_PROXY_POOL: {PROXY_POOL_ROOT}")
    PROXY_POOL_ROOT.mkdir(parents=True, exist_ok=True)

BIN_NAME = BIN_FOLDER.name
PROXY_CONFIG = CFG.get("proxy", {})
PROXY_WIDTH = PROXY_CONFIG.get("width", 1920)
PROXY_FPS = PROXY_CONFIG.get("fps", 24)
PROXY_CRF = PROXY_CONFIG.get("crf", 23)
PROXY_PRESET = PROXY_CONFIG.get("preset", "fast")

# ---------- Helpers ----------
def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)

def find_csv_report(bin_folder: Path) -> Optional[Path]:
    """Find the take report CSV file."""
    reports_dir = bin_folder / "_reports"
    if not reports_dir.exists():
        return None
    
    # Look for gp_wr_take_report_{bin_name}.csv
    csv_file = reports_dir / f"gp_wr_take_report_{bin_folder.name}.csv"
    if csv_file.exists():
        return csv_file
    
    # Fallback: find any gp_wr_take_report_*.csv
    for csv_file in reports_dir.glob("gp_wr_take_report_*.csv"):
        return csv_file
    
    return None

def load_takes_from_csv(csv_path: Path) -> List[Tuple[str, Path, Path, int]]:
    """Load takes from CSV report. Returns list of (take_name, first_path, last_path, frame_count)."""
    takes = []
    with csv_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            take_name = row["take_name"]
            first_path = Path(row["first_frame_path"])
            last_path = Path(row["last_frame_path"])
            frame_count = int(row["frames_total"])
            takes.append((take_name, first_path, last_path, frame_count))
    return takes

def get_frame_files_in_range(first_path: Path, last_path: Path, bin_folder: Path) -> List[Path]:
    """
    Get all frame files between first_path and last_path (inclusive).
    Files are sorted by filename to maintain order.
    """
    # Collect all JPG files in bin folder
    all_files = []
    for p in bin_folder.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg"}:
            all_files.append(p)
    
    # Sort by filename
    all_files.sort(key=lambda p: p.name)
    
    # Find range
    first_idx = None
    last_idx = None
    for i, p in enumerate(all_files):
        if p == first_path:
            first_idx = i
        if p == last_path:
            last_idx = i
    
    if first_idx is not None and last_idx is not None:
        return all_files[first_idx:last_idx + 1]
    
    # Fallback: return just first and last if we can't find the range
    return [first_path, last_path] if first_path.exists() and last_path.exists() else []

def format_timecode(frame_number: int, fps: int) -> str:
    """Convert frame number to timecode format HH:MM:SS:FF."""
    total_seconds = frame_number // fps
    frames = frame_number % fps
    
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"

def escape_filter_text(text: str) -> str:
    """Escape text for use in ffmpeg drawtext filter."""
    # Remove null bytes and other control characters
    text = text.replace('\x00', '')  # Remove null bytes
    text = ''.join(char for char in text if ord(char) >= 32 or char in '\n\r\t')  # Remove other control chars
    
    # Escape special characters: \, :, ', "
    text = text.replace("\\", "\\\\")
    text = text.replace(":", "\\:")
    text = text.replace("'", "\\'")
    text = text.replace('"', '\\"')
    text = text.replace('[', '\\[')
    text = text.replace(']', '\\]')
    return text

def extract_exif_metadata(image_path: Path) -> Dict[str, str]:
    """
    Extract EXIF metadata from JPG image using exifread.
    Returns dict with: camera_model, aperture, exposure_time, iso, f_number
    """
    metadata = {
        "camera_model": "Unknown",
        "aperture": "N/A",
        "exposure_time": "N/A",
        "iso": "N/A",
        "f_number": "N/A"
    }
    
    try:
        with open(image_path, 'rb') as f:
            tags = exifread.process_file(f, details=False)
            
            # Extract Device Model (camera type)
            if "Image Model" in tags:
                model_val = str(tags["Image Model"])
                metadata["camera_model"] = model_val.replace('\x00', '').strip()
            elif "Image Make" in tags:
                make_val = str(tags["Image Make"])
                metadata["camera_model"] = make_val.replace('\x00', '').strip()
            
            # Extract FNumber (preferred over ApertureValue)
            if "EXIF FNumber" in tags:
                fnum_str = str(tags["EXIF FNumber"])
                # Parse fraction like "14/5" or decimal
                if '/' in fnum_str:
                    num, den = map(float, fnum_str.split('/'))
                    f_value = num / den
                else:
                    f_value = float(fnum_str)
                metadata["f_number"] = f"f/{f_value:.1f}"
            
            # Extract ApertureValue as fallback
            elif "EXIF ApertureValue" in tags:
                aperture_str = str(tags["EXIF ApertureValue"])
                if '/' in aperture_str:
                    num, den = map(float, aperture_str.split('/'))
                    # APEX value: 2^((aperture_value)/2)
                    apex = num / den
                    f_value = 2 ** (apex / 2)
                else:
                    apex = float(aperture_str)
                    f_value = 2 ** (apex / 2)
                metadata["f_number"] = f"f/{f_value:.1f}"
            
            # Extract Exposure Time
            if "EXIF ExposureTime" in tags:
                exp_str = str(tags["EXIF ExposureTime"])
                if '/' in exp_str:
                    num, den = map(float, exp_str.split('/'))
                    exp_seconds = num / den
                else:
                    exp_seconds = float(exp_str)
                
                if exp_seconds < 1:
                    metadata["exposure_time"] = f"1/{int(1/exp_seconds)}s"
                else:
                    metadata["exposure_time"] = f"{exp_seconds:.2f}s"
            
            # Extract ISO
            if "EXIF ISOSpeedRatings" in tags:
                iso_val = str(tags["EXIF ISOSpeedRatings"])
                metadata["iso"] = f"ISO {iso_val}"
            elif "EXIF ISO" in tags:
                iso_val = str(tags["EXIF ISO"])
                metadata["iso"] = f"ISO {iso_val}"
            
            # Extract Aperture (FNumber) for aperture field
            if metadata["f_number"] != "N/A":
                metadata["aperture"] = metadata["f_number"]
            
    except Exception as e:
        print(f"Warning: Could not extract EXIF from {image_path.name}: {e}", file=sys.stderr)
    
    # Sanitize all metadata values to remove null bytes and control characters
    for key in metadata:
        if isinstance(metadata[key], str):
            # Remove null bytes and other problematic characters
            metadata[key] = metadata[key].replace('\x00', '')
            metadata[key] = ''.join(char for char in metadata[key] if ord(char) >= 32 or char in '\n\r\t')
            metadata[key] = metadata[key].strip()
    
    return metadata

def build_burnin_filter(take_name: str, metadata: Dict[str, str], total_frames: int, fps: int,
                        parent_dir: str, group_num: int, start_frame: int) -> str:
    """
    Build ffmpeg drawtext filter string for burn-in metadata.
    
    Layout:
    - Top-left: Proxy filename
    - Top-right: Camera model
    - Below top-left: Exposure settings (f-stop, shutter, ISO dynamic)
    - Bottom-left line 1: Frame counter
    - Bottom-left line 2: Source JPG dir/filename (computed dynamically from frame number)
    - Bottom-right: Timecode HH:MM:SS:FF
    """
    proxy_filename = escape_filter_text(f"{take_name}.mp4")
    camera_text = escape_filter_text(metadata.get("camera_model", "Unknown"))
    f_number = escape_filter_text(metadata.get("f_number", "N/A"))
    exposure_time = escape_filter_text(metadata.get("exposure_time", "N/A"))
    
    # Top-left: Proxy filename
    drawtext_top_left = (
        f"drawtext=text='{proxy_filename}':"
        f"fontcolor=white:fontsize=24:x=10:y=10:"
        f"box=1:boxcolor=black@0.5:boxborderw=5"
    )
    
    # Top-right: Camera model
    drawtext_top_right = (
        f"drawtext=text='{camera_text}':"
        f"fontcolor=white:fontsize=24:x=w-text_w-10:y=10:"
        f"box=1:boxcolor=black@0.5:boxborderw=5"
    )
    
    # Below top-left: Exposure settings
    # FNumber and ExposureTime are static (formatted in Python from first frame EXIF)
    # ISO is dynamic per frame via image2 metadata (GoPro auto-adjusts ISO)
    drawtext_exposure = (
        f"drawtext=text='{f_number}  {exposure_time}  ISO %{{metadata\\:ISOSpeedRatings}}':"
        f"fontcolor=white:fontsize=20:x=10:y=50:"
        f"box=1:boxcolor=black@0.5:boxborderw=5"
    )
    
    # Bottom-left line 1: Frame counter (1-based)
    drawtext_frame_counter = (
        f"drawtext=text='Frame %{{eif\\:n+1\\:d}} of {total_frames}':"
        f"fontcolor=white:fontsize=20:x=10:y=h-text_h-30:"
        f"box=1:boxcolor=black@0.5:boxborderw=5"
    )
    
    # Bottom-left line 2: Source JPG dir/filename (computed dynamically)
    # GoPro filenames: G{group:03d}{frame:04d}.JPG
    # Within a take, group is constant and frame increments by 1 per frame
    # So filename = parent_dir/G{group:03d}{start_frame+n:04d}.JPG
    escaped_dir = escape_filter_text(parent_dir)
    drawtext_filename = (
        f"drawtext=text='"
        f"{escaped_dir}/G{group_num:03d}"
        f"%{{eif\\:{start_frame}+n\\:d\\:4}}"
        f".JPG':"
        f"fontcolor=white:fontsize=18:x=10:y=h-text_h-10:"
        f"box=1:boxcolor=black@0.5:boxborderw=5"
    )
    
    # Bottom-right: Timecode HH:MM:SS:FF
    # Calculate from frame number n and fps
    fph = fps * 3600   # frames per hour
    fpm = fps * 60     # frames per minute
    drawtext_timecode = (
        f"drawtext=text='"
        f"TC "
        f"%{{eif\\:floor(n/{fph})\\:d\\:2}}"
        f"\\:"
        f"%{{eif\\:floor(mod(n,{fph})/{fpm})\\:d\\:2}}"
        f"\\:"
        f"%{{eif\\:floor(mod(n,{fpm})/{fps})\\:d\\:2}}"
        f"\\:"
        f"%{{eif\\:mod(n,{fps})\\:d\\:2}}"
        f"':"
        f"fontcolor=white:fontsize=20:x=w-text_w-10:y=h-text_h-10:"
        f"box=1:boxcolor=black@0.5:boxborderw=5"
    )
    
    filters = [
        drawtext_top_left,
        drawtext_top_right,
        drawtext_exposure,
        drawtext_frame_counter,
        drawtext_filename,
        drawtext_timecode
    ]
    
    return ",".join(filters)

# ---------- Progress display ----------
def format_elapsed(seconds: float) -> str:
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

# ---------- Proxy generation ----------
def generate_proxy(take_name: str, frame_files: List[Path], output_path: Path, fps: int, width: int, crf: int, preset: str,
                   task_idx: int = 0, total_tasks: int = 0):
    """
    Generate H.264 proxy file with burn-in metadata using ffmpeg.
    
    Uses the image2 demuxer with a temp directory of symlinks.
    Per-frame burn-in: ISO from EXIF metadata, filename computed from frame number.
    """
    if not frame_files:
        die(f"No frame files found for take {take_name}")
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Extract EXIF metadata from first frame
    print(f"   Extracting EXIF metadata from {frame_files[0].name}...")
    metadata = extract_exif_metadata(frame_files[0])
    
    print(f"   Camera: {metadata.get('camera_model', 'Unknown')}")
    print(f"   Settings: {metadata.get('f_number', 'N/A')} {metadata.get('exposure_time', 'N/A')} {metadata.get('iso', 'N/A')}")
    
    # Extract parent directory, group number, and starting frame from first frame
    # GoPro filenames: G{group:03d}{frame:04d}.JPG  e.g. G0014953.JPG
    import re
    parent_dir = frame_files[0].parent.name  # e.g. "100GOPRO"
    first_match = re.match(r"^G(\d{3})(\d{4})\.JPG$", frame_files[0].name, re.IGNORECASE)
    if first_match:
        group_num = int(first_match.group(1))
        start_frame = int(first_match.group(2))
    else:
        group_num = 0
        start_frame = 0
    
    # Build burn-in filter
    total_frames = len(frame_files)
    burnin_filter = build_burnin_filter(take_name, metadata, total_frames, fps,
                                        parent_dir, group_num, start_frame)
    
    # Sanitize filter string
    if '\x00' in burnin_filter:
        burnin_filter = burnin_filter.replace('\x00', '')
    
    # Create a temp directory with symlinks to only this take's frames.
    # image2 demuxer with -pattern_type glob reads them in sorted order
    # and exposes per-frame EXIF metadata (ISO, etc.) to drawtext filters.
    tmp_dir = tempfile.mkdtemp(prefix=f"gp_proxy_{take_name}_")
    
    try:
        # Create symlinks (original filenames preserved)
        for frame_file in frame_files:
            link_path = Path(tmp_dir) / frame_file.name
            link_path.symlink_to(frame_file.resolve())
        
        # Build the glob pattern for the temp directory
        glob_pattern = f"{tmp_dir}/*.JPG"
        
        cmd = [
            "ffmpeg", "-y",
            "-loglevel", "warning",
            "-nostats",
            "-f", "image2",
            "-pattern_type", "glob",
            "-framerate", str(fps),
            "-i", glob_pattern,
            "-vf", f"scale={width}:-1:flags=lanczos,{burnin_filter}",
            "-c:v", "libx264",
            "-preset", preset,
            "-crf", str(crf),
            "-pix_fmt", "yuv420p",
            "-r", str(fps),
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            str(output_path)
        ]
        
        batch_label = f"[{task_idx}/{total_tasks}] " if total_tasks > 0 else ""
        print(f"\n⏳ {batch_label}Generating proxy: {take_name}")
        print(f"   Input: {len(frame_files)} frames")
        print(f"   Output: {output_path}")
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace'
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
        
        print(f"✅ Proxy created: {output_path}")
        
    except subprocess.CalledProcessError as e:
        if not hasattr(e, 'stderr') or not e.stderr:
            error_msg = str(e)
        else:
            error_msg = e.stderr
        print(f"❌ ffmpeg failed: {error_msg}", file=sys.stderr)
        raise
    finally:
        # Clean up temp symlink directory
        try:
            shutil.rmtree(tmp_dir)
        except Exception:
            pass

def main():
    print(f"=== GoPro Proxy Generator ===")
    print(f"Bin folder: {BIN_FOLDER}")
    print(f"Proxy settings: {PROXY_WIDTH}px width, {PROXY_FPS}fps, CRF {PROXY_CRF}")
    
    # Find CSV report
    csv_path = find_csv_report(BIN_FOLDER)
    if not csv_path:
        die(f"Take report CSV not found in {BIN_FOLDER / '_reports'}. Run take_maker.py first.")
    
    print(f"Loading takes from: {csv_path}")
    takes = load_takes_from_csv(csv_path)
    
    if not takes:
        die("No takes found in CSV report.")
    
    print(f"\nFound {len(takes)} take(s)")
    for take_name, _, _, frame_count in takes:
        print(f"  • {take_name}: {frame_count} frames")
    
    # Process all takes (or could add selection logic here)
    proceed = input("\nGenerate proxies for all takes? [Y/n]: ").strip().lower()
    if proceed in ("n", "no"):
        print("Aborted.")
        return
    
    # Output directory: GP_PROXY_POOL/{bin_name}/
    output_dir = PROXY_POOL_ROOT / BIN_NAME
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {output_dir}")
    
    # Process each take
    total_takes = len(takes)
    print(f"\nProcessing {total_takes} take(s)...")
    for i, (take_name, first_path, last_path, frame_count) in enumerate(takes, 1):
        # Get all frame files for this take
        frame_files = get_frame_files_in_range(first_path, last_path, BIN_FOLDER)
        
        if not frame_files:
            print(f"⚠️  Skipping {take_name}: No frame files found")
            continue
        
        output_path = output_dir / f"{take_name}.mp4"
        
        if output_path.exists():
            overwrite = input(f"Output file exists: {output_path}\nOverwrite? [y/N]: ").strip().lower()
            if overwrite not in ("y", "yes"):
                print(f"Skipping {take_name}")
                continue
        
        try:
            generate_proxy(
                take_name,
                frame_files,
                output_path,
                PROXY_FPS,
                PROXY_WIDTH,
                PROXY_CRF,
                PROXY_PRESET,
                task_idx=i,
                total_tasks=total_takes
            )
        except Exception as e:
            print(f"❌ Failed to generate {take_name}: {e}", file=sys.stderr)
            continue
    
    print("\n✅ Proxy generation complete.")

if __name__ == "__main__":
    main()
