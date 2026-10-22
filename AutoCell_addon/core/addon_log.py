# -*- coding: utf-8 -*-
import os
from datetime import datetime

from addon_paths import STATE_DIR, ensure_state_dir

LOG_PATH = os.path.join(STATE_DIR, "addon.log")


def log(msg):
    line = datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "  " + str(msg)
    try:
        print("ADDON: " + str(msg))
    except Exception:
        pass
    try:
        ensure_state_dir()
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
