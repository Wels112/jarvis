# -*- coding: utf-8 -*-
"""Планировщик недели: одна неделя Пн–Вс, которая повторяется всегда.

Хозяин (10.10.2026): «у меня каждую неделю одни и те же задачи — репетиторство,
учёба. Хочу расписать каждый день, события двигать мышкой, и чтобы это было
у меня на компьютере, без всяких сайтов, и Джарвис понимал, что да как».

Устройство:
* Данные — один файл data/brain/planner.json: категории и события вида
  {день 0–6, начало, конец, название, описание, категория, напомнить}.
  Дат нет — неделя шаблонная.
* Окно — страница apps/planner/index.html, которую отдаёт маленький сервер на
  127.0.0.1 (только этот компьютер; снаружи недоступен, чужие страницы писать
  в него не могут — проверяются Host и Origin). Открывается окном Edge без
  адресной строки — выглядит как программа.
* Сервер поднимает Джарвис при запуске. Без Джарвиса — планировщик.bat
  (python -m skills.planner): поднимет сервер сам и погасит его, когда окно
  закроют (страница раз в 20 секунд отмечается).
* Изменения — отдельными операциями (создать, поправить, удалить), а не
  перезаписью всего файла: так событие, добавленное голосом, не пропадёт,
  пока открыто окно. Окно раз в несколько секунд сверяет номер версии.
"""
import json
import os
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "apps" / "planner" / "index.html"
PORT = 8765
DAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
DAYS_ACC = ["понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье"]
DAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

DEFAULT = {
    "version": 1,
    "categories": [
        {"id": "tutor", "name": "Репетиторство", "color": "#2f7d6d"},
        {"id": "study", "name": "Учёба", "color": "#3f62c4"},
        {"id": "work", "name": "Проекты", "color": "#a9640f"},
        {"id": "sport", "name": "Спорт", "color": "#b8452f"},
        {"id": "life", "name": "Личное", "color": "#7a4fb0"},
    ],
    "events": [],
}

_lock = threading.RLock()


def path() -> Path:
    from core import memory
    return memory.STORE / "planner.json"       # у тестов — своя папка (data/brain/test)


# ---------------- хранение ----------------
def load() -> dict:
    with _lock:
        try:
            data = json.loads(path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = json.loads(json.dumps(DEFAULT))
        data.setdefault("version", 1)
        data.setdefault("categories", json.loads(json.dumps(DEFAULT["categories"])))
        data.setdefault("events", [])
        return data


def _save(data: dict) -> dict:
    data["version"] = int(data.get("version", 0)) + 1
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)                         # целиком или никак: окно не прочтёт половину файла
    return data


def _minutes(hhmm: str) -> int:
    h, m = (int(x) for x in str(hhmm).split(":"))
    return h * 60 + m


def _hhmm(minutes: int) -> str:
    minutes = max(0, min(24 * 60, int(minutes)))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _clean_event(ev: dict, categories) -> dict:
    """Проверка того, что пришло из окна или голосом: день, время, длина текста."""
    day = int(ev.get("day", 0))
    if not 0 <= day <= 6:
        raise ValueError("день недели — от 0 (пн) до 6 (вс)")
    start, end = _minutes(ev.get("start", "09:00")), _minutes(ev.get("end", "10:00"))
    if end <= start:
        end = min(start + 15, 24 * 60)
    cat = ev.get("cat") or ""
    if cat and cat not in {c["id"] for c in categories}:
        cat = ""
    return {"id": str(ev.get("id") or uuid.uuid4().hex[:12]), "day": day,
            "start": _hhmm(start), "end": _hhmm(end),
            "title": str(ev.get("title") or "Без названия").strip()[:120],
            "notes": str(ev.get("notes") or "").strip()[:2000],
            "cat": cat, "remind": bool(ev.get("remind"))}


def add(ev: dict) -> dict:
    with _lock:
        data = load()
        clean = _clean_event(ev, data["categories"])
        data["events"].append(clean)
        _save(data)
        return clean


def update(event_id: str, changes: dict) -> dict:
    with _lock:
        data = load()
        for i, ev in enumerate(data["events"]):
            if ev["id"] == event_id:
                merged = dict(ev, **{k: v for k, v in changes.items() if k != "id"}, id=event_id)
                data["events"][i] = _clean_event(merged, data["categories"])
                _save(data)
                return data["events"][i]
    raise KeyError(event_id)


