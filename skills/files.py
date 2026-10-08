# -*- coding: utf-8 -*-
"""Найти файл на компьютере, открыть его или прислать на телефон.

Старый поиск смотрел только «Рабочий стол», «Документы» и «Загрузки» на C:,
а диск D:, где у хозяина лежат все проекты, не видел. Искал имя целиком —
«отчётом за сентябрь» не находило «Отчёт_сентябрь_2026.xlsx». И отвечал
одними именами: открыть найденное потом было нечем.

Как теперь:

* Список файлов строится в фоне и лежит в data/files_index.json. Обойти D:
  у хозяина — 19 секунд на 55 тысяч файлов (замер 05.10.2026), ждать столько
  на каждый вопрос нельзя; поиск по готовому списку мгновенный. Список
  обновляется при запуске Джарвиса и раз в два часа.

* Ищем по основам слов: «отчётом за сентябрь» → «отчет» + «сентя», и каждая
  основа должна встретиться в имени. Плюс латиницей — файлы часто называют
  транслитом. Слова о типе («таблицу», «презентацию», «фото») сужают поиск
  по расширению.

* Найденное запоминается: «открой второй», «пришли его на телефон».

Служебные папки (окружения Python, node_modules, игры Steam, модели) не
обходим: там десятки тысяч файлов, которые хозяину искать не нужно.
"""
import json
import os
import re
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "data" / "files_index.json"
REFRESH = 2 * 3600

SKIP_DIRS = {".venv", "venv", "env", "node_modules", ".git", "__pycache__", "SteamLibrary",
             "steamapps", "models", ".cache", "cache", "site-packages", "$RECYCLE.BIN",
             "System Volume Information", "Windows", "Program Files", "Program Files (x86)",
             "ProgramData", "AppData", "pytmp", "llm", "dist", "build", ".idea", ".vscode"}

KINDS = {
    r"таблиц|эксел|excel|xls": (".xlsx", ".xls", ".csv", ".ods"),
    r"документ|ворд|word|docx": (".docx", ".doc", ".odt", ".rtf", ".txt"),
    r"презентац|слайд|pptx": (".pptx", ".ppt", ".odp"),
    r"\bpdf\b|пдф": (".pdf",),
    r"фото|картинк|изображен|скриншот|снимок": (".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp"),
    r"видео|ролик|клип": (".mp4", ".mkv", ".mov", ".avi", ".webm"),
    r"музык|песн|трек|аудио": (".mp3", ".wav", ".flac", ".ogg", ".m4a"),
    r"архив|zip|rar": (".zip", ".rar", ".7z"),
}
STOP = {"файл", "файлы", "файла", "найди", "найти", "поищи", "мой", "мою", "мои", "мне",
        "у", "меня", "на", "в", "во", "за", "с", "со", "про", "где", "это", "этот", "тот",
        "компе", "компьютере", "диске", "папке", "под", "названием", "который", "которая"}
TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh",
    "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya"})

_files = []                 # [(имя в нижнем регистре, полный путь, дата изменения)]
_last = []                  # последняя выдача — для «открой второй»
last_at = 0.0               # когда искали: «открой второй» — про файлы или про видео
_lock = threading.Lock()
_building = threading.Event()


def _roots():
    roots = [Path.home()]
    for drive in "DEFGH":
        if Path(f"{drive}:\\").exists():
            roots.append(Path(f"{drive}:\\"))
    return roots


def _norm(text: str) -> str:
    return (text or "").lower().replace("ё", "е")


def build(roots=None):
    """Обойти диски и сохранить список файлов. Долго — вызывать в фоне."""
    _building.set()
    found = []
    try:
        stack = [str(r) for r in (roots or _roots())]
        while stack:
            d = stack.pop()
            try:
                with os.scandir(d) as it:
                    for e in it:
                        try:
                            if e.is_dir(follow_symlinks=False):
                                if e.name not in SKIP_DIRS and not e.name.startswith("."):
                                    stack.append(e.path)
                            else:
                                found.append((_norm(e.name), e.path, e.stat().st_mtime))
                        except OSError:
                            continue
            except OSError:
                continue
        with _lock:
            _files[:] = found
        INDEX.parent.mkdir(parents=True, exist_ok=True)
        INDEX.write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")
    finally:
        _building.clear()
    return len(found)


