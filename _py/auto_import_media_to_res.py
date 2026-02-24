#!/usr/bin/env python3
# Auto import media into a bin named after the folder, then create a timeline from those clips.
# Reads environment from workflow_launcher.py / config.json:
#   CONFIG_PATH (optional), NAME, RESOLVE_PROJECT
# Usage:
#   python3 auto_import_media_to_res.py /path/to/media [--recursive] [--nested]
#   # or (interactive):
#   python3 auto_import_media_to_res.py

import os, sys, pathlib, datetime, json, re
from pathlib import Path

# --------- Arg / Env parsing ---------
def normalize_dragged_path(p: str) -> str:
    """Handle paths dragged into terminal that may have escaped spaces."""
    p = p.strip()
    # Try as-is first
    if pathlib.Path(p).exists():
        return p
    # If path starts with "/" and contains spaces (possibly escaped), try unescaping
    if p.startswith("/") and (" " in p or "\\ " in p):
        # Replace backslash-space with regular space
        unescaped = p.replace("\\ ", " ")
        if pathlib.Path(unescaped).exists():
            return unescaped
    return p

args = [a for a in sys.argv[1:] if a not in ["--nonrecursive", "--recursive", "--nested"]]
RECURSIVE = "--recursive" in sys.argv
NESTED_MODE = "--nested" in sys.argv

MEDIA = args[0] if args else os.getenv("MEDIA")
if MEDIA:
    MEDIA = normalize_dragged_path(MEDIA)

def prompt_media_path() -> str:
    print("No MEDIA path provided.")
    while True:
        p = input("Drag in the folder that contains the MEDIA you just copied to LACIE (or press Enter to abort): ").strip()
        if not p:
            raise SystemExit("Aborted by user (no MEDIA path).")
        normalized = normalize_dragged_path(p)
        if pathlib.Path(normalized).exists():
            return normalized
        print(f"Path not found: {p}")

def prompt_recursive_mode() -> bool:
    """Prompt user for recursive mode. Default is non-recursive (False)."""
    resp = input("Scan recursively (include files in subdirectories)? [y/N]: ").strip().lower()
    return resp in ("y", "yes")

def prompt_nested_mode() -> bool:
    """Prompt user for nested mode. Default is single folder mode (False)."""
    resp = input("Process nested folders (create timeline for each subfolder with media)? [y/N]: ").strip().lower()
    return resp in ("y", "yes")

if not MEDIA:
    MEDIA = prompt_media_path()
    # If in interactive mode and flags weren't provided, prompt for them
    if not args and "--recursive" not in sys.argv:
        RECURSIVE = prompt_recursive_mode()
    if not args and "--nested" not in sys.argv:
        NESTED_MODE = prompt_nested_mode()

BIN = os.path.basename(os.path.normpath(MEDIA))  # requested bin name (may include suffix)

# Validate/split: allow YYYYMMDD_## or YYYYMMDD_##_<suffix>
BIN_PATTERN = re.compile(r"^(?P<ymd>\d{8})_(?P<seq>\d{2})(?:_(?P<sfx>.+))?$")
m = BIN_PATTERN.match(BIN)
if not m:
    print(f"Note: folder name '{BIN}' is not in YYYYMMDD_##[_suffix] form. Proceeding anyway.", file=sys.stderr)
BASE_BIN = f"{m.group('ymd')}_{m.group('seq')}" if m else BIN
SUFFIX   = m.group("sfx") if m else None

# Optional: read config (for logging only)
CFG_PATH = os.getenv("CONFIG_PATH")
if not CFG_PATH:
    # Use config.json in the same directory as this script
    script_dir = Path(__file__).parent
    CFG_PATH = str(script_dir / "config.json")

CFG = {}
if not os.path.exists(CFG_PATH):
    raise SystemExit(f"Config file not found: {CFG_PATH}")

try:
    with open(CFG_PATH, "r") as f:
        CFG = json.load(f)
except Exception as e:
    raise SystemExit(f"Failed to load config file {CFG_PATH}: {e}")

def pick_user(keymap: dict) -> str:
    """Prompt user to select from keymap, similar to workflow_launcher.py"""
    print("Select user:")
    for letter in sorted(keymap.keys()):
        print(f"  [{letter}] {keymap[letter]}")
    while True:
        choice = input("Enter letter (or q to quit): ").strip().lower()
        if choice == "q":
            raise SystemExit("Aborted by user.")
        if choice in keymap:
            return keymap[choice]  # returns NAME (e.g., "ANDY")
        print("Invalid choice. Try again.")

NAME = os.getenv("NAME")
if not NAME:
    # Check if we're in interactive mode (no MEDIA provided via args/env)
    # If interactive, prompt for user selection
    keymap = CFG.get("user_keymap", {})
    if not keymap:
        raise SystemExit("NAME environment variable not set and 'user_keymap' not found in config.json. This script must be run via workflow_launcher.py or with NAME set.")
    
    # Only prompt if we're in interactive mode (no MEDIA was provided)
    if not args and not os.getenv("MEDIA"):
        NAME = pick_user(keymap)
    else:
        raise SystemExit("NAME environment variable not set. This script must be run via workflow_launcher.py")

