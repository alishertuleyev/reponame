# -*- coding: utf-8 -*-
import builtins
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "core")
if CORE not in sys.path:
    sys.path.insert(0, CORE)

import addon_loader
import addon_log
import addon_paths
import addon_storage
import cli


def _snap():
    return {
        "backend": {
            "name": "AutoCellBackend",
            "Application": r"C:\AutoCell\venv\Scripts\python.exe",
            "AppDirectory": r"C:\AutoCell\backend",
            "AppParameters": r"C:\AutoCell\backend\main.py",
        },
        "frontend": {
            "name": "AutoCellFrontend",
            "Application": r"C:\AutoCell\venv\Scripts\python.exe",
            "AppDirectory": r"C:\AutoCell\frontend",
            "AppParameters": r"C:\AutoCell\frontend\app.py",
        },
    }


class ServiceSafetyTests(unittest.TestCase):
    def setUp(self):
        self.saved = {
            "autocell_root": cli.autocell_root,
            "find_nssm": cli.find_nssm,
            "snapshot": cli.snapshot,
            "nssm_set": cli.nssm_set,
            "service_state": cli.service_state,
            "BACKUP": cli.BACKUP,
            "call": cli.subprocess.call,
        }
        self.sets = []
        self.tmp = tempfile.mkdtemp()
        root = os.path.join(self.tmp, "AutoCell")
        os.makedirs(os.path.join(root, "backend"))
        os.makedirs(os.path.join(root, "frontend"))
        open(os.path.join(root, "backend", "main.py"), "w", encoding="utf-8").close()
        open(os.path.join(root, "frontend", "app.py"), "w", encoding="utf-8").close()
        self.root = root
        cli.BACKUP = os.path.join(self.tmp, "nssm_backup.json")
        cli.autocell_root = lambda cfg=None: root
        cli.find_nssm = lambda *a, **k: r"C:\AutoCell\bin\nssm.exe"
        cli.service_state = lambda name: "RUNNING"
        cli.nssm_set = lambda nssm, service, key, value: self.sets.append((service, key, value))

        def forbid_control(*args, **kwargs):
            raise AssertionError("service control was called: %s %s" % (args, kwargs))

        cli.subprocess.call = forbid_control
        if CORE not in sys.path:
            sys.path.insert(0, CORE)

    def tearDown(self):
        cli.autocell_root = self.saved["autocell_root"]
        cli.find_nssm = self.saved["find_nssm"]
        cli.snapshot = self.saved["snapshot"]
        cli.nssm_set = self.saved["nssm_set"]
        cli.service_state = self.saved["service_state"]
        cli.BACKUP = self.saved["BACKUP"]
        cli.subprocess.call = self.saved["call"]
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_stop_pending_is_not_stopped(self):
        text = "\n".join([
            "SERVICE_NAME: AutoCellBackend",
            "        STATE              : 3  STOP_PENDING",
        ])
        self.assertEqual(cli.parse_sc_query(text), "STOP_PENDING")
        self.assertEqual(
            cli.parse_sc_query("        STATE              : 1  STOPPED"),
            "STOPPED",
        )
        self.assertEqual(
            cli.parse_sc_query("        STATE              : 4  RUNNING"),
            "RUNNING",
        )
        self.assertEqual(cli.parse_sc_query("no state here"), "UNKNOWN")

    def test_install_only_changes_appparameters(self):
        cli.snapshot = lambda *a, **k: _snap()
        cli.cmd_install()
        keys = [item[1] for item in self.sets]
        blob = " ".join(item[2] for item in self.sets)
        self.assertEqual(keys, ["AppParameters", "AppParameters"])
        self.assertIn("run_backend.py", blob)
        self.assertIn("run_frontend.py", blob)
        self.assertTrue(os.path.isfile(cli.BACKUP))

    def test_broken_nssm_answer_does_not_touch_service(self):
        cli.snapshot = lambda *a, **k: {
            "backend": {
                "name": "AutoCellBackend",
                "Application": "python",
                "AppDirectory": "backend",
                "AppParameters": "main.py",
            },
            "frontend": {
                "name": "AutoCellFrontend",
                "Application": "python",
                "AppDirectory": "frontend",
                "AppParameters": "app.py",
            },
        }
        with self.assertRaises(SystemExit):
            cli.cmd_install()
        self.assertEqual(self.sets, [])
        self.assertFalse(os.path.isfile(cli.BACKUP))

    def test_remove_without_backup_does_not_rewrite_application(self):
        cli.cmd_remove()
        keys = [item[1] for item in self.sets]
        blob = " ".join(item[2] for item in self.sets)
        self.assertEqual(keys, ["AppParameters", "AppParameters"])
        self.assertIn("main.py", blob)
        self.assertIn("app.py", blob)
        self.assertNotIn("run_backend.py", blob)

    def test_cli_has_no_start_or_stop_helper(self):
        with open(cli.__file__, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("stop_all", text)
        self.assertNotIn("start_all", text)
        self.assertNotIn("start_if_down", text)
        self.assertNotIn("nssm_cmd", text)


class EntryBlockTests(unittest.TestCase):
    def setUp(self):
        self.real_import = builtins.__import__
        if CORE not in sys.path:
            sys.path.insert(0, CORE)
        import importlib.util
        path = os.path.join(ROOT, "features", "entry_block", "backend.py")
        spec = importlib.util.spec_from_file_location("entry_block_backend_under_test", path)
        self.eb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.eb)
        self.logs = []
        self.ctx = {
            "config": {
                "entry_block": {
                    "block_types": [1, 5],
                    "waiting_index": {"1": 20, "2": 46},
                    "outfeed_index": {"1": 4, "2": 6},
                    "asrs1_cells": [1, 93],
                    "asrs2_cells": [94, 186],
                }
            },
            "db_path": ":memory:",
            "log": self.logs.append,
        }

    def tearDown(self):
        builtins.__import__ = self.real_import
        mod = sys.modules.get("addon_feature_entry_block_backend")
        if mod is not None:
            mod._hooked = False
            mod._busy = False
        self.eb._hooked = False
        self.eb._busy = False
        for name in ("components", "components.plc", "components.plc.plc_maping", "components.auto_mode"):
            sys.modules.pop(name, None)

    def test_decide_type(self):
        types = [1, 5]
        self.assertEqual(self.eb.decide_type(1, True, 0, True, types), 2)
        self.assertEqual(self.eb.decide_type(1, True, 0, False, types), 0)
        self.assertEqual(self.eb.decide_type(1, True, 0, None, types), 1)
        self.assertEqual(self.eb.decide_type(1, True, 3, True, types), 1)
        self.assertEqual(self.eb.decide_type(1, False, 0, True, types), 1)
        self.assertEqual(self.eb.decide_type(1, None, 0, True, types), 1)
        self.assertEqual(self.eb.decide_type(5, True, 0, True, types), 2)
        self.assertEqual(self.eb.decide_type(2, True, 0, False, types), 2)
        self.assertEqual(self.eb.decide_type(6, True, 0, False, types), 6)
        self.assertEqual(self.eb.decide_type(9, True, 0, False, types), 9)
        self.assertEqual(self.eb.decide_type("1", True, 0, True, types), 2)
        self.assertIsNone(self.eb.decide_type(None, True, 0, True, types))

    def test_write_wrapper_calls_original_once(self):
        def boom(*args, **kwargs):
            raise RuntimeError("plc read failed")

        self.eb.adjust = boom
        calls = []

        def orig(value):
            calls.append(value)
            return "kept"

        wrapped = self.eb._wrap_write(orig, 1, self.ctx)
        self.assertEqual(wrapped(1), "kept")
        self.assertEqual(calls, [1])

    def test_block_only_when_waiting_and_empty(self):
        actions = [0] * 50
        actions[20] = 1
        actions[4] = 0
        self._install_fake_plc(actions)
        self.eb.count_empty_cells = lambda *a, **k: 0
        calls = []

        def orig(value):
            calls.append(value)
            return value

        wrapped = self.eb._wrap_write(orig, 1, self.ctx)
        self.assertEqual(wrapped(1), 2)
        self.assertEqual(calls, [2])

        actions[20] = 0
        calls.clear()
        wrapped_running = self.eb._wrap_write(orig, 1, self.ctx)
        self.assertEqual(wrapped_running(1), 1)
        self.assertEqual(calls, [1])

    def test_install_does_not_import_plc(self):
        saved = addon_loader.autocell_root
        addon_loader.autocell_root = lambda cfg=None: r"C:\AutoCell"
        try:
            before = set(sys.modules)
            addon_loader.install_backend()
            added = set(sys.modules) - before
            bad = [name for name in added if "plc" in name or name.endswith("auto_mode")]
            self.assertEqual(bad, [])
            self.assertFalse(any(
                os.path.abspath(p) == os.path.abspath(CORE) for p in sys.path if p
            ))
        finally:
            addon_loader.autocell_root = saved

    def test_feature_systemexit_does_not_escape(self):
        def boom():
            raise SystemExit(7)

        self.assertFalse(addon_loader._call_feature("backend", "boom", boom))

    def test_only_entry_block_is_enabled(self):
        self.assertEqual(addon_loader.enabled_feature_names(), ["entry_block"])
        cfg = {"features": {"signal_watch": True, "live_sync": True, "plc_wait": True, "entry_block": True}}
        self.assertEqual(addon_loader.enabled_feature_names(cfg), ["entry_block"])
        shipped = [
            name for name in os.listdir(os.path.join(ROOT, "features"))
            if not name.startswith(".")
        ]
        self.assertEqual(shipped, ["entry_block"])
        with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
            raw = json.load(f)
        self.assertEqual(list(raw["features"]), ["entry_block"])

    def test_count_empty_cells(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            conn = sqlite3.connect(path)
            conn.execute("CREATE TABLE storage (cell_id int, cell_status text)")
            conn.executemany(
                "INSERT INTO storage VALUES (?, ?)",
                [(1, "empty"), (2, "full"), (94, "empty"), (200, "empty")],
            )
            conn.commit()
            conn.close()
            cfg = {"entry_block": {"asrs1_cells": [1, 93], "asrs2_cells": [94, 186]}}
            self.assertEqual(addon_storage.count_empty_cells(path, 1, cfg), 1)
            self.assertEqual(addon_storage.count_empty_cells(path, 2, cfg), 1)
        finally:
            os.remove(path)

    def test_log_survives_closed_stdout(self):
        def boom(*args, **kwargs):
            raise OSError("stdout closed")

        addon_log.print = boom
        try:
            addon_log.log("still alive")
        finally:
            del addon_log.print

    def test_release_core_path(self):
        if CORE not in sys.path:
            sys.path.insert(0, CORE)
        addon_paths.release_core_path()
        self.assertFalse(any(
            os.path.abspath(p) == os.path.abspath(CORE) for p in sys.path if p
        ))

    def test_runners_drop_core_path_before_host(self):
        with open(os.path.join(CORE, "run_backend.py"), encoding="utf-8") as f:
            backend = f.read()
        with open(os.path.join(CORE, "run_frontend.py"), encoding="utf-8") as f:
            frontend = f.read()
        self.assertLess(backend.index("release_core_path()"), backend.index("runpy.run_path"))
        self.assertLess(frontend.index("release_core_path()"), frontend.index("exec_module"))

    def _install_fake_plc(self, actions):
        pkg = types.ModuleType("components")
        sub = types.ModuleType("components.plc")
        plc = types.ModuleType("components.plc.plc_maping")
        plc.data_read_asrs_actions = lambda: actions
        pkg.plc = sub
        sub.plc_maping = plc
        sys.modules["components"] = pkg
        sys.modules["components.plc"] = sub
        sys.modules["components.plc.plc_maping"] = plc


if __name__ == "__main__":
    unittest.main()
