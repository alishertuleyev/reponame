# -*- coding: utf-8 -*-
"""NSSM install/remove. Does not edit AutoCell files and does not start or stop services."""
import json
import os
import shutil
import subprocess
import sys

from addon_paths import ADDON_DIR, CORE_DIR, STATE_DIR, autocell_root, ensure_state_dir, load_config

BACKUP = os.path.join(STATE_DIR, "nssm_backup.json")

_STATES = {
    "RUNNING",
    "STOPPED",
    "STOP_PENDING",
    "START_PENDING",
    "PAUSED",
    "PAUSE_PENDING",
    "CONTINUE_PENDING",
}


def _decode_nssm(raw):
    if not raw:
        return ""
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16").strip("\x00").strip()
    if len(raw) >= 4 and raw[1:2] == b"\x00":
        return raw.decode("utf-16le").strip("\x00").strip()
    return raw.decode("utf-8", errors="replace").strip("\x00").strip()


def nssm_get(nssm, service, key):
    raw = subprocess.check_output([nssm, "get", service, key], stderr=subprocess.STDOUT)
    return _decode_nssm(raw)


def nssm_set(nssm, service, key, value):
    subprocess.check_call([nssm, "set", service, key, value])


def parse_sc_query(text):
    """Read sc query output. STOP_PENDING must not be treated as STOPPED."""
    if not text:
        return "UNKNOWN"
    for line in text.splitlines():
        upper = line.upper()
        if "STATE" not in upper and "СОСТОЯНИЕ" not in upper:
            continue
        parts = line.strip().split()
        if not parts:
            continue
        token = parts[-1].upper()
        if token in _STATES:
            return token
    return "UNKNOWN"


def service_state(name):
    try:
        raw = subprocess.check_output(["sc", "query", name], stderr=subprocess.STDOUT)
        text = raw.decode("utf-8", errors="replace")
        if "\x00" in text[:4] or (len(raw) >= 4 and raw[1:2] == b"\x00"):
            text = _decode_nssm(raw)
        return parse_sc_query(text)
    except Exception:
        return "UNKNOWN"


def _clean_path(p):
    p = (p or "").strip().strip('"')
    if len(p) >= 4 and p[1] == ":" and p[2] == " " and p[3] == "\\":
        p = p[:2] + p[3:]
    return p


def sane_win_path(p):
    p = _clean_path(p)
    if not p or any(ch in p for ch in ("\x00", "\r", "\n")):
        return False
    if len(p) < 3 or not p[0].isalpha() or p[1] != ":":
        return False
    return True


def snapshot_ok(snap):
    if not isinstance(snap, dict) or not snap:
        return False
    for data in snap.values():
        if not isinstance(data, dict):
            return False
        if not sane_win_path(data.get("Application")):
            return False
        if not sane_win_path(data.get("AppDirectory")):
            return False
        params = data.get("AppParameters")
        if params is None:
            return False
        if any(ch in str(params) for ch in ("\x00", "\r", "\n")):
            return False
    return True


def _service_image_path(service):
    try:
        raw = subprocess.check_output(["sc", "qc", service], stderr=subprocess.STDOUT)
    except Exception:
        return ""
    text = raw.decode("utf-8", errors="replace")
    if "\x00" in text[:4] or (len(raw) >= 4 and raw[1:2] == b"\x00"):
        text = _decode_nssm(raw)
    for line in text.splitlines():
        up = line.upper()
        if "BINARY_PATH_NAME" not in up and "NSSM.EXE" not in up:
            continue
        if " : " in line:
            return _clean_path(line.split(" : ", 1)[-1])
    return ""


def find_nssm(cfg, root, services):
    candidates = []
    custom = _clean_path(cfg.get("nssm") or "")
    if custom:
        candidates.append(custom)
    for name in services.values():
        img = _service_image_path(name)
        if img.lower().endswith("nssm.exe"):
            candidates.append(img)
    candidates.extend([
        os.path.join(root, "bin", "nssm.exe"),
        r"C:\AutoCell\bin\nssm.exe",
        r"C:\nssm\nssm.exe",
        r"C:\nssm\win64\nssm.exe",
    ])
    which = shutil.which("nssm")
    if which:
        candidates.append(which)

    tried = []
    seen = set()
    for p in candidates:
        p = _clean_path(p)
        if not p:
            continue
        p = os.path.normpath(p)
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        tried.append(p)
        if os.path.isfile(p):
            print("NSSM:     " + p)
            return p

    raise SystemExit(
        "NSSM не найден. Проверенные пути:\n  "
        + "\n  ".join(tried)
        + "\nУкажите полный путь в config.json -> nssm"
        + "\nИли в cmd:  sc qc AutoCellBackend"
        + "\nстрока BINARY_PATH_NAME — это и есть nssm.exe"
    )


def looks_like_addon(params):
    p = (params or "").replace("/", "\\").lower()
    return "autocell_addon" in p and "run_" in p


