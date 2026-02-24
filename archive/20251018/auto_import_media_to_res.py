#!/usr/bin/env python3
# Auto import media into a bin named after the folder, then create a timeline from those clips.
# Reads environment from workflow_launcher.py / config.json:
#   CONFIG_PATH (optional), NAME, RESOLVE_PROJECT
# Usage:
#   python3 auto_import_media_to_res.py /path/to/media [--nonrecursive]
#   # or (interactive):
#   python3 auto_import_media_to_res.py

import os, sys, pathlib, datetime, json, re
from pathlib import Path

# --------- Arg / Env parsing ---------
args = [a for a in sys.argv[1:] if a != "--nonrecursive"]
RECURSIVE = "--nonrecursive" not in sys.argv

MEDIA = args[0] if args else os.getenv("MEDIA")

def prompt_media_path() -> str:
    print("No MEDIA path provided.")
    while True:
        p = input("Drag in the folder that contains the MEDIA you just copied to LACIE (or press Enter to abort): ").strip()
        if not p:
            raise SystemExit("Aborted by user (no MEDIA path).")
        if pathlib.Path(p).exists():
            return p
        print(f"Path not found: {p}")

if not MEDIA:
    MEDIA = prompt_media_path()

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

NAME = os.getenv("NAME")
if not NAME:
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

# --------- Import ---------
if not pathlib.Path(MEDIA).exists():
    raise SystemExit(f"MEDIA path not found: {MEDIA}")

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
