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