RESOLVE_PROJECT = os.getenv("RESOLVE_PROJECT") or NAME

print("=== Resolve Auto-Import ===")
print(f"Operator:        {NAME or '(unknown)'}")
print(f"Media folder:    {MEDIA}")
print(f"Recursive:       {RECURSIVE}")
print(f"Requested bin:   {BIN}")
if m:
    print(f"  ↳ base:        {BASE_BIN}" + (f"   suffix: {SUFFIX}" if SUFFIX else ""))
print(f"Resolve project: {RESOLVE_PROJECT or '(use current project)'}")

# --------- Load Resolve API (macOS common paths) ---------
resolve_paths = CFG.get("resolve_api_paths", [
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules",
    "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Resources/Developer/Scripting/Modules",
    os.path.expanduser("~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"),
])

for p in resolve_paths:
    if os.path.exists(p) and p not in sys.path:
        sys.path.append(p)
try:
    import DaVinciResolveScript as bmd
except Exception as e:
    raise SystemExit(f"Could not import Resolve API. Add its 'Modules' path to PYTHONPATH.\n{e}")

resolve = bmd.scriptapp("Resolve")
if not resolve:
    raise SystemExit("Could not connect to DaVinci Resolve. Open Resolve and a project, then run again.")

pm = resolve.GetProjectManager()

# Load the requested project if we have a name; otherwise fall back to current
project = None
if RESOLVE_PROJECT:
    project = pm.LoadProject(RESOLVE_PROJECT)
    if not project:
        raise SystemExit(f"Could not load Resolve project '{RESOLVE_PROJECT}'. Is it spelled correctly?")
else:
    project = pm.GetCurrentProject()
    if not project:
        raise SystemExit("No project open in Resolve, and no RESOLVE_PROJECT specified.")

media_pool  = project.GetMediaPool()
media_store = resolve.GetMediaStorage()
root_bin    = media_pool.GetRootFolder()

# --------- Helpers ---------
def find_subfolder_by_name(parent, name):
    for sub in parent.GetSubFolders().values():  # dict of {id: bin_obj}
        if sub.GetName() == name:
            return sub
    return None

def get_or_create_bin_suffix_aware(parent, requested_name: str, base_name: str):
    """
    Prefer exact match (requested_name). If not found, try base_name (YYYYMMDD_##).
    If base exists and requested had a suffix, reuse the base (avoid duplicates).
    Otherwise create requested_name.
    """
    exact = find_subfolder_by_name(parent, requested_name)
    if exact:
        if requested_name != base_name:
            print(f"Using existing bin '{requested_name}' (suffix match).")
        else:
            print(f"Using existing bin '{requested_name}'.")
        return exact

    base = find_subfolder_by_name(parent, base_name)
    if base and requested_name != base_name:
        print(f"No exact bin '{requested_name}', but found base '{base_name}'. Reusing base bin.")
        return base

    created = media_pool.AddSubFolder(parent, requested_name)
    if not created:
        raise SystemExit(f"Failed to create bin '{requested_name}'.")
    print(f"Created bin '{requested_name}'.")
    return created

VIDEO = {".mov",".mp4",".mxf",".mkv",".m4v",".avi",".r3d",".braw",".ari",".hevc"}
AUDIO = {".wav",".aif",".aiff",".mp3",".m4a",".flac",".aac",".ogg",".bwf"}
SEQ   = {".dpx",".exr",".dng",".tif",".tiff",".jpg",".jpeg",".png",".bmp"}

def discover(base, recurse=True):
    base = pathlib.Path(base)
    if not base.exists():
        return []
    it = base.rglob("*") if recurse else base.glob("*")
    out = []
    for p in it:
        if p.is_file() and p.suffix.lower() in (VIDEO | AUDIO | SEQ):
            out.append(str(p.resolve()))
    out.sort()
    return out

# --------- Nested Folder Mode Functions ---------
def find_media_folders(root_path, include_root=True):
    """
    Find all directories (including root) that contain media files.
    Returns list of (folder_path, relative_path_for_bin) tuples.
    """
    root = pathlib.Path(root_path)
    folders_with_media = []
    
    # Check root folder
    if include_root:
        root_files = discover(root, recurse=False)  # Only check root level
        if root_files:
            folders_with_media.append((root, "."))
    
    # Find all subdirectories recursively
    for subdir in root.rglob("*"):
        if subdir.is_dir():
            # Check if this directory contains media files (non-recursive check)
            dir_files = discover(subdir, recurse=False)
            if dir_files:
                # Calculate relative path from root for bin naming
                try:
                    rel_path = subdir.relative_to(root)
                    folders_with_media.append((subdir, str(rel_path)))
                except ValueError:
                    # If relative path calculation fails, use absolute path
                    folders_with_media.append((subdir, str(subdir)))
    
    return folders_with_media