def remove(event_id: str) -> bool:
    with _lock:
        data = load()
        left = [e for e in data["events"] if e["id"] != event_id]
        if len(left) == len(data["events"]):
            return False
        data["events"] = left
        _save(data)
        return True


def set_categories(categories: list) -> list:
    with _lock:
        data = load()
        clean = []
        for c in categories[:20]:
            color = str(c.get("color") or "#6e747a")
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                color = "#6e747a"
            clean.append({"id": str(c.get("id") or uuid.uuid4().hex[:8])[:24],
                          "name": str(c.get("name") or "Без названия").strip()[:40], "color": color})
        data["categories"] = clean
        ids = {c["id"] for c in clean}
        for ev in data["events"]:                   # удалённая категория — событие без категории
            if ev.get("cat") and ev["cat"] not in ids:
                ev["cat"] = ""
        _save(data)
        return clean


# ---------------- что спросят голосом ----------------
def day_events(day: int, data: dict = None) -> list:
    data = data or load()
    return sorted((e for e in data["events"] if e["day"] == day), key=lambda e: e["start"])


def _cat_name(data, cat_id):
    return next((c["name"] for c in data["categories"] if c["id"] == cat_id), "")


def day_items(date) -> list:
    """[(datetime начала, «название»)] на конкретную дату — для «что у меня сегодня»."""
    out = []
    for e in day_events(date.weekday()):
        h, m = (int(x) for x in e["start"].split(":"))
        out.append((datetime.combine(date, datetime.min.time()).replace(hour=h, minute=m), e["title"]))
    return out


def plan_for(day: int) -> str:
    data = load()
    items = day_events(day, data)
    if not items:
        return f"В {DAYS_ACC[day]} по плану ничего нет."
    parts = [f"{e['start']}–{e['end']} {e['title']}" for e in items[:12]]
    return f"В {DAYS_ACC[day]} по плану {len(items)}: " + "; ".join(parts) + "."


def now_and_next(now: datetime = None) -> str:
    """«Что у меня сейчас по плану» — что идёт и что следующее."""
    now = now or datetime.now()
    minute = now.hour * 60 + now.minute
    data = load()
    today = day_events(now.weekday(), data)
    current = [e for e in today if _minutes(e["start"]) <= minute < _minutes(e["end"])]
    upcoming = [e for e in today if _minutes(e["start"]) > minute]
    parts = []
    if current:
        e = current[0]
        parts.append(f"Сейчас по плану {e['title']}, до {e['end']}.")
    if upcoming:
        e = upcoming[0]
        parts.append(f"Дальше в {e['start']} — {e['title']}.")
    elif not current:
        for shift in range(1, 8):                        # сегодня всё — ближайшее в другие дни
            nxt = day_events((now.weekday() + shift) % 7, data)
            if nxt:
                when = "завтра" if shift == 1 else f"в {DAYS_ACC[(now.weekday() + shift) % 7]}"
                parts.append(f"Сегодня по плану больше ничего. Дальше {when} в {nxt[0]['start']} — "
                             f"{nxt[0]['title']}.")
                break
    return " ".join(parts) or "В планировщике пока пусто."


def due_reminders(now: datetime = None, ahead: int = 10, told: set = None) -> list:
    """События с «напомнить», которые начнутся через ahead минут. told — уже напомненные
    (ключ: дата+id), чтобы не повторять."""
    now = now or datetime.now()
    minute = now.hour * 60 + now.minute
    out = []
    for e in day_events(now.weekday()):
        if not e.get("remind"):
            continue
        left = _minutes(e["start"]) - minute
        key = f"{now:%Y-%m-%d}:{e['id']}"
        if 0 <= left <= ahead and (told is None or key not in told):
            out.append((e, left))
            if told is not None:
                told.add(key)
    return out


# ---------------- «добавь в планировщик…» голосом ----------------
WEEK_WORDS = {"каждый день": list(range(7)), "ежедневно": list(range(7)),
              "по будням": list(range(5)), "в будни": list(range(5)),
              "по выходным": [5, 6], "в выходные": [5, 6]}


