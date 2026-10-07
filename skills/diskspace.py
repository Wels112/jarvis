# -*- coding: utf-8 -*-
"""Что занимает место на диске — словами, которые человек узнает.

05.10.2026 Джарвис предупредил, что на C: осталось 1,9 ГБ, и предложил убрать
временные файлы — а их там были сотни мегабайт. Место съедали Dota 2 (74 ГБ),
Far Cry 5 (26 ГБ) и кэши лаунчеров (15 ГБ), и об этом он не знал. Помощь —
сказать, куда ушло место и что с этим можно сделать.

* Обход C: — около 80 секунд (557 тысяч файлов, замер 07.10.2026), поэтому он
  идёт в фоне: при запуске и раз в шесть часов; итог — в data/disk_usage.json.
  «Что занимает место» отвечается мгновенно по готовому замеру.
* Папки-«контейнеры» (Program Files, AppData, steamapps…) раскрываются до того,
  что человек узнает: игра Steam — по имени из её манифеста («Dota 2», а не
  «dota 2 beta»), известные кэши — словами («кэш патчей Ubisoft»).
* Ссылки и точки соединения не считаются: игра, перенесённая на D: со ссылкой
  на старом месте, на C: больше не числится.
"""
import json
import ntpath
import os
import re
import shutil
import stat
import threading
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "disk_usage.json"
REFRESH = 6 * 3600
DEPTH = 7                   # глубже — только суммой: «C:\…\Steam\steamapps\common\Игра» — это 5
REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
GB = 2 ** 30

HOME = Path.home()
LOCAL = Path(os.environ.get("LOCALAPPDATA") or HOME / "AppData" / "Local")
PROGRAMDATA = Path(os.environ.get("PROGRAMDATA") or "C:/ProgramData")
WINDIR = Path(os.environ.get("SYSTEMROOT") or "C:/Windows")

# Папки, имя которых человеку ничего не говорит: смотрим, что внутри
CONTAINERS = {"program files", "program files (x86)", "programdata", "users", "appdata",
              "local", "roaming", "locallow", "programs", "games", "steam", "steamapps",
              "common", "steamlibrary", "epic games", "gog games", "riot games",
              HOME.name.lower()}

# Известные места — словами. Вид подсказывает, что с ними делать
KNOWN = {
    PROGRAMDATA / "Ubisoft" / "Ubisoft Game Launcher" / "patch": ("кэш патчей Ubisoft", "cache"),
    PROGRAMDATA / "NVIDIA Corporation" / "NVIDIA App" / "UpdateFramework": ("скачанные обновления NVIDIA", "cache"),
    LOCAL / "NVIDIA" / "DXCache": ("кэш шейдеров NVIDIA", "cache"),
    LOCAL / "Temp": ("временные файлы", "cache"),
    HOME / "Downloads": ("папка «Загрузки»", "user"),
    HOME / "Desktop": ("Рабочий стол", "user"),
    HOME / "Documents": ("Документы", "user"),
    HOME / "Videos": ("папка «Видео»", "user"),
    HOME / "Pictures": ("Изображения", "user"),
    HOME / "Music": ("Музыка", "user"),
    WINDIR: ("сама Windows", "system"),
}
GAME_PARENTS = {"common", "games", "gog games", "epic games", "riot games"}

_state = {"data": None}
_lock = threading.Lock()
_running = threading.Event()


def _key(p) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


KNOWN_BY_KEY = {_key(p): v for p, v in KNOWN.items()}


def scan(drive: str = "C:") -> dict:
    """Обойти диск и сложить размеры по папкам. Долго — вызывать в фоне."""
    root = drive.rstrip("\\") + "\\"
    sizes = defaultdict(int)
    big_files = []
    t0 = time.time()

    def walk(path, parts):
        try:
            it = os.scandir(path)
        except OSError:
            return
        with it:
            for e in it:
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if getattr(st, "st_file_attributes", 0) & REPARSE:
                    continue        # ссылка: настоящие файлы лежат в другом месте
                if stat.S_ISDIR(st.st_mode):
                    walk(e.path, parts + [e.name])
                    continue
                for d in range(min(len(parts), DEPTH) + 1):
                    sizes[ntpath.join(root, *parts[:d])] += st.st_size
                if st.st_size >= GB and len(parts) <= 1:
                    big_files.append((e.path, st.st_size))   # файл подкачки, гибернации

    walk(root, [])
    usage = shutil.disk_usage(root)
    data = {"drive": drive, "at": time.time(), "seconds": round(time.time() - t0),
            "total": usage.total, "free": usage.free, "counted": sizes.get(root, 0),
            "sizes": dict(sizes), "big_files": big_files}
    with _lock:
        _state["data"] = data
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return data


def _load():
    with _lock:
        if _state["data"] is not None:
            return _state["data"]
    try:
        data = json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    with _lock:
        _state["data"] = data
    return data


def refresh(force: bool = False):
    """Пересчитать в фоне, если замер устарел. Два обхода сразу не запускаем."""
    data = _load()
    fresh = data and time.time() - data.get("at", 0) < REFRESH
    if (fresh and not force) or _running.is_set():
        return

    def run():
        _running.set()
        try:
            scan()
        except Exception:
            pass
        finally:
            _running.clear()
    threading.Thread(target=run, daemon=True).start()


def start_background():
    """При запуске и дальше раз в шесть часов — замер в фоне."""
    def loop():
        while True:
            refresh()
            time.sleep(600)
    threading.Thread(target=loop, daemon=True).start()


