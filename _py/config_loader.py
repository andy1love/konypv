import json
import os
from pathlib import Path


def load_config(cfg_path=None) -> dict:
    """Load config.json and derive ROOT-based paths for any keys not explicitly set."""
    if cfg_path is None:
        env_path = os.getenv("CONFIG_PATH")
        cfg_path = Path(env_path) if env_path else Path(__file__).parent / "config.json"

    cfg_path = Path(cfg_path)
    if not cfg_path.exists():
        raise SystemExit(f"Config file not found: {cfg_path}")

    with cfg_path.open(encoding="utf-8") as f:
        cfg = json.load(f)

    root = cfg.get("ROOT")
    if root:
        root = Path(root)
        cfg.setdefault("repo_root",       str(root / "_scripts"))
        cfg.setdefault("MEDIA_POOL_ROOT", str(root / "MEDIA_POOL"))
        cfg.setdefault("PROXY_POOL_ROOT", str(root / "PROXY_POOL"))
        if "scripts" not in cfg:
            cfg["scripts"] = {}
        cfg["scripts"].setdefault("ingest", str(root / "_scripts/_py/sdcard_to_lacie.py"))
        cfg["scripts"].setdefault("import", str(root / "_scripts/_py/auto_import_media_to_res.py"))

    return cfg


def resolve_dailies_roll(cfg: dict) -> Path:
    """Decide which dailies roll to use.

    Order of precedence:
      1. DAILIES_ROLL env var (explicit override).
      2. If any SECONDARY_DAILIES_ROLL entries are mounted, prompt the user
         to pick one; blank input falls back to DEFAULT_DAILIES_ROLL.
      3. DEFAULT_DAILIES_ROLL.
    """
    env_val = os.getenv("DAILIES_ROLL")
    if env_val:
        return Path(env_val)

    default_val = cfg.get("DEFAULT_DAILIES_ROLL")
    if not default_val:
        raise SystemExit("ERROR: DEFAULT_DAILIES_ROLL not found in config.")
    default_roll = Path(default_val)

    secondary = cfg.get("SECONDARY_DAILIES_ROLL") or []
    if isinstance(secondary, str):
        secondary = [secondary]
    mounted = [Path(p) for p in secondary if Path(p).exists()]
    if not mounted:
        return default_roll

    print("\nMounted SECONDARY_DAILIES_ROLL(s) detected:")
    for i, p in enumerate(mounted, 1):
        print(f"  [{i}] {p}")
    print(f"  [Enter] use DEFAULT_DAILIES_ROLL ({default_roll})")
    while True:
        choice = input("Select number, or press Enter for default: ").strip()
        if choice == "":
            return default_roll
        if choice.isdigit() and 1 <= int(choice) <= len(mounted):
            return mounted[int(choice) - 1]
        print("Invalid choice. Try again.")
