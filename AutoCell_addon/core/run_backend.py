# -*- coding: utf-8 -*-
import os
import runpy
import sys

CORE_DIR = os.path.dirname(os.path.abspath(__file__))
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

from addon_loader import install_backend
from addon_log import log
from addon_paths import autocell_root, load_config, release_core_path
import addon_storage  # noqa: F401  cache before AutoCell imports


def _host_main():
    cfg = load_config()
    root = autocell_root(cfg)
    backend = os.path.join(root, "backend")
    main_py = os.path.join(backend, "main.py")
    if not os.path.isfile(main_py):
        raise SystemExit("не найден backend\\main.py в " + root)
    os.chdir(backend)
    if backend not in sys.path:
        sys.path.insert(0, backend)
    return main_py


if __name__ == "__main__":
    main_py = None
    try:
        main_py = _host_main()
        log("run_backend cwd=" + os.getcwd())
        install_backend()
    except SystemExit:
        if not main_py:
            raise
        log("addon init остановлен. Стартую исходный main.py.")
    except BaseException as exc:
        log("addon init ошибка, стартую исходный main.py: %r" % (exc,))
        if not main_py:
            raise SystemExit(1)
    # Addon names must not shadow AutoCell modules (storage, log, paths, ...).
    release_core_path()
    runpy.run_path(main_py, run_name="__main__")