def parse_slot(text: str):
    """«в среду и пятницу с 18 до 19:30 английский с Петей» → ([2, 4], "18:00", "19:30", "английский с Петей").

    None — не понял дни или время.
    """
    # Работаем с исходной фразой (регистр не трогаем — «с Петей» должно остаться «с Петей»),
    # вырезая только дни, время и служебные слова
    t = " " + text.replace("ё", "е").replace("Ё", "Е") + " "
    days = []
    for phrase, ds in WEEK_WORDS.items():
        if re.search(rf"\s{phrase}\s", t, re.I):
            days += ds
            t = re.sub(rf"\s{phrase}\s", " ", t, flags=re.I)
    for i, (full, short) in enumerate(zip(DAYS, DAYS_SHORT)):
        stem = full[:4] if i != 2 else "сред"
        pat = rf"\b(?:(?:в|во|по|каждую|каждый|каждое)\s+)?{stem}\w*\b|\b{short}\b"
        if re.search(pat, t, re.I):
            days.append(i)
            t = re.sub(pat, " ", t, flags=re.I)
    t = re.sub(r"(?<=\s)и(?=\s)", " ", t)            # «в среду и пятницу» — «и» между днями
    m = re.search(r"\bс\s*(\d{1,2})(?:[:. ](\d{2}))?\s*(?:до|по)\s*(\d{1,2})(?:[:. ](\d{2}))?\b", t, re.I)
    if m:
        start = int(m.group(1)) * 60 + int(m.group(2) or 0)
        end = int(m.group(3)) * 60 + int(m.group(4) or 0)
    else:
        m = re.search(r"\bв\s*(\d{1,2})(?:[:. ](\d{2}))?\b(?:\s+на\s+(полчаса|час|полтора часа|два часа|"
                      r"(\d+)\s*(?:минут\w*|час\w*)))?", t, re.I)
        if not m:
            return None
        start = int(m.group(1)) * 60 + int(m.group(2) or 0)
        span = {"полчаса": 30, "час": 60, "полтора часа": 90, "два часа": 120}.get(m.group(3) or "", 60)
        if m.group(4):
            span = int(m.group(4)) * (60 if "час" in m.group(3) else 1)
        end = start + span
    if not days or not 0 <= start < end <= 24 * 60:
        return None
    title = (t[:m.start()] + " " + t[m.end():])
    title = re.sub(r"\b(?:добавь|запиши|поставь|внеси|в\s+планировщик\w*|планировщик\w*|"
                   r"в\s+расписани\w*|на\s+неделю)\b", " ", title, flags=re.I)
    title = re.sub(r"\s+", " ", title).strip(" ,.")
    # Служебные слова остаются только по краям: «… в», «и …» — внутри названия их не трогаем
    while True:
        cut = re.sub(r"^(?:в|во|по|с|до|и|на)\s+|\s+(?:в|во|по|с|до|и|на)$", "", title, flags=re.I)
        if cut == title:
            break
        title = cut
    title = title or "Дело"
    return sorted(set(days)), _hhmm(start), _hhmm(end), title[:1].upper() + title[1:]


def add_by_voice(text: str) -> str:
    slot = parse_slot(text)
    if not slot:
        return ("Не понял, в какие дни и во сколько. Скажи, например: «добавь в планировщик в среду "
                "с 18 до 19 английский».")
    days, start, end, title = slot
    for d in days:
        add({"day": d, "start": start, "end": end, "title": title})
    names = ", ".join(DAYS_ACC[d] for d in days)
    return f"Добавил в планировщик: {title}, {start}–{end}, в {names}."


