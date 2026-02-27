#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Scan a root directory for files named C####.MP4 (case-insensitive),
summarize totals, size, duplicates, missing sequence numbers,
and export a human-readable report + a CSV.

Usage (non-interactive):
  python3 find_c_clips.py --root /path/to/search
Optional:
  --outdir /path/to/save/outputs   (defaults to --root)
  --follow-symlinks                (follow directory symlinks)

If --root is not provided, the script enters interactive mode and prompts
for root/outdir and whether to follow symlinks.
"""

import argparse
import csv
import os
import re
import bisect
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

PATTERN = re.compile(r"^C(\d{4})\.MP4$", re.IGNORECASE)

def human_bytes(n: int) -> str:
    for unit in ["B","KB","MB","GB","TB"]:
        if n < 1024 or unit == "TB":
            return f"{n:.2f} {unit}" if unit != "B" else f"{n} {unit}"
        n /= 1024

def walk_files(root: Path, follow_symlinks=False):
    stack = [root]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=follow_symlinks):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            yield Path(entry.path)
                    except PermissionError:
                        continue
        except (PermissionError, FileNotFoundError):
            continue

# --- Interactive path helpers (handles quoted paths and \-escaped spaces) ---
def _strip_outer_quotes(s: str) -> str:
    s = s.strip()
    if (len(s) >= 2) and ((s[0] == s[-1]) and s[0] in ("'", '"')):
        return s[1:-1]
    return s

def _unescape_spaces_if_needed(p: Path) -> Path:
    raw = str(p)
    if "\\ " in raw and not p.exists():
        return Path(raw.replace("\\ ", " "))
    return p

def prompt_path(prompt_text: str, must_exist_dir=True, default: Optional[Path] = None) -> Path:
    while True:
        raw = input(prompt_text).strip()
        if not raw and default is not None:
            candidate = default
        else:
            cleaned = _strip_outer_quotes(raw)
            candidate = Path(cleaned).expanduser()
            candidate = _unescape_spaces_if_needed(candidate)

        if must_exist_dir:
            if candidate.exists() and candidate.is_dir():
                return candidate.resolve()
            print("Path must exist and be a directory. Try again.")
        else:
            candidate = Path(str(candidate).replace("\\ ", " "))
            return candidate.resolve()

def prompt_yes_no(prompt_text: str, default=False) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        ans = input(prompt_text + suffix).strip().lower()
        if ans == "" and default is not None:
            return default
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print("Please answer Y or N.")

def resolve_args():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--root", help="Root directory to search")
    ap.add_argument("--outdir", help="Directory to write outputs (default: root)")
    ap.add_argument("--follow-symlinks", action="store_true", help="Follow directory symlinks")
    ap.add_argument("-h", "--help", action="store_true")
    args, _ = ap.parse_known_args()

    if args.help:
        full = argparse.ArgumentParser(description="Scan for C####.MP4 files and report/CSV outputs.")
        full.add_argument("--root", required=False, help="Root directory to search")
        full.add_argument("--outdir", required=False, help="Directory to write outputs (default: root)")
        full.add_argument("--follow-symlinks", action="store_true", help="Follow directory symlinks")
        full.print_help()
        raise SystemExit(0)

    if not args.root:
        print("Interactive mode (no --root specified).")
        root = prompt_path("Enter ROOT directory to search: ", must_exist_dir=True)
        outdir = prompt_path(f"Enter OUTDIR for outputs (blank = use ROOT: {root}): ",
                             must_exist_dir=False, default=root)
        follow = prompt_yes_no("Follow directory symlinks?", default=False)
        return argparse.Namespace(root=str(root), outdir=str(outdir), follow_symlinks=follow)

    root = Path(_strip_outer_quotes(args.root)).expanduser()
    root = _unescape_spaces_if_needed(root).resolve()
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Root does not exist or is not a directory: {root}")

    if args.outdir:
        outdir = Path(_strip_outer_quotes(args.outdir)).expanduser()
        outdir = Path(str(outdir).replace("\\ ", " ")).resolve()
    else:
        outdir = root

    return argparse.Namespace(root=str(root), outdir=str(outdir), follow_symlinks=args.follow_symlinks)

def main():
    ns = resolve_args()
    root = Path(ns.root)
    outdir = Path(ns.outdir)
    follow_symlinks = ns.follow_symlinks

    outdir.mkdir(parents=True, exist_ok=True)

    matches = []   # all occurrences
    groups = {}    # UPPER filename -> list[rec]
    seq_numbers = set()

    for p in walk_files(root, follow_symlinks=follow_symlinks):
        m = PATTERN.match(p.name)
        if not m:
            continue
        num = int(m.group(1))
        try:
            st = p.stat()
        except (FileNotFoundError, PermissionError):
            continue
        rec = {
            "filename": p.name,
            "filename_upper": p.name.upper(),
            "clip_number": num,
            "path": str(p),
            "parent_folder": str(p.parent),
            "size_bytes": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
        }
        matches.append(rec)
        groups.setdefault(p.name.upper(), []).append(rec)
        seq_numbers.add(num)

    total_files = len(matches)
    total_size_bytes = sum(r["size_bytes"] for r in matches)

    # Canonical "source" per filename (earliest mtime, tie -> lexicographic path)
    canonical_by_name = {}
    for fname_upper, recs in groups.items():
        recs_sorted = sorted(recs, key=lambda r: (r["mtime"], r["path"]))
        canonical_by_name[fname_upper] = recs_sorted[0]

    # Map existing clip number -> canonical record (for neighbor/folder lookups)
    by_number = {}
    for rec in canonical_by_name.values():
        by_number[rec["clip_number"]] = rec

    # Unique total size (sum of canonical only)
    unique_total_size_bytes = sum(rec["size_bytes"] for rec in by_number.values())

    # Missing sequence
    if seq_numbers:
        seq_min = min(seq_numbers)
        seq_max = max(seq_numbers)
        missing = [n for n in range(seq_min, seq_max + 1) if n not in seq_numbers]
    else:
        seq_min = seq_max = None
        missing = []

    # Build neighbor lookup structure for expected-folder inference
    sorted_existing = sorted(seq_numbers)  # strictly increasing

    def neighbor_info(n: int):
        """Return (lower_rec or None, higher_rec or None) nearest to n."""
        i = bisect.bisect_left(sorted_existing, n)
        lower_rec = by_number.get(sorted_existing[i-1]) if i > 0 else None
        higher_rec = by_number.get(sorted_existing[i]) if i < len(sorted_existing) else None
        return lower_rec, higher_rec

    # CSV (same as before)
    csv_path = outdir / "clips.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "clip_number", "filename", "role", "is_duplicate",
            "path", "parent_folder",
            "source_path_if_duplicate",
            "size_bytes", "size_human",
            "mtime_utc_iso",
        ])
        for fname_upper, recs in sorted(groups.items()):
            source = canonical_by_name[fname_upper]
            # source
            w.writerow([
                source["clip_number"], source["filename"],
                "source", "no",
                source["path"], source["parent_folder"],
                "",
                source["size_bytes"], human_bytes(source["size_bytes"]),
                source["mtime"].isoformat().replace("+00:00", "Z"),
            ])
            # duplicates
            if len(recs) > 1:
                for dup in sorted(recs[1:], key=lambda r: (r["mtime"], r["path"])):
                    w.writerow([
                        dup["clip_number"], dup["filename"],
                        "duplicate", "yes",
                        dup["path"], dup["parent_folder"],
                        source["path"],
                        dup["size_bytes"], human_bytes(dup["size_bytes"]),
                        dup["mtime"].isoformat().replace("+00:00", "Z"),
                    ])

    # -------- REPORT --------
    report_lines = []
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    report_lines.append(f"Scan timestamp (UTC): {now}")
    report_lines.append(f"Root: {root}")
    report_lines.append(f"Outdir: {outdir}")
    report_lines.append(f"Follow symlinks: {follow_symlinks}")
    report_lines.append("")
    report_lines.append("=== SUMMARY ===")
    report_lines.append(f"Total matching files (all occurrences): {total_files}")
    report_lines.append(f"Total size (all occurrences): {human_bytes(total_size_bytes)} ({total_size_bytes} bytes)")
    report_lines.append(f"Unique filenames: {len(groups)}")
    report_lines.append(f"Unique total size (one per filename): {human_bytes(unique_total_size_bytes)} ({unique_total_size_bytes} bytes)")
    duplicates_count = sum(max(0, len(v)-1) for v in groups.values())
    report_lines.append(f"Duplicate occurrences (beyond 1 per name): {duplicates_count}")
    if seq_min is not None:
        report_lines.append(f"Sequence range detected: C{seq_min:04d} – C{seq_max:04d}")
        report_lines.append(f"Missing from sequence between C{seq_min:04d} and C{seq_max:04d}: {len(missing)}")
    else:
        report_lines.append("No C####.MP4 files found; sequence analysis skipped.")

    # (A) MISSING SEQ NUMBERS — compact list only
    report_lines.append("")
    report_lines.append("=== MISSING SEQUENCE NUMBERS ===")
    if seq_min is not None and missing:
        # print in chunks to avoid overly long lines
        labels = [f"C{n:04d}" for n in missing]
        line = []
        max_line_len = 90  # target width
        cur = ""
        for lab in labels:
            nxt = (lab if not cur else f"{cur}, {lab}")
            if len(nxt) > max_line_len:
                report_lines.append(cur)
                cur = lab
            else:
                cur = nxt
        if cur:
            report_lines.append(cur)
    elif seq_min is not None:
        report_lines.append("None")
    else:
        report_lines.append("N/A")

    # (B) MISSING CLIPS — EXPECTED FOLDERS (concise one-liners)
    report_lines.append("")
    report_lines.append("=== MISSING CLIPS — EXPECTED FOLDERS ===")
    if seq_min is not None and missing:
        for n in missing:
            low, high = neighbor_info(n)
            tag = f"C{n:04d}"
            if low and high:
                if low["parent_folder"] == high["parent_folder"]:
                    report_lines.append(f"{tag} → {low['parent_folder']}  (neighbors: C{low['clip_number']:04d}, C{high['clip_number']:04d})")
                else:
                    report_lines.append(f"{tag} → between {low['parent_folder']} ⇄ {high['parent_folder']}  (nearest: C{low['clip_number']:04d}, C{high['clip_number']:04d}; early slate/test possible)")
            elif low and not high:
                report_lines.append(f"{tag} → {low['parent_folder']}  (nearest: C{low['clip_number']:04d})")
            elif high and not low:
                report_lines.append(f"{tag} → {high['parent_folder']}  (nearest: C{high['clip_number']:04d}; early slate/test possible)")
            else:
                report_lines.append(f"{tag} → (no neighbors)")
    elif seq_min is not None:
        report_lines.append("None")
    else:
        report_lines.append("N/A")

    report_path = outdir / "report.txt"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    print("Done.")
    print(f"Report: {report_path}")
    print(f"CSV:    {csv_path}")

if __name__ == "__main__":
    main()