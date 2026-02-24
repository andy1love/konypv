#!/usr/bin/env python3
import json
import os
import re
import sys
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional

# ------------------------ Utils ------------------------

def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)

def die(msg: str, code: int = 1):
    eprint(f"[ERROR] {msg}")
    sys.exit(code)

def which(cmd: str) -> Optional[str]:
    from shutil import which as _which
    return _which(cmd)

def run(cmd: List[str], log_path: Optional[Path] = None) -> int:
    """Run a command streaming output; tee to log if provided."""
    eprint(" ".join([f"'{c}'" if " " in c else c for c in cmd]))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, text=True)
    logf = None
    try:
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            logf = log_path.open("w", encoding="utf-8", newline="")
        for line in proc.stdout:
            print(line, end="")
            if logf:
                logf.write(line)
        return proc.wait()
    finally:
        if logf:
            logf.close()

def confirm(prompt: str, default_yes: bool = False) -> bool:
    suffix = " [Y/n]: " if default_yes else " [y/N]: "
    ans = input(prompt + suffix).strip().lower()
    if ans == "" and default_yes:
        return True
    return ans in ("y", "yes")

def banner(title: str, pairs: List[Tuple[Path, Path]]):
    print("\n" + "─" * 68)
    print(f"{title}")
    for src, dst in pairs:
        print(f"  SRC: {src}")
        print(f"  DST: {dst}")
    print("─" * 68 + "\n")

def ensure_mounted(p: Path, label: str):
    # Minimal sanity: if under /Volumes, ensure drive exists; ensure parent dirs for non-existent paths.
    if str(p).startswith("/Volumes/"):
        parts = Path(p).resolve().parts
        if len(parts) >= 3:
            drive_path = Path("/").joinpath(*parts[:3])
            if not drive_path.exists():
                die(f"{label} volume not mounted: {drive_path}")
    p.parent.mkdir(parents=True, exist_ok=True)

def write_excludes_tempfile(excludes: List[str]) -> Path:
    tf = tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8")
    with tf as f:
        for pat in excludes:
            f.write(pat + "\n")
    return Path(tf.name)

def log_path_for(dest_root: Path, name: str, label: str) -> Path:
    rep = dest_root / "_reports" / "sync_logs"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return rep / f"{ts}_{name}_{label}.log"

def make_lock(root: Path) -> Path:
    return root / ".sync.lock"

class _LockCtx:
    def __init__(self, root: Path):
        self.root = root
    def __enter__(self):
        self.root.mkdir(parents=True, exist_ok=True)
        lock = make_lock(self.root)
        if lock.exists():
            die(f"Lock file exists: {lock}\nAnother sync may be running. If not, remove the lock and retry.")
        lock.write_text(f"{os.getpid()}\n{datetime.now().isoformat()}\n", encoding="utf-8")
        return self
    def __exit__(self, exc_type, exc, tb):
        try:
            make_lock(self.root).unlink(missing_ok=True)
        except Exception:
            pass

def with_lock(root: Path):
    return _LockCtx(root)

# ------------------------ rsync pick/version ------------------------

def pick_rsync_bin() -> str:
    # Prefer Homebrew rsync 3.x if available; otherwise system rsync (2.6.9 on macOS).
    brew_rsync = "/opt/homebrew/bin/rsync"
    if os.path.exists(brew_rsync):
        return brew_rsync
    return which("rsync") or "rsync"

RSYNC_BIN = pick_rsync_bin()

def rsync_version_tuple(rsync_bin: str) -> Tuple[int, int]:
    try:
        out = subprocess.check_output([rsync_bin, "--version"], text=True)
        m = re.search(r"version\s+(\d+)\.(\d+)", out)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return (2, 6)

# ------------------------ Config ------------------------

class Config:
    def __init__(self, path: Path):
        with path.open("r", encoding="utf-8") as f:
            self.data = json.load(f)

        for key in ["MEDIA_POOL_ROOT", "PROXY_POOL_ROOT", "user_keymap", "user_dest_roots"]:
            if key not in self.data:
                die(f"Missing '{key}' in config JSON: {path}")

        self.MEDIA_POOL_ROOT = Path(self.data["MEDIA_POOL_ROOT"])
        self.PROXY_POOL_ROOT = Path(self.data["PROXY_POOL_ROOT"])
        self.user_keymap = self.data["user_keymap"]
        self.user_dest_roots = self.data["user_dest_roots"]
        self.excludes = self.data.get("excludes", [])
        self.backsync_globs = self.data.get("backsync_globs", ["*.mp4", "*.MP4"])

        raw_flags = self.data.get("rsync", {}).get("flags", None)
        if raw_flags is None:
            # Choose sensible defaults based on rsync version if config omits flags
            major, _ = rsync_version_tuple(RSYNC_BIN)
            if major >= 3:
                self.rsync_flags = ["-a", "-AX", "--partial", "--append-verify", "--human-readable", "--info=progress2", "--protect-args"]
            else:
                self.rsync_flags = ["-r", "-E", "--extended-attributes", "--partial", "--append", "--human-readable", "--progress"]
        else:
            # Use provided flags; if empty list, add minimal safe defaults for system rsync
            if len(raw_flags) == 0:
                self.rsync_flags = ["-r", "--progress"]
            else:
                self.rsync_flags = raw_flags

    def destination_roots_for(self, name: str) -> Tuple[Path, Path]:
        if name not in self.user_dest_roots:
            die(f"No destination root configured for user '{name}' in 'user_dest_roots'.")
        root = Path(self.user_dest_roots[name])
        return (root / "MEDIA_POOL", root / "PROXY_POOL")