def quoted(path):
    path = os.path.abspath(path)
    if " " in path or "\t" in path:
        return '"' + path + '"'
    return path


def snapshot(nssm, services):
    out = {}
    for role, name in services.items():
        out[role] = {
            "name": name,
            "Application": nssm_get(nssm, name, "Application"),
            "AppDirectory": nssm_get(nssm, name, "AppDirectory"),
            "AppParameters": nssm_get(nssm, name, "AppParameters"),
        }
    return out


def apply_snapshot(nssm, snap):
    for role, data in snap.items():
        name = data["name"]
        nssm_set(nssm, name, "Application", data["Application"])
        nssm_set(nssm, name, "AppDirectory", data["AppDirectory"])
        nssm_set(nssm, name, "AppParameters", data["AppParameters"])


def print_states(services):
    for name in services.values():
        print("  %s: %s" % (name, service_state(name)))


def _services(cfg):
    services = cfg.get("services") or {}
    if "backend" not in services or "frontend" not in services:
        raise SystemExit("config.json: нужны services.backend и services.frontend")
    return services


def addon_scripts():
    return {
        "backend": os.path.join(CORE_DIR, "run_backend.py"),
        "frontend": os.path.join(CORE_DIR, "run_frontend.py"),
    }


def original_scripts(root):
    return {
        "backend": os.path.join(root, "backend", "main.py"),
        "frontend": os.path.join(root, "frontend", "app.py"),
    }


def set_parameters(nssm, services, scripts):
    """Change only AppParameters. Never Application, AppDirectory, start, or stop."""
    for role, script in scripts.items():
        if role not in services:
            raise SystemExit("нет службы для " + role)
        if not os.path.isfile(script):
            raise SystemExit("нет файла " + script)
        name = services[role]
        nssm_set(nssm, name, "AppParameters", quoted(script))
        print("%s AppParameters -> %s" % (name, script))


def _save_backup(current):
    if os.path.isfile(BACKUP):
        print("Backup уже есть, не трогаю.")
        return
    addonish = any(looks_like_addon(v.get("AppParameters")) for v in current.values())
    if addonish:
        print("Службы уже на надстройке, backup не перезаписываю.")
        return
    if not snapshot_ok(current):
        raise SystemExit("Ответ NSSM не разобран. Службу не менял.")
    ensure_state_dir()
    with open(BACKUP, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    print("Сохранил исходные пути служб: state\\nssm_backup.json")


def cmd_install():
    cfg = load_config()
    root = autocell_root(cfg)
    services = _services(cfg)
    nssm = find_nssm(cfg, root, services)
    ensure_state_dir()

    print("Python:   " + sys.executable)
    print("AutoCell: " + root)
    print("Addon:    " + ADDON_DIR)
    print("Службы НЕ останавливаю и НЕ запускаю.")
    print_states(services)

    try:
        current = snapshot(nssm, services)
    except subprocess.CalledProcessError:
        raise SystemExit(
            "Служба AutoCellBackend/Frontend не найдена. Сначала AutoCell\\setup.bat"
        )
    if not snapshot_ok(current):
        raise SystemExit(
            "Ответ NSSM не разобран (битый путь python или каталога). "
            "Службу не менял. Проверьте: nssm get AutoCellBackend Application"
        )
    _save_backup(current)
    set_parameters(nssm, services, addon_scripts())

    print("")
    print("Готово. Application и AppDirectory не менял.")
    print("Службу не останавливал и не запускал.")
    print("Надстройка включится при следующем штатном старте (ребут ПК).")
    print("Сейчас ASRS работает тем процессом, который уже запущен.")
    print_states(services)


def cmd_remove():
    cfg = load_config()
    root = autocell_root(cfg)
    services = _services(cfg)
    nssm = find_nssm(cfg, root, services)

    print("Службы НЕ останавливаю и НЕ запускаю.")
    print_states(services)

    restored = False
    snap = None
    if os.path.isfile(BACKUP):
        try:
            with open(BACKUP, encoding="utf-8") as f:
                snap = json.load(f)
        except FileNotFoundError:
            snap = None
        except Exception as exc:
            raise SystemExit("backup не читается, службу не менял: %s" % exc)
    if snap is not None and snapshot_ok(snap):
        print("Восстанавливаю пути из state\\nssm_backup.json")
        apply_snapshot(nssm, snap)
        restored = True
    elif snap is not None:
        print("Backup повреждён. Application не трогаю, верну только скрипты.")
    if not restored:
        set_parameters(nssm, services, original_scripts(root))
        print("AppParameters возвращены на main.py / app.py.")

    print("")
    print("Процесс не перезапускался.")
    print("Оригинал подхватится при следующем старте службы (ребут).")
    print_states(services)


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("install", "remove"):
        raise SystemExit("usage: cli.py install|remove")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if sys.argv[1] == "install":
        cmd_install()
    else:
        cmd_remove()
