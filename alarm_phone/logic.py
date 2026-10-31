# -*- coding: utf-8 -*-
"""Alarm edge detection. No PLC or network calls."""


def classify(raw, when, equals=None):
    """True when the sample is the alarm condition."""
    if isinstance(raw, bool):
        text = "1" if raw else "0"
    else:
        text = str(raw if raw is not None else "").strip().lower()
    mode = (when or "nonzero").strip().lower()
    if mode in ("bit", "true", "on"):
        return text in ("1", "true", "yes", "on")
    if mode == "equals":
        return text == str(equals if equals is not None else "").strip().lower()
    if mode == "nonzero":
        try:
            return float(text) != 0.0
        except ValueError:
            return text not in ("", "0", "false", "none", "empty", "off", "—", "-")
    raise ValueError("unknown when: " + mode)


class AlarmTracker:
    """Notify on the rising edge, then again while it stays active and unacked."""

    def __init__(self, repeat_seconds):
        self.repeat = float(repeat_seconds or 0)
        self.state = {}

    def update(self, alarm_id, active, now):
        st = self.state.get(alarm_id)
        if st is None:
            st = {"active": False, "acked": False, "last_sent": 0.0}
            self.state[alarm_id] = st
        if not active:
            st["active"] = False
            st["acked"] = False
            st["last_sent"] = 0.0
            return False
        if not st["active"]:
            st["active"] = True
            st["acked"] = False
            st["last_sent"] = now
            return True
        if st["acked"]:
            return False
        if self.repeat > 0 and (now - st["last_sent"]) >= self.repeat:
            st["last_sent"] = now
            return True
        return False

    def ack(self, alarm_id):
        st = self.state.get(alarm_id)
        if st is None or not st["active"]:
            return False
        st["acked"] = True
        return True

    def snapshot(self):
        out = []
        for alarm_id, st in self.state.items():
            out.append({
                "id": alarm_id,
                "active": bool(st["active"]),
                "acked": bool(st["acked"]),
            })
        return out


def consider(tracker, hub, alarm, sample, now):
    """sample is None when the source is down or the signal is absent: hold state.

    Returns 'skip', 'sent', or 'quiet'.
    """
    if sample is None:
        return "skip"
    active = classify(sample, alarm.get("when") or "nonzero", alarm.get("equals"))
    if tracker.update(alarm["id"], active, now):
        hub.publish(
            alarm.get("title") or alarm["id"],
            alarm.get("message") or alarm.get("title") or alarm["id"],
            alarm["id"],
        )
        return "sent"
    return "quiet"
