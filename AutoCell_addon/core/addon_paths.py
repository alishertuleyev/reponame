# -*- coding: utf-8 -*-
import json
import os
import sys

CORE_DIR = os.path.dirname(os.path.abspath(__file__))
ADDON_DIR = os.path.dirname(CORE_DIR)
FEATURES_DIR = os.path.join(ADDON_DIR, "features")
STATE_DIR = os.path.join(ADDON_DIR, "state")
CONFIG_PATH = os.path.join(ADDON_DIR, "config.json")


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def autocell_root(cfg=None):
    cfg = cfg if cfg is not None else load_config()
    custom = (cfg.get("autocell_root") or "").strip().strip('"')
    if custom:
        root = os.path.abspath(custom)
        if os.path.isdir(os.path.join(root, "backend")):
            return root
        raise SystemExit("config.json: autocell_root не найден: " + root)

    sibling = os.path.abspath(os.path.join(ADDON_DIR, "..", "AutoCell"))
    if os.path.isdir(os.path.join(sibling, "backend")):
        return sibling

    if os.path.isdir(os.path.join(r"C:\AutoCell", "backend")):
        return r"C:\AutoCell"

    raise SystemExit(
        "Папка AutoCell не найдена. Пропишите путь в config.json -> autocell_root"
    )


def storage_db(root=None, cfg=None):
    root = root or autocell_root(cfg)
    return os.path.join(root, "backend", "components", "sql", "storage.db")


def ensure_state_dir():
    os.makedirs(STATE_DIR, exist_ok=True)
    return STATE_DIR


def release_core_path():
    """Remove core/ from sys.path so AutoCell cannot import addon modules by name."""
    core = os.path.normcase(os.path.abspath(CORE_DIR))
    kept = []
    for entry in sys.path:
        try:
            if entry and os.path.normcase(os.path.abspath(entry)) == core:
                continue
        except Exception:
            pass
        kept.append(entry)
    sys.path[:] = kept


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(autocell_root())