def _load():
    if _files or not INDEX.exists():
        return
    try:
        data = json.loads(INDEX.read_text(encoding="utf-8"))
        with _lock:
            _files[:] = [tuple(x) for x in data]
    except Exception:
        pass


def start_background():
    """Подгрузить готовый список и обновлять его в фоне."""
    _load()

    def loop():
        while True:
            fresh = INDEX.exists() and time.time() - INDEX.stat().st_mtime < REFRESH
            if not fresh:
                build()
            time.sleep(600)
    threading.Thread(target=loop, daemon=True).start()


def _stems(query: str):
    words = [w for w in re.findall(r"[\w-]+", _norm(query)) if w not in STOP and len(w) >= 2]
    kinds = set()
    stems = []
    for w in words:
        hit = next((exts for pat, exts in KINDS.items() if re.search(pat, w)), None)
        if hit:
            kinds.update(hit)
            continue
        # Русское слово — по основе («сентябрь» → «сентя»), латинское — целиком:
        # «requirements», обрезанное до «requi», цепляло «requires_grad.h»
        cyrillic = bool(re.search(r"[а-я]", w))
        stems.append(w[:5] if cyrillic and len(w) > 5 else w)
    return stems, kinds


def find(query: str, limit: int = 5):
    """[(имя, путь, дата)] лучших совпадений, свежие выше."""
    _load()
    stems, kinds = _stems(query)
    if not stems and not kinds:
        return []
    # «джарвиса» латиницей по правилам — «dzharv», а в путях пишут «jarvis»
    latin = [s.translate(TRANSLIT).replace("dzh", "j") for s in stems]
    with _lock:
        pool = list(_files)
    scored = []
    for name, path, mtime in pool:
        if kinds and not name.endswith(tuple(kinds)):
            continue
        # Каждое слово должно найтись в имени или хотя бы в пути: «jarvis readme»
        # — это README.md в папке jarvis. Совпадение в имени весит вдвое больше
        low_path = path.lower().replace("ё", "е")
        score = 0
        for s, l in zip(stems, latin):
            if s in name or (l and l in name):
                score += 2
            elif s in low_path or (l and l in low_path):
                score += 1
            else:
                score = -1
                break
        if score < 0 or (stems and score == 0):
            continue
        scored.append((score, mtime, os.path.basename(path), path))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [(n, p, m) for _, m, n, p in scored[:limit]]


def report(query: str) -> str:
    """Голосовой ответ на «найди файл …»."""
    global _last, last_at
    hits = find(query)
    if not hits:
        if _building.is_set() and not _files:
            return "Ещё составляю список файлов на дисках — спроси через минуту."
        return f"Не нашёл файлов по запросу «{query}»."
    _last, last_at = hits, time.time()
    from datetime import datetime
    lines = []
    for i, (name, path, mtime) in enumerate(hits, 1):
        folder = Path(path).parent
        short = f"{folder.drive}\\…\\{folder.name}" if len(folder.parts) > 3 else str(folder)
        lines.append(f"{i}. {name} — в {short}, от {datetime.fromtimestamp(mtime):%d.%m.%Y}")
    tail = " Скажи «открой первый» или «пришли второй на телефон»." if len(hits) > 1 else \
        " Скажи «открой его» или «пришли на телефон»."
    return f"Нашёл {len(hits)}: " + "; ".join(lines) + "." + tail


def last(n: int = 1):
    """Путь из последней выдачи по номеру (с единицы)."""
    if not _last:
        return None
    return _last[n - 1][1] if 1 <= n <= len(_last) else None


def open_found(n: int = 1) -> str:
    path = last(n)
    if not path:
        return "Сначала найдём файл — скажи, какой." if not _last else \
            f"В последнем поиске {len(_last)} файлов, назови номер от 1 до {len(_last)}."
    if not os.path.exists(path):
        return f"Файла {os.path.basename(path)} уже нет на месте."
    return open_safely(path)


# Запуск этого — уже не «открыть файл», а выполнить программу. Скачанный
# установщик голосом не запускаем: показываем в папке, дальше решает хозяин
RUNNABLE = {".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs", ".vbe", ".js", ".jse", ".wsf",
            ".scr", ".com", ".hta", ".reg"}