def process_single_folder(folder_path, bin_name, base_bin_name, media_pool, media_store, root_bin, project, recursive=True):
    """
    Process a single folder: import media and create timeline.
    Returns (success: bool, imported_count: int, timeline_name: str, error: str or None)
    """
    try:
        folder = pathlib.Path(folder_path)
        if not folder.exists():
            return False, 0, None, f"Folder does not exist: {folder_path}"
        
        # Discover media files in this folder
        paths = discover(folder, recurse=recursive)
        if not paths:
            return False, 0, None, f"No importable media found in {folder_path!r}"
        
        # Get or create bin
        target_bin = get_or_create_bin_suffix_aware(root_bin, bin_name, base_bin_name)
        media_pool.SetCurrentFolder(target_bin)
        
        # Import media
        added_items = media_store.AddItemListToMediaPool(paths) or []
        imported_count = len(added_items)
        
        if imported_count == 0:
            return False, 0, None, "Nothing new was imported"
        
        # Create timeline
        timeline_name = f"{bin_name}_assembly"
        timeline = media_pool.CreateTimelineFromClips(timeline_name, added_items)
        if not timeline:
            return False, imported_count, None, "Failed to create timeline from imported clips"
        
        project.SetCurrentTimeline(timeline)
        return True, imported_count, timeline_name, None
        
    except Exception as e:
        return False, 0, None, f"Exception: {str(e)}"

# --------- Import ---------
if not pathlib.Path(MEDIA).exists():
    raise SystemExit(f"MEDIA path not found: {MEDIA}")

if NESTED_MODE:
    # Nested folder mode: process each subdirectory separately
    print("=== Nested Folder Mode ===")
    print(f"Scanning for folders with media files in: {MEDIA}")
    
    folders_to_process = find_media_folders(MEDIA, include_root=True)
    
    if not folders_to_process:
        raise SystemExit(f"No folders containing media files found in {MEDIA!r}")
    
    print(f"Found {len(folders_to_process)} folder(s) to process.\n")
    
    results = []
    failed = []
    
    for i, (folder_path, rel_path) in enumerate(folders_to_process, 1):
        folder = pathlib.Path(folder_path)
        folder_name = folder.name
        
        # Derive bin name from relative path
        if rel_path == ".":
            bin_name = os.path.basename(os.path.normpath(MEDIA))
        else:
            # Use full path structure: replace path separators with forward slashes
            bin_name = rel_path.replace(os.sep, "/")
        
        # Parse bin name for base/suffix (use last component for pattern matching)
        last_component = os.path.basename(bin_name)
        m = BIN_PATTERN.match(last_component)
        base_bin = f"{m.group('ymd')}_{m.group('seq')}" if m else last_component
        
        print(f"[{i}/{len(folders_to_process)}] Processing: {rel_path}")
        print(f"  Folder: {folder_path}")
        print(f"  Bin:    {bin_name}")
        
        success, imported_count, timeline_name, error = process_single_folder(
            folder_path, bin_name, base_bin, media_pool, media_store, 
            root_bin, project, recursive=RECURSIVE
        )
        
        if success:
            print(f"  ✅ Imported {imported_count} item(s), created timeline: '{timeline_name}'")
            results.append((rel_path, imported_count, timeline_name))
        else:
            print(f"  ❌ Failed: {error}")
            failed.append((rel_path, error))
        print()
    
    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total folders processed: {len(folders_to_process)}")
    print(f"Successful: {len(results)}")
    print(f"Failed: {len(failed)}")
    print()
    
    if results:
        print("Successful imports:")
        total_imported = 0
        for rel_path, count, timeline in results:
            print(f"  ✅ {rel_path}: {count} item(s) → {timeline}")
            total_imported += count
        print(f"\nTotal items imported: {total_imported}")
        print()
    
    if failed:
        print("Failed folders:")
        for rel_path, error in failed:
            print(f"  ❌ {rel_path}: {error}")
        print()
        # Don't exit with error code - user can review failures

else:
    # Original single-folder mode
    target_bin = get_or_create_bin_suffix_aware(root_bin, BIN, BASE_BIN)
    media_pool.SetCurrentFolder(target_bin)
    
    paths = discover(MEDIA, RECURSIVE)
    if not paths:
        raise SystemExit(f"No importable media found in {MEDIA!r} (recursive={RECURSIVE}).")
    
    added_items = media_store.AddItemListToMediaPool(paths) or []
    imported_count = len(added_items)
    print(f"Imported {imported_count} item(s) into bin '{target_bin.GetName()}'.")
    
    if imported_count == 0:
        raise SystemExit("Nothing new was imported, so no timeline was created.")
    
    # --------- Create timeline from the newly imported clips ---------
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    # keep the visible timeline aligned with the folder/bin naming
    timeline_name = f"{target_bin.GetName()}_assembly"
    
    timeline = media_pool.CreateTimelineFromClips(timeline_name, added_items)
    if not timeline:
        raise SystemExit("Failed to create timeline from imported clips.")
    
    project.SetCurrentTimeline(timeline)
    print(f"Created timeline: '{timeline_name}' with {imported_count} clip(s) in bin '{target_bin.GetName()}'.")
