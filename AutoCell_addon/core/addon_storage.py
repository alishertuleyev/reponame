# -*- coding: utf-8 -*-
import sqlite3


def cell_range(cfg, asrs_num):
    block = cfg.get("entry_block") or {}
    key = "asrs%s_cells" % int(asrs_num)
    pair = block.get(key)
    if not pair or len(pair) != 2:
        defaults = {1: (1, 93), 2: (94, 186)}
        return defaults[int(asrs_num)]
    return int(pair[0]), int(pair[1])


def count_empty_cells(db_path, asrs_num, cfg):
    lo, hi = cell_range(cfg, asrs_num)
    conn = sqlite3.connect(db_path, timeout=2)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM storage WHERE cell_id BETWEEN ? AND ? AND cell_status = 'empty'",
            (lo, hi),
        ).fetchone()[0]
        return int(n or 0)
    finally:
        conn.close()
