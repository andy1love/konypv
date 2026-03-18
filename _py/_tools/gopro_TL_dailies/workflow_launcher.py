#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
GoPro Time-Lapse Workflow Launcher
Orchestrates ingest, take detection, and optional proxy generation.
Suffix-aware newest bin detection: matches YYYYMMDD_GP_## and YYYYMMDD_GP_##_<suffix>.
"""

import os
import re
import sys
import json
import subprocess
import venv
from pathlib import Path
from typing import List, Tuple, Optional

# suffix-aware: 20260207_GP_01 or 20260207_GP_01_test
BIN_PATTERN = re.compile(r"^(?P<ymd>\d{8})_GP_(?P<seq>\d{2})(?:_.*)?$")

def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)

def load_config(cfg_path: Path) -> dict:
    if not cfg_path.exists():
        die(f"Config file not found: {cfg_path}")
    with cfg_path.open() as f:
        return json.load(f)

def newest_bin(media_pool: Path) -> Optional[Path]:
    """Find newest bin folder matching YYYYMMDD_GP_## pattern."""
    if not media_pool.exists():
        return None
    candidates: List[Tuple[str, int, Path]] = []
    for p in media_pool.iterdir():
        if p.is_dir():
            m = BIN_PATTERN.match(p.name)
            if m:
                candidates.append((m.group("ymd"), int(m.group("seq")), p))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1]))  # ascending by date then seq
    return candidates[-1][2]

def confirm(prompt: str, default_yes: bool = True) -> bool:
    resp = input(prompt + (" [Y/n]: " if default_yes else " [y/N]: ")).strip().lower()
    return default_yes if resp == "" else resp in ("y", "yes")

def normalize_dragged_path(p: str) -> str:
    """Handle paths dragged/pasted into terminal that may have quotes or escaped spaces."""
    p = p.strip()
    # Strip surrounding quotes (single or double)
    if (p.startswith("'") and p.endswith("'")) or (p.startswith('"') and p.endswith('"')):
        p = p[1:-1]
    # Try as-is first
    if Path(p).exists():
        return p
    # If path starts with "/" and contains spaces (possibly escaped), try unescaping
    if p.startswith("/") and (" " in p or "\\ " in p):
        # Replace backslash-space with regular space
        unescaped = p.replace("\\ ", " ")
        if Path(unescaped).exists():
            return unescaped
    return p

def setup_venv(script_dir: Path) -> Path:
    """
    Create virtual environment if it doesn't exist, and ensure Pillow is installed.
    Returns absolute path to venv's Python interpreter.
    """
    venv_dir = script_dir / "venv"
    venv_python = venv_dir / "bin" / "python3"
    
    # Create venv if it doesn't exist
    if not venv_dir.exists():
        print(f"Creating virtual environment: {venv_dir}")
        venv.create(venv_dir, with_pip=True)
    
    # Ensure venv_python exists
    if not venv_python.exists():
        die(f"Virtual environment Python not found at {venv_python}")
    
    # Check if exifread is installed
    try:
        result = subprocess.run(
            [str(venv_python.resolve()), "-c", "import exifread; print(exifread.__version__)"],
            capture_output=True,
            text=True,
            check=True
        )
        print(f"exifread already installed (version {result.stdout.strip()})")
    except (subprocess.CalledProcessError, FileNotFoundError):
        # exifread not installed, install it
        print("Installing exifread in virtual environment...")
        try:
            subprocess.run(
                [str(venv_python.resolve()), "-m", "pip", "install", "exifread"],
                check=True
            )
            print("✅ exifread installed successfully")
        except subprocess.CalledProcessError as e:
            die(f"Failed to install exifread: {e}")
    
    return venv_python.resolve()

