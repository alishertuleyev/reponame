# -*- coding: utf-8 -*-
"""Watch one PLC alarm and ring a phone on the corporate LAN.

The SCADA PC has no internet. The phone must be on the same network
and open this program's page, or the ntfy app pointed at this PC.
"""
import json
import os
import socket
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from logic import AlarmTracker, consider
from server import Hub, Notifier, forward_ntfy
from sources import Snap7Reader, fetch_status, sample_autocell

CONFIG_PATH = os.path.join(BASE, "config.json")
HTML_PATH = os.path.join(BASE, "phone.html")
LOG_PATH = os.path.join(BASE, "alarm_phone.log")


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S") + "  " + str(msg)
    try:
        print(line)
    except Exception:
        pass
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        pass


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def lan_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except Exception:
        return ""
    finally:
        sock.close()


def server_beep():
    try:
        import winsound
        winsound.PlaySound("SystemExclamation", winsound.SND_ALIAS | winsound.SND_ASYNC)
    except Exception:
        pass


class Poller:
    def __init__(self, cfg, hub, tracker):
        self.cfg = cfg
        self.hub = hub
        self.tracker = tracker
        self.snap = None
        self._last_error = 0.0

    def _note(self, msg):
        now = time.time()
        if now - self._last_error < 30:
            return
        self._last_error = now
        log(msg)

    def _values(self, alarms):
        table = None
        if any((a.get("via") or "autocell") == "autocell" for a in alarms):
            url = self.cfg.get("autocell_status_url") or "http://127.0.0.1:5000/api/status_data"
            try:
                table = fetch_status(url)
            except Exception as exc:
                self._note("AutoCell status недоступен: %s" % exc)
                table = None
        if any((a.get("via") or "") == "snap7" for a in alarms):
            if self.snap is None:
                self.snap = Snap7Reader(self.cfg.get("snap7") or {})
        return table

    def step(self, now):
        alarms = self.cfg.get("alarms") or []
        table = self._values(alarms)
        sent = []
        for alarm in alarms:
            via = alarm.get("via") or "autocell"
            if via == "autocell":
                if table is None:
                    sample = None
                else:
                    sample = sample_autocell(table, alarm)
            elif via == "snap7":
                try:
                    sample = self.snap.read(alarm)
                except Exception as exc:
                    self._note("snap7 чтение не удалось: %s" % exc)
                    sample = None
            else:
                self._note("неизвестный via у %s" % alarm.get("id"))
                continue
            result = consider(self.tracker, self.hub, alarm, sample, now)
            if result == "sent":
                sent.append(alarm)
        return sent

    def close(self):
        if self.snap is not None:
            self.snap.close()


def notify_sent(cfg, hub, alarm):
    title = alarm.get("title") or alarm["id"]
    message = alarm.get("message") or title
    log("АЛАРМ %s — %s" % (alarm["id"], title))
    if cfg.get("server_beep", True):
        server_beep()
    extra = (cfg.get("ntfy_url") or "").strip()
    if not extra:
        return
    try:
        forward_ntfy(extra, hub.topic, title, message)
    except Exception as exc:
        log("ntfy_url не принял сообщение: %s" % exc)


def serve(cfg):
    topic = (cfg.get("topic") or "alarm").strip()
    hub = Hub(topic)
    tracker = AlarmTracker(cfg.get("repeat_seconds") or 0)
    with open(HTML_PATH, encoding="utf-8") as handle:
        html = handle.read()
    notifier = Notifier(hub, tracker, cfg, html)
    host = cfg.get("listen") or "0.0.0.0"
    port = int(cfg.get("port") or 8787)
    httpd = notifier.serve(host, port)
    return httpd, hub, tracker


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cfg = load_config()
    httpd, hub, tracker = serve(cfg)
    port = int(cfg.get("port") or 8787)
    ip = lan_ip()
    token = (cfg.get("token") or "").strip()
    query = ("?token=" + token) if token else ""
    log("Страница телефона: http://%s:%s/%s" % (ip or "IP-этого-ПК", port, query))
    log("Топик ntfy: %s" % hub.topic)
    if "--simulate" in sys.argv:
        hub.publish("Проверка", "Сирена, ПЛК не опрашивался", "simulate")
        tracker.state["simulate"] = {"active": True, "acked": False, "last_sent": time.time()}
        log("Симуляция отправлена")
    poller = Poller(cfg, hub, tracker)
    try:
        while True:
            now = time.time()
            try:
                sent = poller.step(now)
            except Exception as exc:
                log("шаг опроса: %s" % exc)
                sent = []
            for alarm in sent:
                notify_sent(cfg, hub, alarm)
            time.sleep(float(cfg.get("poll_seconds") or 1))
    except KeyboardInterrupt:
        log("остановлено")
    finally:
        poller.close()
        hub.close_all()
        httpd.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    main()
