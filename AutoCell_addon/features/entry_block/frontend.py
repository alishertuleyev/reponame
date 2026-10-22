# -*- coding: utf-8 -*-
"""UI lock + reject /api/set_asrs_modes 1/5 when the aisle has no empty cells."""
import traceback

from addon_storage import count_empty_cells


def install(app, ctx):
    from flask import jsonify, request

    cfg = ctx["config"]
    db_path = ctx["db_path"]
    log = ctx["log"]
    types = set((cfg.get("entry_block") or {}).get("block_types") or [1, 5])

    @app.route("/addon/empty_cells")
    def addon_empty_cells():
        try:
            return jsonify({
                "asrs1": count_empty_cells(db_path, 1, cfg),
                "asrs2": count_empty_cells(db_path, 2, cfg),
            })
        except Exception as e:
            return jsonify({"asrs1": None, "asrs2": None, "error": str(e)}), 500

    @app.before_request
    def addon_reject_entry_if_full():
        try:
            if request.path != "/api/set_asrs_modes" or request.method != "POST":
                return None
            data = request.get_json(silent=True) or {}
            for key, asrs_num in (("asrs1", 1), ("asrs2", 2)):
                block = data.get(key) or {}
                if block.get("control") != "manual":
                    continue
                mode = block.get("mode")
                try:
                    mode = int(mode)
                except Exception:
                    continue
                if mode not in types:
                    continue
                try:
                    empty = count_empty_cells(db_path, asrs_num, cfg)
                except Exception:
                    log("entry_block: база недоступна, ручной вход не блокирую")
                    continue
                if empty <= 0:
                    msg = "ASRS%s: вход (%s) заблокирован — нет пустых ячеек" % (
                        asrs_num, mode
                    )
                    log(msg)
                    return jsonify({"error": msg}), 400
        except Exception:
            log("entry_block API guard error, pass-through:\n" + traceback.format_exc())
            return None
        return None
