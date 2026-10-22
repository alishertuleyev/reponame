# -*- coding: utf-8 -*-
import importlib.util
import os
import sys
import threading
import webbrowser

CORE_DIR = os.path.dirname(os.path.abspath(__file__))
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

from addon_loader import install_frontend
from addon_log import log
from addon_paths import autocell_root, load_config, release_core_path
import addon_storage  # noqa: F401


def _load_host():
    cfg = load_config()
    root = autocell_root(cfg)
    frontend = os.path.join(root, "frontend")
    app_py = os.path.join(frontend, "app.py")
    if not os.path.isfile(app_py):
        raise SystemExit("не найден frontend\\app.py в " + root)
    os.chdir(frontend)
    if frontend not in sys.path:
        sys.path.insert(0, frontend)
    release_core_path()
    spec = importlib.util.spec_from_file_location("autocell_frontend_app", app_py)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["autocell_frontend_app"] = mod
    spec.loader.exec_module(mod)
    return mod


def open_browser():
    try:
        webbrowser.open_new("http://127.0.0.1:5000/storage")
    except Exception:
        pass


if __name__ == "__main__":
    try:
        mod = _load_host()
    except SystemExit:
        raise
    except BaseException as exc:
        log("frontend host не загрузился: %r" % (exc,))
        raise SystemExit(1)
    try:
        log("run_frontend cwd=" + os.getcwd())
        install_frontend(mod.app)
    except BaseException as exc:
        log("addon frontend init ошибка, исходный frontend всё равно стартует: %r" % (exc,))
    threading.Timer(1.0, open_browser).start()
    mod.app.run(host="0.0.0.0", port=5000, debug=False)