def _steam_names(common: str) -> dict:
    """installdir → название игры из манифестов Steam (steamapps\\appmanifest_*.acf)."""
    names = {}
    steamapps = ntpath.dirname(common)
    try:
        for f in os.listdir(steamapps):
            if f.startswith("appmanifest_") and f.endswith(".acf"):
                text = Path(steamapps, f).read_text(encoding="utf-8", errors="replace")
                d = re.search(r'"installdir"\s+"([^"]+)"', text)
                n = re.search(r'"name"\s+"([^"]+)"', text)
                if d and n:
                    names[d.group(1).lower()] = n.group(1)
    except OSError:
        pass
    return names


def _label(path: str):
    """(название, вид) для папки; вид: game, cache, user, system, program."""
    known = KNOWN_BY_KEY.get(_key(path))
    if known:
        return known
    name = ntpath.basename(path)
    parent = ntpath.basename(ntpath.dirname(path)).lower()
    if parent == "common" and ntpath.basename(ntpath.dirname(ntpath.dirname(path))).lower() == "steamapps":
        return _steam_names(ntpath.dirname(path)).get(name.lower(), name), "game"
    if parent == "workshop":
        return "моды из мастерской Steam", "game"
    if parent in GAME_PARENTS:
        return name, "game"
    if parent in ("program files", "program files (x86)", "programs"):
        return name, "program"
    return name, "program"


def hogs(data: dict, top: int = 6, min_gb: float = 1.0) -> list:
    """Самые большие узнаваемые папки: [(название, вид, путь, байты)]."""
    sizes = data["sizes"]
    kids = defaultdict(list)
    for p in sizes:
        parent = ntpath.dirname(p)
        if parent != p:
            kids[parent].append(p)
    # Папки, внутри которых лежит известное место: «Ubisoft» — это не программа
    # на 8 ГБ, а кэш патчей в её глубине; туда и спускаемся
    present = {_key(p) for p in sizes}
    known_inside = set()
    for kp in KNOWN_BY_KEY:
        if kp in present:
            parent = ntpath.dirname(kp)
            while parent != ntpath.dirname(parent):
                known_inside.add(parent)
                parent = ntpath.dirname(parent)
    out = []

    def visit(path):
        for k in sorted(kids.get(path, []), key=lambda p: -sizes[p]):
            if sizes[k] < min_gb * GB:
                break
            name, kk = ntpath.basename(k).lower(), _key(k)
            if kk in KNOWN_BY_KEY:
                label, kind = KNOWN_BY_KEY[kk]
                out.append((label, kind, k, sizes[k]))
            elif kids.get(k) and (name in CONTAINERS or kk in known_inside
                                  or name == "workshop"):   # моды Steam — суммой по игре
                visit(k)
            else:
                label, kind = _label(k)
                out.append((label, kind, k, sizes[k]))

    root = data["drive"].rstrip("\\") + "\\"
    visit(root)
    for path, size in data.get("big_files", []):
        name = ntpath.basename(path).lower()
        label = {"pagefile.sys": "файл подкачки", "hiberfil.sys": "файл гибернации",
                 "swapfile.sys": "файл подкачки приложений"}.get(name, ntpath.basename(path))
        out.append((label, "system", path, size))
    # «моды из мастерской» могли попасть несколько раз — по одному на игру; складываем
    merged = {}
    for label, kind, path, size in out:
        if label in merged and kind == "game" and label.startswith("моды"):
            merged[label] = (label, kind, merged[label][2], merged[label][3] + size)
        else:
            merged.setdefault(label, (label, kind, path, size))
    return sorted(merged.values(), key=lambda x: -x[3])[:top]


def _gb(n: float) -> str:
    """«74», «7,8», но «8», а не «8,0»: вслух «восемь запятая ноль» звучит нелепо."""
    v = n / GB
    if v >= 10 or abs(v - round(v)) < 0.05:
        return f"{v:.0f}"
    return f"{v:.1f}".replace(".", ",")


def report(drive: str = "C:", with_free: bool = True) -> str:
    """Голосовой ответ на «что занимает место». with_free=False — без «свободно столько-то»,
    когда это уже сказано рядом."""
    data = _load()
    if not data:
        refresh()
        return "Ещё считаю, что занимает место на диске, — это около минуты. Спроси чуть позже."
    try:
        usage = shutil.disk_usage(data["drive"].rstrip("\\") + "\\")
        free, total = usage.free, usage.total
    except OSError:
        free, total = data["free"], data["total"]
    items = hogs(data, top=5)
    age_h = (time.time() - data.get("at", 0)) / 3600
    when = "" if age_h < 1 else f" (замер {age_h:.0f} ч назад)"
    parts = [f"{label} — {_gb(size)} ГБ" for label, _k, _p, size in items]
    head = f"На диске {data['drive'][0]} свободно {_gb(free)} из {_gb(total)} ГБ. " if with_free else ""
    text = head + f"Больше всего на {data['drive'][0]} занимают{when}: " + "; ".join(parts) + "."
    kinds = {k for _l, k, _p, _s in items}
    if "cache" in kinds:
        text += " Кэши можно почистить — скажи «почисти диск»."
    if "game" in kinds:
        text += " Игры можно перенести на другой диск."
    if age_h > REFRESH / 3600:
        refresh()
    return text


def top_phrase(n: int = 2) -> str:
    """Коротко для предупреждения: «Больше всего — Dota 2 (74 ГБ) и Far Cry 5 (26 ГБ)»."""
    data = _load()
    if not data:
        return ""
    items = hogs(data, top=n)
    if not items:
        return ""
    parts = [f"{label} ({_gb(size)} ГБ)" for label, _k, _p, size in items]
    return "Больше всего места занимают " + " и ".join(parts) + "."
