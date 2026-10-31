# -*- coding: utf-8 -*-
"""LAN notifier: phone page, and an ntfy-style JSON stream for the ntfy app.

Publish from the network is refused. Only this process, or a program on
the same PC, can raise an alarm.
"""
import html
import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

def is_loopback(ip):
    return ip in ("127.0.0.1", "::1")


class Hub:
    def __init__(self, topic):
        self.topic = topic
        self._subs = []
        self._lock = threading.Lock()
        self.recent = []

    def publish(self, title, message, alarm_id):
        event = {
            "id": "%x" % (time.time_ns() & 0xFFFFFFFFFFFF),
            "time": int(time.time()),
            "event": "message",
            "topic": self.topic,
            "title": title,
            "message": message,
            "priority": 5,
            "tags": ["warning"],
            "alarm_id": alarm_id,
        }
        with self._lock:
            self.recent.append(event)
            del self.recent[:-50]
            subs = list(self._subs)
        for sub in subs:
            try:
                sub.put_nowait(event)
            except queue.Full:
                pass
        return event

    def subscribe(self):
        sub = queue.Queue(maxsize=100)
        with self._lock:
            if len(self._subs) >= 30:
                raise RuntimeError("too many listeners")
            self._subs.append(sub)
        return sub

    def unsubscribe(self, sub):
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)

    def close_all(self):
        with self._lock:
            subs = list(self._subs)
        for sub in subs:
            try:
                sub.put_nowait(None)
            except queue.Full:
                pass


def state_payload(tracker, alarms):
    by_id = {a["id"]: a for a in alarms}
    rows = []
    for row in tracker.snapshot():
        alarm = by_id.get(row["id"], {})
        rows.append({
            "id": row["id"],
            "active": row["active"],
            "acked": row["acked"],
            "title": alarm.get("title") or row["id"],
            "message": alarm.get("message") or "",
        })
    return {"alarms": rows}


def _line(obj):
    return json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n"


class Notifier:
    def __init__(self, hub, tracker, cfg, html):
        self.hub = hub
        self.tracker = tracker
        self.cfg = cfg
        self.html = html
        self.httpd = None

    def serve(self, host, port):
        handler = self._handler_class()
        self.httpd = ThreadingHTTPServer((host, port), handler)
        self.httpd.daemon_threads = True
        thread = threading.Thread(target=self.httpd.serve_forever, name="alarm-http", daemon=True)
        thread.start()
        return self.httpd

    def _handler_class(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):
                return

            def _query(self):
                return parse_qs(urlparse(self.path).query)

            def _ok_token(self):
                token = (owner.cfg.get("token") or "").strip()
                if not token:
                    return True
                got = (self._query().get("token") or [""])[0]
                header = self.headers.get("X-Token") or ""
                return got == token or header == token

            def _send(self, code, body, content_type, extra=None):
                data = body if isinstance(body, bytes) else body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                for key, value in (extra or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(data)

            def _deny(self, code, text):
                self._send(code, text, "text/plain; charset=utf-8")

            def do_GET(self):
                path = urlparse(self.path).path
                topic = owner.hub.topic
                # The ntfy app cannot attach a custom token. The topic name is the secret.
                if path == "/" + topic + "/json":
                    self._stream_ndjson()
                    return
                if path not in ("/health",) and not self._ok_token():
                    self._deny(401, "token")
                    return
                if path in ("/", "/phone"):
                    token = (owner.cfg.get("token") or "").strip()
                    page = owner.html.replace("__TOKEN__", html.escape(token, quote=True))
                    self._send(200, page, "text/html; charset=utf-8")
                    return
                if path == "/health":
                    self._send(200, json.dumps({"ok": True}), "application/json")
                    return
                if path == "/state":
                    body = json.dumps(
                        state_payload(owner.tracker, owner.cfg.get("alarms") or []),
                        ensure_ascii=False,
                    )
                    self._send(200, body, "application/json; charset=utf-8")
                    return
                self._deny(404, "not found")

            def do_POST(self):
                path = urlparse(self.path).path
                local = is_loopback(self.client_address[0])
                if path.startswith("/ack/"):
                    if not self._ok_token():
                        self._deny(401, "token")
                        return
                    alarm_id = path[len("/ack/"):]
                    owner.tracker.ack(alarm_id)
                    self._send(200, "{\"ok\":true}", "application/json")
                    return
                if path == "/simulate" or path == "/" + owner.hub.topic:
                    if not local:
                        self._deny(403, "only this PC can raise an alarm")
                        return
                    length = int(self.headers.get("Content-Length") or 0)
                    raw = self.rfile.read(length) if length else b""
                    text = raw.decode("utf-8", errors="replace").strip() or "проверка сирены"
                    owner.hub.publish("Проверка", text, "simulate")
                    owner.tracker.state["simulate"] = {
                        "active": True,
                        "acked": False,
                        "last_sent": time.time(),
                    }
                    self._send(200, "{\"ok\":true}", "application/json")
                    return
                self._deny(404, "not found")

            def _stream_ndjson(self):
                try:
                    sub = owner.hub.subscribe()
                except RuntimeError:
                    self._deny(503, "too many listeners")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    self.wfile.write(_line({
                        "id": "open",
                        "time": int(time.time()),
                        "event": "open",
                        "topic": owner.hub.topic,
                    }))
                    self.wfile.flush()
                    while True:
                        try:
                            event = sub.get(timeout=15)
                        except queue.Empty:
                            event = {
                                "id": "keepalive",
                                "time": int(time.time()),
                                "event": "keepalive",
                                "topic": owner.hub.topic,
                            }
                        if event is None:
                            break
                        self.wfile.write(_line(event))
                        self.wfile.flush()
                except Exception:
                    pass
                finally:
                    owner.hub.unsubscribe(sub)

        return Handler


def forward_ntfy(base_url, topic, title, message, timeout=2):
    """Optional POST to a real ntfy.exe on the same PC. Cyrillic stays in JSON."""
    if not base_url:
        return
    body = json.dumps({
        "topic": topic,
        "title": title,
        "message": message,
        "priority": 5,
        "tags": ["warning"],
    }, ensure_ascii=False).encode("utf-8")
    req = urllib_request(base_url, body)
    with req as resp:
        resp.read()


def urllib_request(base_url, body):
    import urllib.request
    url = base_url.rstrip("/") + "/"
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    return urllib.request.urlopen(request, timeout=2)