def main():
    # 1) Load config (allow custom path as argv[1], or use default in same directory)
    if len(sys.argv) > 1:
        cfg_path = Path(sys.argv[1])
    else:
        # Use gopro_config.json in the same directory as this script
        script_dir = Path(__file__).parent
        cfg_path = script_dir / "gopro_config.json"
    cfg = load_config(cfg_path)

    if "GP_JPGSEQ_POOL_ROOT" not in cfg:
        die("Config missing 'GP_JPGSEQ_POOL_ROOT' key.")
    if "GP_DAILIES_ROLL" not in cfg:
        die("Config missing 'GP_DAILIES_ROLL' key.")
    if "GP_PROXY_POOL" not in cfg:
        die("Config missing 'GP_PROXY_POOL' key.")

    def resolve_dailies_roll(cfg_val) -> Path:
        """Resolve GP_DAILIES_ROLL from a string or list of candidate paths."""
        if isinstance(cfg_val, str):
            return Path(cfg_val)
        if isinstance(cfg_val, list):
            found = [Path(p) for p in cfg_val if Path(p).exists()]
            if len(found) == 1:
                return found[0]
            if len(found) > 1:
                print("Multiple SD cards detected:")
                for i, p in enumerate(found, 1):
                    print(f"  [{i}] {p}")
                while True:
                    choice = input("Select SD card number: ").strip()
                    if choice.isdigit() and 1 <= int(choice) <= len(found):
                        return found[int(choice) - 1]
                    print("Invalid choice. Try again.")
            # None found yet — return first candidate (will fail at mount check later)
            return Path(cfg_val[0])
        die(f"GP_DAILIES_ROLL has unexpected type: {type(cfg_val)}")
        return Path()  # unreachable

    # Setup virtual environment and get Python interpreter
    script_dir = Path(__file__).parent
    python_exec = str(setup_venv(script_dir))
    
    gp_pool_root = Path(cfg["GP_JPGSEQ_POOL_ROOT"])
    gp_proxy_pool = Path(cfg["GP_PROXY_POOL"])
    gp_dailies_roll = resolve_dailies_roll(cfg["GP_DAILIES_ROLL"])

    scripts = cfg.get("scripts")
    if not scripts:
        die("Missing 'scripts' entry in config.json")
    if "ingest" not in scripts:
        die("Missing 'scripts.ingest' entry in config.json")
    if "take_maker" not in scripts:
        die("Missing 'scripts.take_maker' entry in config.json")
    if "proxy_maker" not in scripts:
        die("Missing 'scripts.proxy_maker' entry in config.json")

    ingest_script = Path(scripts["ingest"])
    take_maker_script = Path(scripts["take_maker"])
    proxy_maker_script = Path(scripts.get("proxy_maker")) if scripts.get("proxy_maker") else None
    
    # Resolve script paths relative to config file location or absolute
    if not ingest_script.is_absolute():
        ingest_script = cfg_path.parent / ingest_script
    if not take_maker_script.is_absolute():
        take_maker_script = cfg_path.parent / take_maker_script
    if proxy_maker_script and not proxy_maker_script.is_absolute():
        proxy_maker_script = cfg_path.parent / proxy_maker_script
    
    if not ingest_script.exists():
        die(f"Ingest script not found at {ingest_script}")
    if not take_maker_script.exists():
        die(f"Take maker script not found at {take_maker_script}")

    print(f"\n=== GoPro Time-Lapse Workflow ===")
    print(f"GP_JPGSEQ_POOL_ROOT: {gp_pool_root}")
    print(f"GP_PROXY_POOL:       {gp_proxy_pool}")
    print(f"GP_DAILIES_ROLL:     {gp_dailies_roll}")

    # Ensure GP_JPGSEQ_POOL_ROOT exists
    if not gp_pool_root.exists():
        print(f"Creating GP_JPGSEQ_POOL_ROOT: {gp_pool_root}")
        gp_pool_root.mkdir(parents=True, exist_ok=True)
    
    # Ensure GP_PROXY_POOL exists
    if not gp_proxy_pool.exists():
        print(f"Creating GP_PROXY_POOL: {gp_proxy_pool}")
        gp_proxy_pool.mkdir(parents=True, exist_ok=True)

    # 2) Shared environment for child scripts
    env = os.environ.copy()
    env["CONFIG_PATH"] = str(cfg_path)
    env["GP_JPGSEQ_POOL_ROOT"] = str(gp_pool_root)
    env["GP_PROXY_POOL"] = str(gp_proxy_pool)
    env["GP_DAILIES_ROLL"] = str(gp_dailies_roll)

    # 4) Ask whether to run ingest first
    run_ingest_first = confirm("\nRun ingest (copy JPGs from SD card to pool)?", default_yes=True)

    if run_ingest_first:
        ingest_cmd = [python_exec, str(ingest_script)]
        print(f"\n— Running ingest: {' '.join(ingest_cmd)}")
        try:
            subprocess.run(ingest_cmd, check=True, env=env)
        except subprocess.CalledProcessError as e:
            die(f"Ingest failed with exit code {e.returncode}")
        print("\n✅ Ingest finished.")

    # 5) Determine folder to process (suffix-aware)
    latest = newest_bin(gp_pool_root)
    if latest:
        print(f"\nLatest bin detected: {latest.name}")
        use_latest = confirm("Use this folder for take detection?", default_yes=True)
        if not use_latest:
            manual = input("Drag in the folder path you want to process: ").strip()
            if not manual:
                die("No folder provided.")
            manual = normalize_dragged_path(manual)
            latest = Path(manual)
            if not latest.exists():
                die(f"Folder not found: {latest}")
    else:
        print(f"\nNo YYYYMMDD_GP_##[_suffix] folders found in {gp_pool_root}.")
        manual = input("Enter absolute folder path to process (or press Enter to abort): ").strip()
        if not manual:
            die("Aborted (no folder to process).")
        manual = normalize_dragged_path(manual)
        latest = Path(manual)
        if not latest.exists():
            die(f"Folder not found: {latest}")

    env["GP_BIN_FOLDER"] = str(latest)

    # 6) Run take_maker
    take_maker_cmd = [python_exec, str(take_maker_script)]
    print(f"\n— Running take_maker: {' '.join(take_maker_cmd)}")
    try:
        subprocess.run(take_maker_cmd, check=True, env=env)
    except subprocess.CalledProcessError as e:
        die(f"Take maker failed with exit code {e.returncode}")
    print("\n✅ Take detection finished.")

    # 7) Optionally run proxy maker
    if proxy_maker_script and proxy_maker_script.exists():
        run_proxy = confirm("\nGenerate proxies?", default_yes=True)
        if run_proxy:
            proxy_cmd = [python_exec, str(proxy_maker_script)]
            print(f"\n— Running proxy maker: {' '.join(proxy_cmd)}")
            try:
                subprocess.run(proxy_cmd, check=True, env=env)
            except subprocess.CalledProcessError as e:
                die(f"Proxy maker failed with exit code {e.returncode}")
            print("\n✅ Proxy generation finished.")
    else:
        print("\n(Proxy maker script not configured or not found. Skipping.)")

    # 8) Optionally run SD card wipe
    sdcard_wipe_script = cfg_path.parent / "sdcard_wipe.py"
    if sdcard_wipe_script.exists():
        run_wipe = confirm("\nVerify & wipe SD card?", default_yes=False)
        if run_wipe:
            wipe_cmd = [python_exec, str(sdcard_wipe_script)]
            print(f"\n— Running SD card wipe: {' '.join(wipe_cmd)}")
            try:
                subprocess.run(wipe_cmd, check=True, env=env)
            except subprocess.CalledProcessError as e:
                die(f"SD card wipe failed with exit code {e.returncode}")
            print("\n✅ SD card wipe finished.")

    print("\n🎬 Pipeline complete.")

if __name__ == "__main__":
    main()
