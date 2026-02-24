#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GoPro Time-Lapse Take Detection
Analyzes JPG image sequences and detects takes based on frame number breaks.

- Scans all JPG files recursively in bin folder
- Parses GoPro filenames: G{group}{frame}.JPG (e.g., G0018174.JPG)
- Extracts frame number (last 4 digits: 8174)
- Detects breaks when frame number jumps by >1
- Exception: 9999 → 0001 is NOT a break (rollover)
- Groups consecutive frames into takes
- Take naming: YYYYMMDD_GP_##_tk### format
  - Take numbers restart at tk001 for each bin folder
  - Letter suffixes (tk001a, tk001b) used when 9999→0001 rollover occurs
- Outputs CSV report: _reports/gp_wr_take_report_{bin_name}.csv

Env/config used:
  CONFIG_PATH (optional, JSON config)
  GP_BIN_FOLDER -> path to bin folder to analyze
"""

import os
import re
import sys
import csv
import json
from pathlib import Path
from typing import List, Tuple, Optional

# GoPro filename pattern: G{group}{frame}.JPG
# Example: G0018174.JPG -> group=001, frame=8174
GOPRO_PATTERN = re.compile(r"^G(\d{3})(\d{4})\.JPG$", re.IGNORECASE)

# JPG file extensions
JPG_EXTS = {".jpg", ".jpeg", ".JPG", ".JPEG"}

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
    # Prompt for folder if not provided
    print("No GP_BIN_FOLDER environment variable set.")
    while True:
        p = input("Enter path to bin folder to analyze (or press Enter to abort): ").strip()
        if not p:
            sys.exit("Aborted by user.")
        bin_path = Path(p)
        if bin_path.exists() and bin_path.is_dir():
            GP_BIN_FOLDER = str(bin_path)
            break
        print(f"Path not found or not a directory: {p}")

BIN_FOLDER = Path(GP_BIN_FOLDER)
if not BIN_FOLDER.exists():
    die(f"Bin folder not found: {BIN_FOLDER}")

# Extract bin name from folder path
BIN_NAME = BIN_FOLDER.name

# ---------- Helpers ----------
def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)

def is_hidden_or_metadata(p: Path) -> bool:
    return p.name.startswith(".") or p.name.startswith("._")

def extract_group_and_frame(filename: str) -> Optional[Tuple[int, int]]:
    """
    Extract group number and frame number from GoPro filename.
    Returns (group, frame) tuple or None if filename doesn't match pattern.
    Example: G0018174.JPG -> (1, 8174)
    """
    m = GOPRO_PATTERN.match(filename)
    if m:
        group = int(m.group(1))  # First 3 digits (001 -> 1)
        frame = int(m.group(2))  # Last 4 digits (8174 -> 8174)
        return (group, frame)
    return None

def extract_frame_number(filename: str) -> Optional[int]:
    """
    Extract frame number from GoPro filename (for backward compatibility).
    Returns None if filename doesn't match pattern.
    """
    result = extract_group_and_frame(filename)
    if result:
        return result[1]  # Return frame number
    return None

def list_jpg_files_recursive(root: Path) -> List[Path]:
    """List all JPG files recursively, skipping hidden/metadata files."""
    files = []
    for p in root.rglob("*"):
        if p.is_file() and not is_hidden_or_metadata(p) and p.suffix in JPG_EXTS:
            files.append(p)
    return files

def is_rollover(current_group: int, current_frame: int, next_group: int, next_frame: int) -> bool:
    """
    Check if next frame is a rollover from current frame (9999 → 0001).
    GoPro increments the group number on rollover (e.g., G001→G002),
    so we allow the group to change by exactly +1.
    """
    if current_frame == 9999 and next_frame == 1:
        # Same group or group incremented by 1 (GoPro rolls group on 9999→0001)
        return next_group == current_group or next_group == current_group + 1
    return False

def is_break(current_group: int, current_frame: int, next_group: int, next_frame: int) -> bool:
    """
    Determine if there's a break between current and next frame.
    Break occurs if:
    1. Group number changes (G001 → G002), OR
    2. Frame number jumps by more than 1 (unless it's a rollover)
    """
    # If group number changes, it's always a break
    if current_group != next_group:
        return True
    
    # Same group - check frame number continuity
    expected_next = current_frame + 1
    if next_frame == expected_next:
        return False  # Consecutive
    if is_rollover(current_group, current_frame, next_group, next_frame):
        return False  # Rollover, not a break
    return True  # Break detected (frame jump > 1)

def generate_take_name(bin_name: str, take_num: int, letter_suffix: Optional[str] = None) -> str:
    """
    Generate take name: YYYYMMDD_GP_##_tk### or YYYYMMDD_GP_##_tk###a
    """
    base = f"{bin_name}_tk{take_num:03d}"
    if letter_suffix:
        return f"{base}{letter_suffix}"
    return base

def detect_takes(files: List[Path]) -> List[Tuple[str, Path, Path, int]]:
    """
    Detect takes from sorted list of JPG files.
    Returns list of (take_name, first_frame_path, last_frame_path, frame_count) tuples.
    """
    if not files:
        return []
    
    # Sort files by filename to maintain order across folders
    sorted_files = sorted(files, key=lambda p: p.name)
    
    takes = []
    current_take_start: Optional[Path] = None
    current_take_last: Optional[Path] = None
    current_group: Optional[int] = None
    current_frame: Optional[int] = None
    take_num = 1
    letter_suffix_idx = 0  # For tracking rollovers: 0='a', 1='b', etc.
    
    for file_path in sorted_files:
        result = extract_group_and_frame(file_path.name)
        if result is None:
            # Skip files that don't match GoPro pattern
            continue
        
        next_group, next_frame = result
        
        if current_take_start is None:
            # First file - start new take segment
            current_take_start = file_path
            current_take_last = file_path
            current_group = next_group
            current_frame = next_frame
            continue
        
        # Check if this is a rollover (9999 → 0001, possibly with group increment)
        if is_rollover(current_group, current_frame, next_group, next_frame):
            # End current segment and start new segment with letter suffix
            if current_take_start and current_take_last:
                # First rollover: this segment gets 'a'
                letter_suffix = chr(ord('a') + letter_suffix_idx)
                take_name = generate_take_name(BIN_NAME, take_num, letter_suffix)
                takes.append((take_name, current_take_start, current_take_last, 0))
            
            # Start new segment (same take number, next letter)
            letter_suffix_idx += 1
            current_take_start = file_path
            current_take_last = file_path
            current_group = next_group
            current_frame = next_frame
        elif is_break(current_group, current_frame, next_group, next_frame):
            # End current take and start new one (new take number)
            if current_take_start and current_take_last:
                # Use letter suffix only if rollovers occurred for this take
                letter_suffix = chr(ord('a') + letter_suffix_idx) if letter_suffix_idx > 0 else None
                take_name = generate_take_name(BIN_NAME, take_num, letter_suffix)
                takes.append((take_name, current_take_start, current_take_last, 0))
            
            # Start new take
            take_num += 1
            letter_suffix_idx = 0
            current_take_start = file_path
            current_take_last = file_path
            current_group = next_group
            current_frame = next_frame
        else:
            # Continue current segment (consecutive frame, same group)
            current_take_last = file_path
            current_group = next_group
            current_frame = next_frame
    
    # Don't forget the last take segment
    if current_take_start and current_take_last:
        letter_suffix = chr(ord('a') + letter_suffix_idx) if letter_suffix_idx > 0 else None
        take_name = generate_take_name(BIN_NAME, take_num, letter_suffix)
        takes.append((take_name, current_take_start, current_take_last, 0))
    
    return takes


def main():
    print(f"=== GoPro Take Detection ===")
    print(f"Bin folder: {BIN_FOLDER}")
    
    # Collect all JPG files
    print("Scanning for JPG files...")
    jpg_files = list_jpg_files_recursive(BIN_FOLDER)
    
    if not jpg_files:
        die(f"No JPG files found in {BIN_FOLDER}")
    
    print(f"Found {len(jpg_files)} JPG file(s)")
    
    # Detect takes
    print("Analyzing frame sequences...")
    takes = detect_takes(jpg_files)
    
    if not takes:
        die("No takes detected. Check that files match GoPro naming pattern (G#######.JPG)")
    
    print(f"Detected {len(takes)} take(s)")
    
    # Recalculate frame counts accurately by counting files in sorted list
    print("Calculating frame counts...")
    all_sorted = sorted(jpg_files, key=lambda p: p.name)
    takes_with_counts = []
    for take_name, first_path, last_path, _ in takes:
        # Find indices in sorted list
        first_idx = None
        last_idx = None
        for i, p in enumerate(all_sorted):
            if p == first_path:
                first_idx = i
            if p == last_path:
                last_idx = i
        
        if first_idx is not None and last_idx is not None:
            frame_count = last_idx - first_idx + 1
        else:
            # Fallback: calculate from frame numbers
            first_frame = extract_frame_number(first_path.name)
            last_frame = extract_frame_number(last_path.name)
            if first_frame is not None and last_frame is not None:
                if last_frame >= first_frame:
                    frame_count = last_frame - first_frame + 1
                else:
                    # Rollover case: frames from first_frame to 9999, then 1 to last_frame
                    frame_count = (9999 - first_frame + 1) + last_frame
            else:
                frame_count = 0
        
        takes_with_counts.append((take_name, first_path, last_path, frame_count))
    
    # Write CSV report
    reports_dir = BIN_FOLDER / "_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    csv_path = reports_dir / f"gp_wr_take_report_{BIN_NAME}.csv"
    
    print(f"\nWriting report: {csv_path}")
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["take_name", "first_frame_path", "last_frame_path", "frames_total"])
        for take_name, first_path, last_path, frame_count in takes_with_counts:
            w.writerow([
                take_name,
                str(first_path.resolve()),
                str(last_path.resolve()),
                frame_count
            ])
    
    # Summary
    print("\n✅ Take detection complete.")
    print(f"Report: {csv_path}")
    print(f"\nTakes detected:")
    for take_name, first_path, last_path, frame_count in takes_with_counts:
        print(f"  {take_name}: {frame_count} frames ({first_path.name} → {last_path.name})")

if __name__ == "__main__":
    main()
