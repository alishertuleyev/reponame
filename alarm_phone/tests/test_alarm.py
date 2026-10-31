# -*- coding: utf-8 -*-
import json
import os
import socket
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import watch
from logic import AlarmTracker, classify, consider
from server import Hub, Notifier, is_loopback, state_payload
from sources import parse_status, sample_autocell


HTML = "<html>__TOKEN__ сирена</html>"


class ClassifyTests(unittest.TestCase):
    def test_nonzero_and_bit(self):
        self.assertFalse(classify("0", "nonzero"))
        self.assertFalse(classify(0, "nonzero"))
        self.assertTrue(classify("12", "nonzero"))
        self.assertTrue(classify("1", "bit"))
        self.assertFalse(classify("0", "bit"))
        self.assertFalse(classify("", "nonzero"))
        self.assertFalse(classify("false", "nonzero"))
        self.assertTrue(classify("true", "nonzero"))
        self.assertTrue(classify("5", "equals", "5"))
        self.assertFalse(classify("4", "equals", "5"))

    def test_status_table(self):
        table = parse_status([
            {"name": "from_WMS_dn_jb_error_ASRS1", "monitor_value": "0"},
            {"name": "other", "monitor_value": "1"},
        ])
        alarm = {"signal": "from_WMS_dn_jb_error_ASRS1"}
        self.assertEqual(sample_autocell(table, alarm), "0")
        self.assertIsNone(sample_autocell(table, {"signal": "missing"}))
        self.assertIsNone(sample_autocell(None, alarm))

    def test_edge_ack_and_hold_when_source_down(self):
        hub = Hub("alarm")
        tracker = AlarmTracker(repeat_seconds=10)
        alarm = {"id": "e", "title": "Ошибка", "message": "код", "when": "nonzero"}
        self.assertEqual(consider(tracker, hub, alarm, "0", 100), "quiet")
        self.assertEqual(consider(tracker, hub, alarm, "7", 101), "sent")
        self.assertEqual(consider(tracker, hub, alarm, "7", 102), "quiet")
        self.assertEqual(consider(tracker, hub, alarm, None, 150), "skip")
        self.assertTrue(tracker.snapshot()[0]["active"])
        self.assertEqual(len(hub.recent), 1)
        self.assertTrue(tracker.ack("e"))
        self.assertEqual(consider(tracker, hub, alarm, "7", 200), "quiet")
        self.assertEqual(consider(tracker, hub, alarm, "0", 201), "quiet")
        self.assertEqual(consider(tracker, hub, alarm, "7", 202), "sent")
        self.assertEqual(hub.recent[-1]["title"], "Ошибка")
        self.assertEqual(hub.recent[-1]["priority"], 5)

    def test_poller_fires_on_rising_status_value(self):
        cfg = {
            "autocell_status_url": "http://127.0.0.1:9/missing",
            "alarms": [{
                "id": "asrs1_error",
                "title": "ASRS1 ошибка задания",
                "message": "код",
                "via": "autocell",
                "signal": "from_WMS_dn_jb_error_ASRS1",
                "when": "nonzero",
            }],
        }
        hub = Hub("alarm")
        tracker = AlarmTracker(30)
        poller = watch.Poller(cfg, hub, tracker)
        saved = watch.fetch_status
        try:
            watch.fetch_status = lambda url, timeout=2: {"from_WMS_dn_jb_error_ASRS1": "0"}
            self.assertEqual(poller.step(time.time()), [])
            watch.fetch_status = lambda url, timeout=2: {"from_WMS_dn_jb_error_ASRS1": "4"}
            sent = poller.step(time.time())
            self.assertEqual([item["id"] for item in sent], ["asrs1_error"])
            self.assertEqual(hub.recent[-1]["message"], "код")

            def down(url, timeout=2):
                raise OSError("down")

            watch.fetch_status = down
            self.assertEqual(poller.step(time.time()), [])
            self.assertTrue(tracker.snapshot()[0]["active"])
        finally:
            watch.fetch_status = saved


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.hub = Hub("alarm")
        self.tracker = AlarmTracker(0)
        cfg = {"token": "secret", "alarms": [
            {"id": "e", "title": "Ошибка", "message": "код"},
        ]}
        self.notifier = Notifier(self.hub, self.tracker, cfg, HTML)
        self.httpd = self.notifier.serve("127.0.0.1", 0)
        self.port = self.httpd.server_address[1]

    def tearDown(self):
        self.hub.close_all()
        self.httpd.shutdown()
        self.httpd.server_close()

    def _open(self, path, method="GET", data=None, token="secret"):
        url = "http://127.0.0.1:%s%s" % (self.port, path)
        if token:
            url += ("&" if "?" in path else "?") + "token=" + token
        req = urllib.request.Request(url, data=data, method=method)
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status, resp.read().decode("utf-8")

    def test_page_token_and_state(self):
        status, body = self._open("/")
        self.assertEqual(status, 200)
        self.assertIn("secret", body)
        self.assertIn("сирена", body)
        self.tracker.update("e", True, 1)
        status, body = self._open("/state")
        payload = json.loads(body)
        self.assertTrue(payload["alarms"][0]["active"])
        self.assertEqual(payload["alarms"][0]["title"], "Ошибка")
        status, _ = self._open("/ack/e", method="POST", data=b"")
        self.assertEqual(status, 200)
        self.assertTrue(self.tracker.snapshot()[0]["acked"])

    def test_token_required(self):
        url = "http://127.0.0.1:%s/state" % self.port
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(url, timeout=3)
        self.assertEqual(caught.exception.code, 401)

    def test_ntfy_stream_does_not_need_page_token(self):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        sock.settimeout(2)
        sock.sendall(b"GET /alarm/json HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        buf = b""
        deadline = time.time() + 2
        while time.time() < deadline and b"open" not in buf:
            try:
                buf += sock.recv(4096)
            except socket.timeout:
                break
        sock.close()
        self.assertIn(b"open", buf)
        self.assertNotIn(b"401", buf.split(b"\r\n")[0])

    def test_json_stream_receives_alarm(self):
        found = {}

        def reader():
            sock = socket.create_connection(("127.0.0.1", self.port), timeout=3)
            sock.settimeout(2)
            req = (
                "GET /alarm/json?token=secret HTTP/1.1\r\n"
                "Host: 127.0.0.1\r\n"
                "Connection: close\r\n\r\n"
            )
            sock.sendall(req.encode("ascii"))
            buf = b""
            deadline = time.time() + 3
            while time.time() < deadline and b'"event": "message"' not in buf and b'"event":"message"' not in buf:
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
                    chunk = b""
                if not chunk:
                    if buf:
                        break
                    continue
                buf += chunk
            sock.close()
            found["buf"] = buf

        thread = threading.Thread(target=reader)
        thread.start()
        time.sleep(0.4)
        self.hub.publish("Ошибка", "код 7", "e")
        thread.join(4)
        text = found.get("buf", b"").decode("utf-8", errors="replace")
        self.assertIn('"event": "open"', text.replace('"event":"open"', '"event": "open"'))
        self.assertIn("код 7", text)

    def test_loopback_only(self):
        self.assertTrue(is_loopback("127.0.0.1"))
        self.assertFalse(is_loopback("192.168.0.5"))
        payload = state_payload(self.tracker, [{"id": "e", "title": "Ошибка", "message": ""}])
        self.assertEqual(payload["alarms"], [])


if __name__ == "__main__":
    unittest.main()
