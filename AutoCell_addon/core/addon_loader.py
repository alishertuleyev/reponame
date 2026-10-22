# -*- coding: utf-8 -*-
"""Loads enabled features from features/<name>/ without editing AutoCell."""
import importlib.util
import os
import sys
import traceback

from addon_log import log
from addon_paths import (
    ADDON_DIR,
    CORE_DIR,
    FEATURES_DIR,
    autocell_root,
    load_config,
    release_core_path,
    storage_db,
)


def _ensure_core_path():
    if CORE_DIR not in sys.path:
        sys.path.insert(0, CORE_DIR)


def enabled_feature_names(cfg=None):
    cfg = cfg if cfg is not None else load_config()
    flags = cfg.get("features") or {}
    names = []
    if not os.path.isdir(FEATURES_DIR):
        return names
    for name in sorted(os.listdir(FEATURES_DIR)):
        folder = os.path.join(FEATURES_DIR, name)
        if not os.path.isdir(folder) or name.startswith("_"):
            continue
        if flags.get(name) is True:
            names.append(name)
    return names


def _load_module(feature, filename):
    path = os.path.join(FEATURES_DIR, feature, filename)
    if not os.path.isfile(path):
        return None
    mod_name = "addon_feature_%s_%s" % (feature, os.path.splitext(filename)[0])
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def make_ctx():
    cfg = load_config()
    root = autocell_root(cfg)
    return {
        "config": cfg,
        "addon_dir": ADDON_DIR,
        "core_dir": CORE_DIR,
        "autocell_root": root,
        "db_path": storage_db(root, cfg),
        "log": log,
        "features": enabled_feature_names(cfg),
    }


def _call_feature(kind, name, fn):
    """Run a feature hook. SystemExit here must not kill the AutoCell service."""
    try:
        fn()
    except BaseException:
        log("%s feature FAIL %s:\n%s" % (kind, name, traceback.format_exc()))
        return False
    return True


def install_backend():
    _ensure_core_path()
    try:
        ctx = make_ctx()
        log("backend start, AutoCell=" + ctx["autocell_root"])
        log("features: " + ", ".join(ctx["features"] or ["(none)"]))
        for name in ctx["features"]:
            mod = None
            try:
                mod = _load_module(name, "backend.py")
            except BaseException:
                log("backend feature FAIL " + name + ":\n" + traceback.format_exc())
                continue
            if mod and hasattr(mod, "install"):
                if _call_feature("backend", name, lambda m=mod: m.install(ctx)):
                    log("backend feature ON: " + name)
        return ctx
    finally:
        release_core_path()


def _static_scripts(ctx):
    urls = ["/addon/static/_core/badge.js"]
    for name in ctx["features"]:
        static = os.path.join(FEATURES_DIR, name, "static")
        if not os.path.isdir(static):
            continue
        for fn in sorted(os.listdir(static)):
            if fn.endswith(".js"):
                urls.append("/addon/static/%s/%s" % (name, fn))
    return urls


def install_frontend(app):
    from flask import abort, send_from_directory

    _ensure_core_path()
    try:
        ctx = make_ctx()
        log("frontend start, AutoCell=" + ctx["autocell_root"])
        log("features: " + ", ".join(ctx["features"] or ["(none)"]))

        allowed = set(ctx["features"]) | {"_core"}
        scripts = _static_scripts(ctx)
        inject = b"\n" + b"".join(
            b'<script src="' + u.encode("ascii") + b'"></script>\n' for u in scripts
        )

        @app.after_request
        def addon_inject(resp):
            try:
                if getattr(resp, "direct_passthrough", False):
                    return resp
                if (resp.headers.get("Content-Encoding") or "").strip():
                    return resp
                ctype = resp.content_type or ""
                if resp.status_code != 200 or "text/html" not in ctype:
                    return resp
                data = resp.get_data()
                if b"/addon/static/_core/badge.js" in data:
                    return resp
                lower = data.lower()
                idx = lower.rfind(b"</body>")
                if idx < 0:
                    idx = lower.rfind(b"</html>")
                if idx >= 0:
                    data = data[:idx] + inject + data[idx:]
                    resp.set_data(data)
                    resp.headers["Content-Length"] = str(len(data))
            except Exception:
                log("HTML inject error:\n" + traceback.format_exc())
            return resp

        @app.route("/addon/static/<feature>/<path:filename>")
        def addon_static(feature, filename):
            if feature not in allowed or ".." in filename or filename.startswith("/"):
                abort(404)
            if feature == "_core":
                folder = os.path.join(CORE_DIR, "static")
            else:
                folder = os.path.join(FEATURES_DIR, feature, "static")
            if not os.path.isfile(os.path.join(folder, filename)):
                abort(404)
            r = send_from_directory(folder, filename)
            r.headers["Cache-Control"] = "no-store"
            return r

        for name in ctx["features"]:
            mod = None
            try:
                mod = _load_module(name, "frontend.py")
            except BaseException:
                log("frontend feature FAIL " + name + ":\n" + traceback.format_exc())
                continue
            if mod and hasattr(mod, "install"):
                if _call_feature("frontend", name, lambda m=mod: m.install(app, ctx)):
                    log("frontend feature ON: " + name)
        return ctx
    finally:
        release_core_path()