def open_safely(path: str) -> str:
    name = os.path.basename(path)
    if os.path.splitext(path)[1].lower() in RUNNABLE:
        import subprocess
        subprocess.Popen(["explorer.exe", "/select,", path])
        return f"{name} — программа или установщик: сам не запускаю, показал его в папке."
    os.startfile(path)
    return f"Открываю {name}."


_folder_cache = {"key": None, "data": {}}


def _folders() -> dict:
    """{папка: (имя строчными, самая свежая дата файла внутри)} — собирается раз на индекс."""
    with _lock:
        pool = list(_files)
    key = (len(pool), pool[0][1] if pool else "")
    if _folder_cache["key"] == key:
        return _folder_cache["data"]
    data = {}
    for _name, path, mtime in pool:
        d = os.path.dirname(path)
        while len(d) > 3:
            old = data.get(d)
            if old and old[1] >= mtime:
                break                        # выше уже учтено с датой не хуже
            data[d] = (os.path.basename(d).lower().replace("ё", "е"), max(mtime, old[1] if old else 0))
            d = os.path.dirname(d)
    _folder_cache.update(key=key, data=data)
    return data


def find_folders(query: str, limit: int = 5):
    """Папки по имени — из путей проиндексированных файлов: «папку jarvis», «проект tutorlab».

    Отдельного списка папок нет, но каждая папка с файлами встречается в их
    путях. Лучше — имя совпало целиком, путь короче, файлы в ней свежее.
    """
    _load()
    stems, _ = _stems(query)
    if not stems:
        return []
    latin = [s.translate(TRANSLIT).replace("dzh", "j") for s in stems]
    want = " ".join(stems)
    best = {d: m for d, (base, m) in _folders().items()
            if all(s in base or (l and l in base) for s, l in zip(stems, latin))}
    ranked = sorted(best.items(), key=lambda kv: (
        os.path.basename(kv[0]).lower() in (want, " ".join(latin)),     # имя целиком
        -kv[0].count(os.sep), kv[1]), reverse=True)
    return [d for d, _ in ranked[:limit]]


def open_folder(query: str) -> str:
    """«Открой папку jarvis» — в Проводнике."""
    hits = find_folders(query)
    if not hits:
        return f"Папку «{query}» не нашёл."
    import subprocess
    subprocess.Popen(["explorer.exe", hits[0]])
    more = f" Есть ещё похожие: {', '.join(hits[1:3])}." if len(hits) > 1 else ""
    return f"Открываю папку {hits[0]}.{more}"


def open_in_code(query: str) -> str:
    """«Открой проект jarvis в VS Code» — папкой, как проект."""
    import shutil
    import subprocess
    hits = find_folders(query)
    if not hits:
        return f"Папку проекта «{query}» не нашёл."
    exe = shutil.which("code") or next((str(p) for p in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft VS Code" / "Code.exe") if p.exists()), None)
    if not exe:
        return "VS Code не нашёл на компьютере."
    subprocess.Popen([exe, hits[0]], shell=exe.lower().endswith((".cmd", ".bat")))
    return f"Открываю {hits[0]} в VS Code."


def open_document(query: str) -> str:
    """«Открой документ резюме» — найти и сразу открыть лучший; остальные — по номеру."""
    global _last, last_at
    hits = find(query)
    if not hits:
        return f"Не нашёл файлов по запросу «{query}»."
    _last, last_at = hits, time.time()
    said = open_safely(hits[0][1])
    if len(hits) > 1:
        said += f" Нашёл ещё {len(hits) - 1} — скажи «открой второй», если не тот."
    return said


def latest_download() -> str:
    """«Открой последний скачанный файл» — самый свежий файл в «Загрузках».

    Становится «последним найденным»: дальше «пришли его на телефон» знает, о чём речь.
    """
    global _last, last_at
    folder = Path.home() / "Downloads"
    try:
        files = [p for p in folder.iterdir() if p.is_file() and not p.name.startswith(("~$", "."))
                 and p.suffix.lower() not in (".crdownload", ".part", ".tmp", ".partial", ".ini")]
    except OSError:
        files = []
    if not files:
        return "В «Загрузках» пусто."
    newest = max(files, key=lambda p: p.stat().st_mtime)
    _last, last_at = [(newest.name, str(newest), newest.stat().st_mtime)], time.time()
    return open_safely(str(newest))