# ------------------------ rsync wrappers ------------------------

def rsync_copy(src: Path, dst: Path, excludes_file: Path, flags: List[str], log_file: Path) -> int:
    src_arg = str(src) if str(src).endswith("/") else str(src) + "/"
    dst_arg = str(dst) if str(dst).endswith("/") else str(dst) + "/"
    cmd = [RSYNC_BIN] + flags + ["--exclude-from", str(excludes_file), src_arg, dst_arg]
    return run(cmd, log_file)

def rsync_list_missing_from_src_mp4_only(dst: Path, src: Path, excludes_file: Path, flags: List[str], backsync_globs: List[str]) -> Tuple[int, List[str]]:
    """Dry-run DEST -> SOURCE to list only MP4 files missing on SOURCE (files only, no dirs)."""
    src_arg = str(src) if str(src).endswith("/") else str(src) + "/"
    dst_arg = str(dst) if str(dst).endswith("/") else str(dst) + "/"

    # Strip noisy flags (no progress/verbose for parsing)
    noisy = {"--progress", "--info=progress2", "-v", "--verbose"}
    clean_flags = [f for f in flags if f not in noisy]

    # Include/Exclude: traverse dirs, include mp4 globs, exclude everything else
    include_args = ["--include", "*/"]
    for g in backsync_globs:
        include_args += ["--include", g]
    include_args += ["--exclude", "*"]

    # Itemized changes so we can filter to files; prune empty dirs
    cmd = [
        RSYNC_BIN, "-an", "-i","--ignore-existing", "--prune-empty-dirs",
        "--out-format=%i %n", "--exclude-from", str(excludes_file)
    ] + include_args + clean_flags + [dst_arg, src_arg]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    candidates: List[str] = []
    for line in proc.stdout:
        line = line.rstrip("\n")
        if not line:
            continue
        # itemized format: first field like ">f++++++++" or ".d..t......"
        # second char is the file-type code: 'f' = file, 'd' = dir, 'L' = symlink, etc.
        # separate the 11-char code from the path
        if " " not in line:
            continue
        code, path = line.split(" ", 1)
        if len(code) >= 2 and code[1] == "f":
            # It's a file; safe to treat as missing-on-source
            candidates.append(path)
    rc = proc.wait()
    if rc != 0:
        return rc, []
    # Final guard: drop any trailing-slash items just in case
    candidates = [p for p in candidates if not p.endswith("/")]
    return 0, candidates

def rsync_copy_missing_mp4s_to_src(dst: Path, src: Path, excludes_file: Path, flags: List[str], backsync_globs: List[str], log_file: Path) -> int:
    """Copy from DEST -> SOURCE only for MP4s missing on SOURCE."""
    src_arg = str(src) if str(src).endswith("/") else str(src) + "/"
    dst_arg = str(dst) if str(dst).endswith("/") else str(dst) + "/"

    include_args = ["--include", "*/"]
    for g in backsync_globs:
        include_args += ["--include", g]
    include_args += ["--exclude", "*"]

    cmd = [RSYNC_BIN] + flags + ["--ignore-existing", "--exclude-from", str(excludes_file)]
    cmd += include_args + [dst_arg, src_arg]
    return run(cmd, log_file)

# ------------------------ Interaction ------------------------

def choose_user(cfg: Config) -> str:
    print("Select user:")
    for k in sorted(cfg.user_keymap.keys()):
        print(f"  [{k}] {cfg.user_keymap[k]}")
    choice = input("Enter letter (or q to quit): ").strip().lower()
    if choice == "q":
        sys.exit(0)
    if choice not in cfg.user_keymap:
        die(f"Invalid choice '{choice}'.")
    return cfg.user_keymap[choice]