# ---------------- окно ----------------
def _edge() -> str:
    for p in (Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
              Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe"):
        if p.exists():
            return str(p)
    return ""


def open_window(port: int = PORT) -> str:
    """Окно без адресной строки (Edge --app) — выглядит как программа. Нет Edge — браузер."""
    url = f"http://127.0.0.1:{port}/"
    edge = _edge()
    if edge:
        subprocess.Popen([edge, f"--app={url}", "--window-size=1400,900"])
    else:
        import webbrowser
        webbrowser.open(url)
    return "Открываю планировщик."


# ---------------- сервер ----------------
_last_ping = [time.time()]


class Handler(BaseHTTPRequestHandler):
    server_version = "JarvisPlanner"

    def log_message(self, *args):          # без строки в консоль на каждый запрос
        pass

    def _host_ok(self) -> bool:
        # Чужая страница в браузере не должна достучаться до планировщика (подмена DNS):
        # принимаем только свой адрес в Host, а для изменений — и свой Origin
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return False
        origin = self.headers.get("Origin")
        if self.command != "GET" and origin and not re.match(r"https?://(127\.0\.0\.1|localhost)(:\d+)?$", origin):
            return False
        return True

    def _send(self, code: int, body, ctype="application/json; charset=utf-8"):
        raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 200_000:
            raise ValueError("слишком большой запрос")
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "forbidden"})
        _last_ping[0] = time.time()
        if self.path in ("/", "/index.html"):
            return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        if self.path == "/favicon.ico":                 # значок окна и панели задач
            return self._send(200, (PAGE.parent / "planner.ico").read_bytes(), "image/x-icon")
        if self.path == "/api/plan":
            return self._send(200, load())
        if self.path == "/api/version":
            return self._send(200, {"version": load()["version"], "app": "jarvis-planner"})
        return self._send(404, {"error": "not found"})

    def _change(self, fn):
        if not self._host_ok():
            return self._send(403, {"error": "forbidden"})
        _last_ping[0] = time.time()
        try:
            result = fn()
        except KeyError:
            return self._send(404, {"error": "нет такого события"})
        except (ValueError, TypeError) as e:
            return self._send(400, {"error": str(e)})
        return self._send(200, {"result": result, "version": load()["version"]})

    def do_POST(self):
        if self.path == "/api/events":
            return self._change(lambda: add(self._body()))
        return self._send(404, {"error": "not found"})

    def do_PATCH(self):
        m = re.fullmatch(r"/api/events/([\w-]+)", self.path)
        if m:
            return self._change(lambda: update(m.group(1), self._body()))
        return self._send(404, {"error": "not found"})

    def do_DELETE(self):
        m = re.fullmatch(r"/api/events/([\w-]+)", self.path)
        if m:
            return self._change(lambda: remove(m.group(1)) or (_ for _ in ()).throw(KeyError(m.group(1))))
        return self._send(404, {"error": "not found"})

    def do_PUT(self):
        if self.path == "/api/categories":
            return self._change(lambda: set_categories(self._body().get("categories") or []))
        return self._send(404, {"error": "not found"})


def make_shortcut(folder: Path = None) -> str:
    """Ярлык «Планировщик» (по умолчанию — на рабочий стол): окно без консоли, со своим значком."""
    import win32com.client
    folder = folder or Path(os.path.join(os.environ["USERPROFILE"], "Desktop"))
    try:
        from win32com.shell import shell, shellcon
        folder = Path(shell.SHGetFolderPath(0, shellcon.CSIDL_DESKTOPDIRECTORY, None, 0))
    except Exception:
        pass
    link = folder / "Планировщик.lnk"
    sc = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(link))
    pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    sc.TargetPath = str(pythonw if pythonw.exists() else ROOT / "планировщик.bat")
    sc.Arguments = "-m skills.planner" if pythonw.exists() else ""
    sc.WorkingDirectory = str(ROOT)
    sc.IconLocation = str(PAGE.parent / "planner.ico")
    sc.Description = "Планировщик недели — Джарвис"
    sc.Save()
    return str(link)


def running(port: int = PORT) -> bool:
    import urllib.request
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # свой сервер — мимо прокси
        with opener.open(f"http://127.0.0.1:{port}/api/version", timeout=1.5) as r:
            return json.loads(r.read()).get("app") == "jarvis-planner"
    except Exception:
        return False


def serve(port: int = PORT):
    """Поднять сервер в фоне. None — порт занят (значит, уже работает другой Джарвис/окно)."""
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        return None
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main():
    """planner.bat: окно без Джарвиса. Сервер гаснет, когда окно закрыли (нет отметок 2 минуты)."""
    if not running():
        httpd = serve()
        if httpd is None:
            print("Порт планировщика занят другой программой.")
            return
        open_window()
        _last_ping[0] = time.time()
        while time.time() - _last_ping[0] < 120:
            time.sleep(5)
        httpd.shutdown()
    else:
        open_window()


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT))
    main()
