# -*- coding: utf-8 -*-
"""Block new ENTRY (1/5) when the crane is waiting and its aisle has no empty cells.

Do not import AutoCell PLC modules here. The host imports them itself;
we wrap the functions after that import. A failure stays fail-open and
must not stop AutoCellBackend.
"""
import sys
import traceback

from addon_storage import count_empty_cells

# Same indices as AutoCell auto_mode.py: falsy outfeed bit means the exit is free.
OUTFEED_INDEX = {1: 4, 2: 6}

_busy = False
_hooked = False


def decide_type(requested, waiting, empty, outfeed_free, block_types):
    """Return the TYPE to write.

    waiting/empty/outfeed_free use None when the read failed.
    Unknown data does not change the requested type.
    """
    try:
        req = int(requested)
    except (TypeError, ValueError):
        return requested
    types = set(block_types or [])
    if req not in types:
        return req
    if waiting is not True:
        return req
    if empty is None or empty > 0:
        return req
    if outfeed_free is True:
        return 2
    if outfeed_free is False:
        return 0
    return req


def _actions():
    from components.plc.plc_maping import data_read_asrs_actions
    return data_read_asrs_actions()


def _read_flags(asrs_num, cfg):
    """Return (waiting, outfeed_free). None means unknown, do not block."""
    try:
        actions = _actions()
        if not actions:
            return None, None
        block = cfg.get("entry_block") or {}
        n = int(asrs_num)
        wmap = block.get("waiting_index") or {}
        omap = block.get("outfeed_index") or {}
        widx = int(wmap.get(str(n), 20 if n == 1 else 46))
        oidx = int(omap.get(str(n), OUTFEED_INDEX[n]))
        # auto_mode treats a falsy outfeed bit as free and then writes TYPE 2.
        return bool(actions[widx]), (not bool(actions[oidx]))
    except Exception:
        return None, None


def adjust(requested, asrs_num, ctx):
    cfg = ctx["config"]
    types = (cfg.get("entry_block") or {}).get("block_types") or [1, 5]
    waiting, outfeed_free = _read_flags(asrs_num, cfg)
    empty = None
    if waiting is True:
        try:
            empty = count_empty_cells(ctx["db_path"], asrs_num, cfg)
        except Exception:
            ctx["log"]("entry_block: база недоступна, вход не блокирую")
            empty = None
    new_type = decide_type(requested, waiting, empty, outfeed_free, types)
    try:
        changed = int(new_type) != int(requested)
    except (TypeError, ValueError):
        changed = new_type != requested
    if changed:
        ctx["log"](
            "ASRS%s: вход %s заблокирован (empty=%s) → TYPE %s"
            % (asrs_num, requested, empty, new_type)
        )
    return new_type


def _wrap_write(orig, asrs_num, ctx):
    if getattr(orig, "_autocell_addon_wrapped", False):
        return orig
    log = ctx["log"]

    def wrapped(DN_JB_TYPE):
        new_type = DN_JB_TYPE
        try:
            new_type = adjust(DN_JB_TYPE, asrs_num, ctx)
        except Exception:
            log("entry_block write filter error, pass-through:\n" + traceback.format_exc())
            new_type = DN_JB_TYPE
        return orig(new_type)

    wrapped._autocell_addon_wrapped = True
    return wrapped


def _wrap_auto(orig, asrs_num, ctx):
    if getattr(orig, "_autocell_addon_auto", False):
        return orig
    log = ctx["log"]

    def wrapped():
        selected = orig()
        try:
            return adjust(selected, asrs_num, ctx)
        except Exception:
            log("entry_block auto filter error, pass-through:\n" + traceback.format_exc())
            return selected

    wrapped._autocell_addon_auto = True
    return wrapped


def _try_wrap(ctx):
    global _busy
    if _busy:
        return
    plc = sys.modules.get("components.plc.plc_maping")
    auto_mode = sys.modules.get("components.auto_mode")
    if plc is None and auto_mode is None:
        return
    _busy = True
    try:
        if plc is not None:
            for asrs, attr in ((1, "write_dn_jb_type_asrs1"), (2, "write_dn_jb_type_asrs2")):
                fn = getattr(plc, attr, None)
                if fn is None:
                    continue
                wrapped = _wrap_write(fn, asrs, ctx)
                if wrapped is not fn:
                    setattr(plc, attr, wrapped)
                    ctx["log"]("entry_block: wrap " + attr)
        if auto_mode is not None:
            for asrs, attr in ((1, "auto_selection_asrs1"), (2, "auto_selection_asrs2")):
                fn = getattr(auto_mode, attr, None)
                if fn is None:
                    continue
                wrapped = _wrap_auto(fn, asrs, ctx)
                if wrapped is not fn:
                    setattr(auto_mode, attr, wrapped)
                    ctx["log"]("entry_block: wrap " + attr)
    finally:
        _busy = False


def install(ctx):
    global _hooked
    import builtins

    if not _hooked:
        _hooked = True
        real = builtins.__import__

        def hooked(name, globals=None, locals=None, fromlist=(), level=0):
            mod = real(name, globals, locals, fromlist, level)
            try:
                _try_wrap(ctx)
            except BaseException:
                try:
                    ctx["log"]("entry_block hook error:\n" + traceback.format_exc())
                except Exception:
                    pass
            return mod

        builtins.__import__ = hooked
    try:
        _try_wrap(ctx)
    except BaseException:
        ctx["log"]("entry_block wrap error:\n" + traceback.format_exc())
    ctx["log"]("entry_block: жду импорт plc_maping и auto_mode, сам их не загружаю")