def choose_menu(name: str) -> int:
    print("\nWhat do you want to sync?")
    print(f"  [1] {name}'s MEDIA only")
    print(f"  [2] {name}'s PROXY only")
    print(f"  [3] {name}'s MEDIA & PROXY")
    print(f"  [4] ALL users' MEDIA (entire MEDIA_POOL_ROOT) → {name}'s destination")
    print(f"  [5] ALL users' PROXY (entire PROXY_POOL_ROOT) → {name}'s destination")
    print("  [6] Exit")
    ans = input("Enter number: ").strip()
    if not ans.isdigit():
        die("Please enter a number 1-6.")
    v = int(ans)
    if v < 1 or v > 6:
        die("Please enter a number 1-6.")
    return v

# ------------------------ Sync flow ------------------------

def sync_pair_forward_then_optional_back(cfg: Config, name: str, src: Path, dst: Path, excludes_file: Path, flags: List[str], label: str):
    """Forward sync SRC -> DST, then MP4-only back-sync prompt."""
    ensure_mounted(src, "Source")
    ensure_mounted(dst, "Destination")
    dst.mkdir(parents=True, exist_ok=True)

    log_fwd = log_path_for(dst if label.endswith("_all") else dst.parent, name, f"{label}_forward")
    banner(f"Forward sync: {label}", [(src, dst)])
    rc = rsync_copy(src, dst, excludes_file, flags, log_fwd)
    if rc != 0:
        eprint(f"[WARN] rsync forward exited with code {rc}. See log: {log_fwd}")

    # MP4-only back-sync detection
    print("\nScanning destination for MP4 files missing on source (dry-run)…")
    rc2, missing = rsync_list_missing_from_src_mp4_only(dst, src, excludes_file, flags, cfg.backsync_globs)
    if rc2 != 0:
        eprint(f"[WARN] rsync dry-run (dest→src) exited with code {rc2}; skipping back-sync detection.")
        missing = []

    if missing:
        print(f"Found {len(missing)} MP4 file(s) present only on DEST. Example(s):")
        for i, m in enumerate(missing[:10], 1):
            print(f"  {i}. {m}")
        if len(missing) > 10:
            print(f"  … (+{len(missing)-10} more)")
        if confirm("Back-sync DEST-only MP4s to SOURCE?", default_yes=False):
            log_back = log_path_for(dst if label.endswith("_all") else dst.parent, name, f"{label}_backsync_mp4")
            print("\nBack-syncing MP4s DEST → SOURCE…")
            rc3 = rsync_copy_missing_mp4s_to_src(dst, src, excludes_file, flags, cfg.backsync_globs, log_back)
            if rc3 != 0:
                eprint(f"[WARN] rsync back-sync exited with code {rc3}. See log: {log_back}")
        else:
            print("Skipped back-sync.")
    else:
        print("No DEST-only MP4s found. Back-sync not needed.")

# ------------------------ Main ------------------------

def main():
    if which("rsync") is None:
        die("rsync not found. Install or ensure it is on PATH.")
    # Auto-load config.json beside this script
    script_dir = Path(__file__).resolve().parent
    config_path = script_dir / "config.json"
    if not config_path.exists():
        die(f"Config file not found: {config_path}")
    cfg = Config(config_path)

    name = choose_user(cfg)
    dest_media_root, dest_proxy_root = cfg.destination_roots_for(name)

    excludes_file = write_excludes_tempfile(cfg.excludes)
    try:
        mode = choose_menu(name)
        if mode == 6:
            return

        pairs = []  # (src, dst, label)
        if mode in (1, 3):
            pairs.append((cfg.MEDIA_POOL_ROOT / name, dest_media_root / name, "MEDIA_user"))
        if mode in (2, 3):
            pairs.append((cfg.PROXY_POOL_ROOT / name, dest_proxy_root / name, "PROXY_user"))
        if mode == 4:
            pairs.append((cfg.MEDIA_POOL_ROOT, dest_media_root, "MEDIA_all"))
        if mode == 5:
            pairs.append((cfg.PROXY_POOL_ROOT, dest_proxy_root, "PROXY_all"))

        # Lock on the top pool roots involved
        locks = set()
        for _, dst, label in pairs:
            top = dst if label.endswith("_all") else dst.parent
            locks.add(top)

        lock_ctxs = [with_lock(root) for root in locks]
        for ctx in lock_ctxs:
            ctx.__enter__()
        try:
            for src, dst, label in pairs:
                sync_pair_forward_then_optional_back(cfg, name, src, dst, excludes_file, cfg.rsync_flags, label)
        finally:
            for ctx in reversed(lock_ctxs):
                ctx.__exit__(None, None, None)

        print("\n✅ Done.")
    finally:
        try:
            os.unlink(excludes_file)
        except Exception:
            pass

if __name__ == "__main__":
    main()