# -*- coding: utf-8 -*-
"""Read alarm samples. Autocell HTTP stays on the existing PLC session.

Direct snap7 is optional and read-only. A second S7 connection can take
the last free slot on the CPU, so use it only when this PC is the client.
"""
import json
import urllib.request


def parse_status(payload):
    """Map AutoCell /api/status_data into name -> monitor_value."""
    rows = payload
    if isinstance(payload, dict):
        rows = payload.get("rows")
        if rows is None:
            rows = payload.get("data")
        if rows is None:
            rows = []
    out = {}
    for row in rows or []:
        if isinstance(row, dict) and row.get("name"):
            out[str(row["name"])] = row.get("monitor_value")
    return out


def fetch_status(url, timeout=2):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return parse_status(json.loads(raw))


def sample_autocell(table, alarm):
    """None if the signal is not in this snapshot."""
    if table is None:
        return None
    name = alarm.get("signal") or ""
    if name not in table:
        return None
    return table[name]


class Snap7Reader:
    """Read-only S7 DB bits and integers. Does not write."""

    def __init__(self, cfg):
        self.cfg = cfg or {}
        self.client = None

    def close(self):
        client = self.client
        self.client = None
        if client is None:
            return
        try:
            client.disconnect()
        except Exception:
            pass

    def _connect(self):
        import snap7
        client = snap7.client.Client()
        client.connect(
            self.cfg["host"],
            int(self.cfg.get("rack", 0)),
            int(self.cfg.get("slot", 1)),
        )
        self.client = client

    def read(self, alarm):
        if self.client is None:
            self._connect()
        db = int(alarm["db"])
        start = int(alarm.get("byte", alarm.get("start", 0)))
        mode = (alarm.get("when") or "bit").strip().lower()
        try:
            if mode in ("bit", "true", "on"):
                data = self.client.db_read(db, start, 1)
                bit = int(alarm.get("bit", 0))
                return (data[0] >> bit) & 1
            data = self.client.db_read(db, start, 2)
            return int.from_bytes(data, "big", signed=True)
        except Exception:
            self.close()
            raise
