# -*- coding: utf-8 -*-
"""Руки Джарвиса: управление компьютером.

Программы не захардкожены: модуль собирает список всего, что установлено, и
запускает по нечёткому совпадению названия («открой стим», «запусти фотошоп»).

Список собирается из двух источников. Раньше был только один — ярлыки меню
«Пуск», — и живой тест 15.09.2026 показал дыру: Claude стоит из Microsoft Store,
ярлыка у Store-приложений нет, и Джарвис его «не находил», пытаясь открыть сайт
и угадывать пути в AppData. Теперь основной источник — Get-StartApps, полный
список приложений Windows, включая Store; ярлыки дополняют его путями к exe,
по которым потом находится процесс при закрытии.
"""
import os
import json
import re
import shutil
import subprocess
import ctypes
import difflib
import time
import webbrowser
from pathlib import Path
from datetime import datetime

import psutil

START_MENUS = [
    Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
]
CACHE = Path(__file__).resolve().parent.parent / "data" / "apps_index_v2.json"
CACHE_MAX_AGE = 24 * 3600          # старый список жил с 3 сентября и ни разу не обновлялся

# Как программу называют вслух → как искать в списке
ALIASES = {
    "браузер": "chrome", "хром": "chrome", "гугл хром": "chrome", "эдж": "edge",
    "блокнот": "notepad", "калькулятор": "calc", "проводник": "explorer",
    "диспетчер задач": "taskmgr", "паинт": "mspaint", "пейнт": "mspaint",
    "консоль": "cmd", "терминал": "wt", "пауэршелл": "powershell",
    "телеграм": "telegram", "телега": "telegram", "дискорд": "discord",
    "стим": "steam", "ворд": "word", "эксель": "excel",
    "вс код": "visual studio code", "вскод": "visual studio code",
    "vs code": "visual studio code", "vscode": "visual studio code",
    "визуал студио код": "visual studio code", "код": "visual studio code",
    "клод": "claude", "клауд": "claude",
    # «Напиши в поиске Cloud Code …» (05.10.2026): так распознаётся Claude Code
    "cloud code": "claude", "клод код": "claude", "клауд код": "claude", "claude code": "claude",
    "настройки": "ms-settings:", "панель управления": "control",
    # Модели зовут программы по-английски, а в русской Windows они по-русски:
    # на проверке 05.10.2026 «Calculator» не нашёлся, хотя Калькулятор был открыт
    "calculator": "калькулятор", "calc": "калькулятор", "notepad": "блокнот",
    "settings": "параметры", "explorer": "проводник", "file explorer": "проводник",
    "task manager": "диспетчер задач", "camera": "камера", "photos": "фотографии",
    "calendar": "календарь", "mail": "почта", "clock": "часы", "alarms": "часы",
    "snipping tool": "ножницы", "control panel": "панель управления",
    "command prompt": "командная строка", "terminal": "терминал",
    "яндекс браузер": "yandex", "яндекс": "yandex", "yandex browser": "yandex",
    # Игры зовут прозвищами и по-русски, а в Steam они по-английски
    "дота": "dota 2", "доту": "dota 2", "дотка": "dota 2", "дотку": "dota 2", "дота 2": "dota 2",
    "кс": "counter-strike 2", "кс2": "counter-strike 2", "контра": "counter-strike 2",
    "контру": "counter-strike 2", "каэс": "counter-strike 2", "пабг": "pubg", "пубг": "pubg",
    "гта": "grand theft auto v", "гта 5": "grand theft auto v", "фар край": "far cry",
    "фаркрай": "far cry", "майнкрафт": "minecraft", "майн": "minecraft", "раст": "rust",
    "апекс": "apex legends", "варфейс": "warface", "танки": "world of tanks",
}

# Одна и та же работа разными программами: «открой ворд», а Word не стоит —
# открываем то, что есть (WPS, LibreOffice), а не WordPad по похожему слову
EQUIVALENTS = {
    "word": ("microsoft word", "word", "wps writer", "libreoffice writer"),
    "excel": ("microsoft excel", "excel", "wps spreadsheets", "libreoffice calc"),
    "powerpoint": ("microsoft powerpoint", "powerpoint", "wps presentation", "libreoffice impress"),
    "ворд": ("microsoft word", "word", "wps writer", "libreoffice writer"),
    "эксель": ("microsoft excel", "excel", "wps spreadsheets", "libreoffice calc"),
    "поверпоинт": ("microsoft powerpoint", "powerpoint", "wps presentation", "libreoffice impress"),
    "презентацию": ("microsoft powerpoint", "powerpoint", "wps presentation", "libreoffice impress"),
    "таблицы": ("microsoft excel", "excel", "wps spreadsheets", "libreoffice calc"),
}

# Места Windows, а не программы: «открой настройки» — это Параметры, а не
# «Средства настройки WPS Office», которые находились по слову (проверка 08.10.2026)
PLACES = {
    "настройки": "ms-settings:", "параметры": "ms-settings:", "параметры windows": "ms-settings:",
    "настройки windows": "ms-settings:", "settings": "ms-settings:",
    "настройки звука": "ms-settings:sound", "параметры звука": "ms-settings:sound",
    "блютуз": "ms-settings:bluetooth", "bluetooth": "ms-settings:bluetooth",
    "вайфай": "ms-settings:network-wifi", "wi-fi": "ms-settings:network-wifi",
    "wifi": "ms-settings:network-wifi", "настройки сети": "ms-settings:network",
    "настройки экрана": "ms-settings:display", "дисплей": "ms-settings:display",
    "обновления": "ms-settings:windowsupdate", "центр обновления": "ms-settings:windowsupdate",
    "обновление windows": "ms-settings:windowsupdate",
    "установленные программы": "ms-settings:appsfeatures", "приложения": "ms-settings:appsfeatures",
    "принтеры": "ms-settings:printers", "питание": "ms-settings:powersleep",
    "обои": "ms-settings:personalization-background", "фон": "ms-settings:personalization-background",
    "загрузки": "shell:Downloads", "закачки": "shell:Downloads", "папку загрузки": "shell:Downloads",
    "документы": "shell:Personal", "мои документы": "shell:Personal", "папку документы": "shell:Personal",
    "рабочий стол": "shell:Desktop", "изображения": "shell:My Pictures", "картинки": "shell:My Pictures",
    "папку видео": "shell:My Video", "папку музыка": "shell:My Music",
    "корзину": "shell:RecycleBinFolder", "корзина": "shell:RecycleBinFolder",
    "этот компьютер": "shell:MyComputerFolder", "мой компьютер": "shell:MyComputerFolder",
    "диск c": "C:\\", "диск с": "C:\\", "диск d": "D:\\", "диск д": "D:\\",
}

# У некоторых программ процесс называется не так, как само приложение
PROCESS_NAMES = {
    "visual studio code": "code", "google chrome": "chrome", "microsoft edge": "msedge",
    "yandex": "browser", "яндекс браузер": "browser", "telegram desktop": "telegram",
}

# Служебные пункты меню «Пуск», которые не нужно открывать по названию программы
NOT_APPS = re.compile(r"uninstall|удал(ить|ение)|readme|справка|help|documentation|"
                      r"release notes|license|лицензи|website|веб-сайт", re.I)

# Слова вокруг названия: по ним программу не ищем
NOT_NAMES = {"открой", "открыть", "откройте", "запусти", "запустить", "включи", "включить",
             "покажи", "давай", "мне", "пожалуйста", "программу", "программа", "приложение",
             "приложуху", "файл", "папку", "документ", "окно", "что", "нибудь", "там"}

SITES = {
    "ютуб": "https://www.youtube.com", "youtube": "https://www.youtube.com",
    "гугл": "https://www.google.com", "google": "https://www.google.com",
    "почта": "https://mail.google.com", "гмейл": "https://mail.google.com",
    "gmail": "https://mail.google.com", "джимейл": "https://mail.google.com",
    "переводчик": "https://translate.yandex.ru", "карты": "https://yandex.ru/maps",
    "гитхаб": "https://github.com", "github": "https://github.com",
    "вк": "https://vk.com", "вконтакте": "https://vk.com", "vk": "https://vk.com",
    "твич": "https://twitch.tv", "twitch": "https://twitch.tv",
    "чат гпт": "https://chatgpt.com", "chatgpt": "https://chatgpt.com", "чатгпт": "https://chatgpt.com",
    "госуслуги": "https://www.gosuslugi.ru", "кинопоиск": "https://www.kinopoisk.ru",
    "рутуб": "https://rutube.ru", "rutube": "https://rutube.ru", "дзен": "https://dzen.ru",
    "озон": "https://www.ozon.ru", "ozon": "https://www.ozon.ru",
    "вайлдберриз": "https://www.wildberries.ru", "wildberries": "https://www.wildberries.ru",
    "вб": "https://www.wildberries.ru", "авито": "https://www.avito.ru", "avito": "https://www.avito.ru",
    "википедию": "https://ru.wikipedia.org", "википедия": "https://ru.wikipedia.org",
    "спотифай": "https://open.spotify.com", "spotify": "https://open.spotify.com",
    "яндекс почту": "https://mail.yandex.ru", "мейл": "https://mail.ru", "мэйл": "https://mail.ru",
    "хабр": "https://habr.com", "hh": "https://hh.ru", "хэдхантер": "https://hh.ru",
    "notion": "https://www.notion.so", "ноушн": "https://www.notion.so",
    "фигму": "https://www.figma.com", "figma": "https://www.figma.com", "канву": "https://www.canva.com",
    "canva": "https://www.canva.com", "сбер": "https://online.sberbank.ru",
    "сбербанк": "https://online.sberbank.ru", "тинькофф": "https://www.tbank.ru", "т банк": "https://www.tbank.ru",
    "яндекс музыку": "https://music.yandex.ru", "яндекс диск": "https://disk.yandex.ru",
    "гугл диск": "https://drive.google.com", "google диск": "https://drive.google.com",
    "колаб": "https://colab.research.google.com", "colab": "https://colab.research.google.com",
    "кагл": "https://www.kaggle.com", "kaggle": "https://www.kaggle.com",
    "инстаграм": "https://www.instagram.com", "instagram": "https://www.instagram.com",
    "тикток": "https://www.tiktok.com", "tiktok": "https://www.tiktok.com",
    "нетфликс": "https://www.netflix.com", "netflix": "https://www.netflix.com",
}
# Сайт — только если такой программы на компьютере нет: «открой клод» должно
# открыть приложение, а не вкладку, как вышло на живом тесте
SITE_FALLBACK = {"claude": "https://claude.ai", "telegram": "https://web.telegram.org",
                 "discord": "https://discord.com/app"}


# ---------------- список установленных программ ----------------
def _start_apps() -> list:
    """Get-StartApps: все приложения меню «Пуск», включая Microsoft Store."""
    cmd = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
           "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                             capture_output=True, timeout=40).stdout.decode("utf-8", "replace")
        data = json.loads(out) if out.strip() else []
        return data if isinstance(data, list) else [data]
    except Exception:
        return []


def _shortcut_target(lnk: Path) -> str:
    try:
        import win32com.client
        return win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(lnk)).TargetPath or ""
    except Exception:
        return ""


def build_app_index(force: bool = False) -> dict:
    """название → {name, aumid, lnk, exe}. Кэш на сутки."""
    if not force and CACHE.exists() and time.time() - CACHE.stat().st_mtime < CACHE_MAX_AGE:
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            pass
    index = {}
    for app in _start_apps():
        name, aumid = (app.get("Name") or "").strip(), (app.get("AppID") or "").strip()
        if name and aumid and not NOT_APPS.search(name):
            # У обычных программ AppID — это путь к exe: из него берётся имя процесса
            exe = Path(aumid).stem.lower() if aumid.lower().endswith(".exe") else ""
            index[name.lower()] = {"name": name, "aumid": aumid, "lnk": "", "exe": exe}
    for root in START_MENUS:
        if not root.exists():
            continue
        for lnk in root.rglob("*.lnk"):
            if NOT_APPS.search(lnk.stem):
                continue
            target = _shortcut_target(lnk)
            entry = index.setdefault(lnk.stem.lower(),
                                     {"name": lnk.stem, "aumid": "", "lnk": "", "exe": ""})
            entry["lnk"] = str(lnk)
            if target.lower().endswith(".exe"):
                entry["exe"] = Path(target).stem.lower()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return index


def _score(query: str, key: str) -> int:
    if key == query:
        return 100
    if key.startswith(query + " ") or query in key.split():
        return 90                                    # «telegram» → «telegram desktop»
    if key.startswith(query):
        return 80
    if f" {query}" in f" {key}":
        return 75
    if query in key:
        return 60
    ratio = difflib.SequenceMatcher(None, query, key).ratio()
    return int(ratio * 55) if ratio >= 0.62 else 0   # «cloud» → «claude»


_TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
})


def _forms(text: str) -> set:
    """Как сказано, по синониму и латиницей: «клод» → claude, «кодблокс» → codeblocks."""
    text = text.strip().lower()
    return {text, ALIASES.get(text, text), text.translate(_TRANSLIT)} - {""}


def find_app(name: str):
    """(запись, название) лучшего совпадения или (None, запрос).

    Сначала ищется сказанное целиком, и побеждает лучшее совпадение — так
    «калькулятор» находит Калькулятор Windows, а не LibreOffice Calc по синониму
    «calc». Если целиком не нашлось, разбираем фразу на слова: на показе
    02.10.2026 «открой текстовый документ в блокнот» осталось без ответа, хотя
    нужное слово в ней было. По отдельным словам берём только уверенные
    совпадения, иначе «открой мне что-нибудь» наугад запустит первое похожее.
    """
    raw = name.strip().lower()
    whole = _forms(raw)
    words = [w for w in re.findall(r"[\w-]+", raw) if len(w) >= 3 and w not in NOT_NAMES]
    pieces = set()
    for i in range(len(words)):
        for n in (2, 1):                      # «визуал студио», затем «блокнот»
            frag = " ".join(words[i:i + n])
            if frag and frag != raw:
                pieces |= _forms(frag)
    pieces -= whole

    def best(index):
        scored = [(_score(v, key), -len(key), key) for v in whole for key in index]
        scored += [(s, ln, key) for s, ln, key in
                   ((_score(v, key), -len(key), key) for v in pieces for key in index)
                   if s >= 75]                # по слову — только точное, не похожее
        scored = [s for s in scored if s[0] > 0]
        if not scored:
            return None
        return index[max(scored)[2]]

    entry = best(build_app_index())
    if entry is None and CACHE.exists() and time.time() - CACHE.stat().st_mtime > 60:
        entry = best(build_app_index(force=True))   # поставили недавно — обновим список сами
    return (entry, entry["name"]) if entry else (None, ALIASES.get(raw, raw))


def _launch(entry: dict):
    if entry.get("aumid"):
        # Через AppsFolder открывается что угодно: и Store-приложения, и обычные
        subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + entry["aumid"]])
    else:
        os.startfile(entry["lnk"])


def _already_open(entry: dict):
    """Окно этой программы, если она уже запущена: по процессу или по заголовку."""
    name = entry["name"].lower()
    procs = {p for p in (entry.get("exe"), PROCESS_NAMES.get(name), name.replace(" ", "")) if p}
    for hwnd, title, pname, _ in _visible_windows():
        if pname in procs or title.lower() == name or title.lower().endswith(" - " + name):
            return hwnd
    return None


def _exact(*names):
    """Запись из списка программ с ровно таким (или начинающимся так) названием."""
    index = build_app_index()
    for n in names:
        for key, entry in index.items():
            if (key == n or key.startswith(n + " ")) and "viewer" not in key:   # просмотрщик не редактор
                return entry
    return None


def _open_place(target: str) -> None:
    if target.startswith("ms-settings:"):
        os.startfile(target)
    else:
        subprocess.Popen(["explorer.exe", target])


def _launch_installed(name: str) -> str:
    """Игра или программа из «Установки и удаления программ», которой нет в «Пуске».

    «Запусти доту» не находилось: у игр Steam нет ярлыка в меню «Пуск», зато в
    реестре у них деинсталлятор steam://uninstall/<номер> — по тому же номеру
    Steam её и запускает.
    """
    try:
        from skills import programs
        p = programs.find(name)
    except Exception:
        return ""
    if not p:
        return ""
    m = re.search(r"steam://uninstall/(\d+)", p.get("uninstall") or "")
    if m:
        os.startfile(f"steam://rungameid/{m.group(1)}")
        return f"Запускаю {p['name']} через Steam."
    loc = p.get("location")
    if loc and os.path.isdir(loc):
        exes = [f for f in os.listdir(loc) if f.lower().endswith(".exe")
                and not re.search(r"unins|setup|update|crash|report|helper|install", f, re.I)]
        want = re.sub(r"[^a-z0-9]", "", p["name"].lower())
        exes.sort(key=lambda f: -difflib.SequenceMatcher(None, want, f.lower()[:-4]).ratio())
        if exes:
            os.startfile(os.path.join(loc, exes[0]))
            return f"Открываю {p['name']}."
    return ""


def _suggest(name: str) -> str:
    """Похожее из установленного — чтобы «не нашёл» не было тупиком."""
    index = build_app_index()
    close = difflib.get_close_matches(name.strip().lower(), list(index), n=2, cutoff=0.5)
    names = [index[k]["name"] for k in close]
    return f" Похожее из установленного: {', '.join(names)}." if names else ""


def _home_page() -> str:
    from core import config
    return "https://www.google.com" if config.CFG.get("search_engine") == "google" else "https://ya.ru"


def open_app(name: str, new_window: bool = False) -> str:
    low = name.strip().lower()
    if low in PLACES:
        try:
            _open_place(PLACES[low])
            return f"Открываю {name}."
        except Exception as e:
            return f"Не смог открыть {name}: {e}"
    if low in EQUIVALENTS:
        entry = _exact(*EQUIVALENTS[low])
        if entry:
            return open_app(entry["name"], new_window)
    if low in ("браузер", "хром", "гугл хром", "chrome", "google chrome"):
        # Chrome у хозяина не стоит, а по похожему слову открывался Comet
        entry = _exact("google chrome") if low != "браузер" else None
        if not entry:
            webbrowser.open(_home_page())
            return ("Chrome не установлен — открыл браузер по умолчанию." if low != "браузер"
                    else "Открываю браузер.")
        return open_app(entry["name"], new_window)
    if low in ("терминал", "консоль", "командная строка", "командную строку", "powershell", "пауэршелл"):
        # Windows Terminal стоит не у всех — тогда PowerShell, а не «Git CMD» по похожему слову
        entry = _exact("терминал", "windows terminal", "windows powershell")
        if entry:
            return open_app(entry["name"], new_window)
        os.startfile("powershell.exe")
        return "Открываю PowerShell."
    entry, display = find_app(name)
    if entry:
        # Уже открыта — выводим вперёд, а не плодим копию. Проверка 05.10.2026:
        # мозг сказал «открой калькулятор», когда тот был открыт, Windows открыла
        # второе окно, и дальше кнопки нажимались не там, где хозяин смотрел
        hwnd = None if new_window else _already_open(entry)
        if hwnd:
            from skills.desktop import focus_window
            import win32gui
            focus_window(win32gui.GetWindowText(hwnd) or display)
            return f"{display} уже открыт — вывел вперёд."
        try:
            _launch(entry)
            return f"Открываю {display}."
        except Exception as e:
            return f"Не смог открыть {display}: {e}"
    query = display
    if shutil.which(query):                          # системные: notepad, calc, cmd
        os.startfile(shutil.which(query))
        return f"Открываю {query}."
    if low in SITES:
        return open_site(low)
    if query in SITE_FALLBACK:
        webbrowser.open(SITE_FALLBACK[query])
        return f"Программы {name} на компьютере нет — открыл сайт."
    try:
        launched = _launch_installed(name)
    except Exception as e:
        launched = f"Не смог запустить {name}: {e}"
    if launched:
        return launched
    # «открой стима», «зайди в дискорда» — в падеже: пробуем основу, но только
    # если она — известное прозвище, а не случайно похожее слово
    for cut in ("ом", "ой", "ах", "у", "а", "е", "ы", "и"):
        base = low[:-len(cut)]
        if low.endswith(cut) and len(base) >= 3 and (base in ALIASES or base in SITES or base in PLACES):
            return open_app(base, new_window)
    return f"Не нашёл программу «{name}» среди установленных.{_suggest(name)}"


def open_site(what: str) -> str:
    url = SITES.get(what.strip().lower())
    if not url:
        w = what.strip()
        if w.startswith("http"):
            url = w
        elif "." in w and " " not in w:
            url = "https://" + w
        else:
            url = "https://www.google.com/search?q=" + w
    webbrowser.open(url)
    return f"Открываю {what}."


SEARCH = {
    "yandex": ("https://ya.ru/search/?text=", "в Яндексе"),
    "google": ("https://www.google.com/search?q=", "в Google"),
}
_last_search = {"query": "", "at": 0.0}     # чтобы «а теперь в яндексе» повторило запрос


def engine_of(word: str) -> str:
    """«яндексе», «гугл», «google» → yandex | google."""
    return "google" if re.search(r"гугл|google", word.lower()) else "yandex"


def search_web(query: str, engine: str = "") -> str:
    """Поиск в браузере. Где — из настроек (search_engine), если не сказано явно.

    Запрос кодируется для адреса: «рецепт R&B» без этого обрывался на «&».
    """
    from urllib.parse import quote_plus
    from core import config
    engine = engine or config.CFG.get("search_engine", "yandex")
    url, where = SEARCH.get(engine, SEARCH["yandex"])
    webbrowser.open(url + quote_plus(query))
    _last_search.update(query=query, at=time.time())
    return f"Ищу {where}: {query}"


def set_search_engine(engine: str) -> str:
    """Запомнить поисковик насовсем и повторить там последний запрос, если он был недавно."""
    from core import config
    config.update_setting("search_engine", engine)
    where = SEARCH[engine][1]
    if _last_search["query"] and time.time() - _last_search["at"] < 600:
        search_web(_last_search["query"], engine)
        return f"Теперь ищу {where}. Повторил: «{_last_search['query']}»."
    return f"Теперь ищу {where}."


def is_cloaked(hwnd) -> bool:
    """Окно «спит»: Windows числит его видимым, но на экране его нет.

    Так ведут себя приложения из Store после сворачивания — Калькулятор,
    Параметры, «Microsoft Text Input Application». Без этой проверки Джарвис
    перечислял их в «что открыто» и считал запущенными.
    """
    value = ctypes.c_int(0)
    try:
        ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(value),
                                                   ctypes.sizeof(value))   # DWMWA_CLOAKED
    except Exception:
        return False
    return value.value != 0


def _visible_windows():
    """(hwnd, заголовок, имя процесса без .exe, pid) всех видимых окон верхнего уровня."""
    import win32gui
    import win32process
    out = []

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd) or win32gui.GetWindow(hwnd, 4):   # 4 = владелец
            return
        if is_cloaked(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title or title == "Program Manager":                             # сам рабочий стол
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            pname = psutil.Process(pid).name().lower().removesuffix(".exe")
        except Exception:
            return
        out.append((hwnd, title, pname, pid))

    win32gui.EnumWindows(cb, None)
    return out


def close_app(name: str) -> str:
    """Закрыть программу — как крестиком, чтобы она успела предложить сохранить.

    Раньше процесс просто убивался: несохранённое пропадало молча. И искался
    только по имени процесса, поэтому «Visual Studio Code» не закрывался —
    его процесс называется Code.exe (так вышло на живом тесте).

    Порядок: сначала по имени процесса (из ярлыка программы или прямо по
    названию), по заголовку окна — только если процесс не нашёлся: иначе
    «закрой telegram» закрыл бы и браузер со вкладкой «Telegram Web».
    """
    import win32con
    import win32gui

    entry, display = find_app(name)
    raw = name.strip().lower()
    query = ALIASES.get(raw, raw)
    # Заголовок окна сравнивается со всеми вариантами названия: у Store-приложений
    # окно держит ApplicationFrameHost, и по процессу его не найти — только по
    # заголовку «Калькулятор», который с синонимом «calc» не совпал бы
    titles = {raw, query} | ({entry["name"].lower()} if entry else set())
    titles = {t for t in titles if len(t) >= 4}
    procs = {query.replace(" ", ""), query.split()[0]}
    if entry:
        low = entry["name"].lower()
        procs |= {low.replace(" ", ""), low.split()[0]}
        if entry.get("exe"):
            procs.add(entry["exe"])
        if low in PROCESS_NAMES:
            procs.add(PROCESS_NAMES[low])
    if query in PROCESS_NAMES:
        procs.add(PROCESS_NAMES[query])
    procs = {p for p in procs if len(p) >= 3}
    shell = {"explorer", "dwm", "python", "pythonw", "powershell", "cmd", "conhost"}

    windows = _visible_windows()
    by_process = [w for w in windows if w[2] in procs and w[2] not in shell]
    targets = by_process or [w for w in windows
                             if any(t in w[1].lower() for t in titles) and w[2] not in shell]
    if not targets:
        # Окон нет, но процесс может жить в трее
        tray = [p for p in psutil.process_iter(["name"])
                if (p.info["name"] or "").lower().removesuffix(".exe") in procs
                and (p.info["name"] or "").lower().removesuffix(".exe") not in shell]
        if not tray:
            return f"Не нашёл запущенную программу «{name}»."
        for p in tray:
            try:
                p.terminate()
            except Exception:
                pass
        return f"Закрыл {display}: окна у него не было, работал в фоне."

    for hwnd, *_ in targets:
        try:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        except Exception:
            pass
    time.sleep(1.5)
    still = [w for w in _visible_windows() if w[0] in {t[0] for t in targets}]
    if still:
        return (f"Попросил {display} закрыться, но окно ещё открыто — наверное, программа "
                "спрашивает, сохранить ли изменения.")
    return f"Закрыл {display}."


# ---------------- звук ----------------
def _volume_iface():
    """Свежий pycaw отдаёт готовый EndpointVolume; на старом — активируем вручную."""
    from pycaw.utils import AudioUtilities
    dev = AudioUtilities.GetSpeakers()
    if hasattr(dev, "EndpointVolume"):
        return dev.EndpointVolume
    from ctypes import cast, POINTER
    from comtypes import CLSCTX_ALL
    from pycaw.api.endpointvolume import IAudioEndpointVolume
    iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(iface, POINTER(IAudioEndpointVolume))


def set_volume(percent: int) -> str:
    percent = max(0, min(100, int(percent)))
    try:
        _volume_iface().SetMasterVolumeLevelScalar(percent / 100, None)
        return f"Громкость {percent} процентов."
    except Exception as e:
        return f"Не вышло со звуком: {e}"


def get_volume() -> str:
    try:
        return f"Громкость {round(_volume_iface().GetMasterVolumeLevelScalar()*100)} процентов."
    except Exception as e:
        return f"Не вышло: {e}"


def change_volume(delta: int) -> str:
    try:
        cur = _volume_iface().GetMasterVolumeLevelScalar() * 100
        return set_volume(int(cur + delta))
    except Exception as e:
        return f"Не вышло: {e}"


def mute(state: bool = True) -> str:
    try:
        _volume_iface().SetMute(1 if state else 0, None)
        return "Звук выключен." if state else "Звук включён."
    except Exception as e:
        return f"Не вышло: {e}"


def audio_activity(settle: float = 0.25) -> dict:
    """Кто сейчас звучит: {имя процесса: громкость от 0 до 1}.

    Windows ведёт счётчик громкости по каждому приложению, и это единственный
    способ проверить, играет ли на самом деле видео в браузере. На показе
    05.10.2026 Джарвис трижды отчитался «видео остановлено», пока оно играло:
    он нажимал клавишу и верил, что сработало. Теперь он может послушать.

    Мгновенное значение скачет (в тишине между словами ноль), поэтому берём
    максимум за четверть секунды.
    """
    from ctypes import POINTER, cast
    from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
    loud = {}
    deadline = time.time() + settle
    while True:
        for s in AudioUtilities.GetAllSessions():
            if not s.Process or s.State != 1:          # 1 = сессия активна
                continue
            try:
                meter = cast(s._ctl.QueryInterface(IAudioMeterInformation),
                             POINTER(IAudioMeterInformation))
                name = s.Process.name().lower().removesuffix(".exe")
                loud[name] = max(loud.get(name, 0.0), float(meter.GetPeakValue()))
            except Exception:
                continue
        if time.time() >= deadline:
            return loud
        time.sleep(0.05)


def sound_level(hint: str = "") -> float:
    """Громкость конкретного приложения (или самая громкая из всех)."""
    loud = audio_activity()
    if not loud:
        return 0.0
    if hint:
        hint = hint.lower().removesuffix(".exe")
        return max((v for k, v in loud.items() if hint in k or k in hint), default=0.0)
    return max(loud.values())


def who_sounds() -> str:
    """Человеческий ответ на «что сейчас играет» — по звуку, а не по догадке."""
    loud = {k: v for k, v in audio_activity().items() if v > 0.001}
    mine = {"python", "pythonw"}                       # свой же голос не считаем
    loud = {k: v for k, v in loud.items() if k not in mine}
    if not loud:
        return "Тихо, ничего не звучит."
    top = sorted(loud.items(), key=lambda kv: -kv[1])
    return "Звук идёт из: " + ", ".join(name for name, _ in top[:3]) + "."


def media_key(key: str) -> str:
    """Управление любым плеером: пауза, следующий трек и т.д.

    Отчёт честный: клавиша глобальная, и её может не принять никто (браузер
    забирает её только когда играет). Поэтому сравниваем звук до и после.
    """
    import win32api
    import win32con
    codes = {"play": 0xB3, "pause": 0xB3, "next": 0xB0, "prev": 0xB1, "stop": 0xB2}
    vk = codes.get(key)
    if not vk:
        return "Не знаю такую команду плеера."
    before = sound_level()
    win32api.keybd_event(vk, 0, 0, 0)
    win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(0.6)
    after = sound_level()
    done = {"play": "Играю.", "pause": "Пауза.", "next": "Следующий.",
            "prev": "Предыдущий.", "stop": "Остановил."}[key]
    if key in ("pause", "stop"):
        if before <= 0.001:
            return "Ничего и не звучало."
        if after > 0.001:
            return ("Нажал клавишу паузы, но звук идёт дальше — плеер её не принял. "
                    "Для видео в браузере нужен инструмент video.")
    return done


# ---------------- система ----------------
def system_info() -> str:
    cpu = psutil.cpu_percent(interval=0.4)
    mem = psutil.virtual_memory()
    parts = [f"Процессор загружен на {cpu:.0f} процентов",
             f"памяти занято {mem.percent:.0f} процентов"]
    for d in psutil.disk_partitions():
        if "cdrom" in d.opts or not d.fstype:
            continue
        try:
            u = psutil.disk_usage(d.mountpoint)
            parts.append(f"на диске {d.device[0]} свободно {u.free/2**30:.0f} гигабайт")
        except Exception:
            pass
    return ", ".join(parts) + "."


def battery() -> str:
    b = psutil.sensors_battery()
    if not b:
        return "Батареи нет — это стационарный компьютер."
    return f"Заряд {b.percent} процентов" + (", от сети." if b.power_plugged else ".")


def top_processes(n: int = 5) -> str:
    procs = []
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            procs.append((p.info["name"], p.info["memory_info"].rss))
        except Exception:
            pass
    procs.sort(key=lambda x: -x[1])
    top = [f"{nm} — {m/2**20:.0f} мегабайт" for nm, m in procs[:n]]
    return "Больше всего памяти едят: " + ", ".join(top) + "."


def screenshot() -> str:
    """Скриншот всех экранов. Путь возвращается — его же читает зрение Джарвиса."""
    from PIL import ImageGrab
    out = Path.home() / "Pictures" / f"jarvis_{datetime.now():%Y%m%d_%H%M%S}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab(all_screens=True).save(out)
    return str(out)


def lock_screen() -> str:
    ctypes.windll.user32.LockWorkStation()
    return "Блокирую."


def shutdown(minutes: int = 0) -> str:
    subprocess.run(["shutdown", "/s", "/t", str(int(minutes) * 60)], capture_output=True)
    return f"Выключаю компьютер через {minutes} минут." if minutes else "Выключаю компьютер."


def reboot() -> str:
    subprocess.run(["shutdown", "/r", "/t", "0"], capture_output=True)
    return "Перезагружаю."


def cancel_shutdown() -> str:
    subprocess.run(["shutdown", "/a"], capture_output=True)
    return "Выключение отменено."


def sleep_pc() -> str:
    subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], capture_output=True)
    return "Ухожу в сон."


def clipboard_get() -> str:
    import win32clipboard
    try:
        win32clipboard.OpenClipboard()
        data = win32clipboard.GetClipboardData()
        win32clipboard.CloseClipboard()
        return data
    except Exception:
        return ""


def clipboard_set(text: str) -> str:
    import win32clipboard
    win32clipboard.OpenClipboard()
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardText(text)
    win32clipboard.CloseClipboard()
    return "Скопировал в буфер."


def find_file(pattern: str, where: str = None, limit: int = 8) -> str:
    """Поиск по всем дискам — см. skills/files.py (старый смотрел только три папки на C:)."""
    from skills import files as F
    return F.report(pattern)


def what_time() -> str:
    now = datetime.now()
    days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
              "августа", "сентября", "октября", "ноября", "декабря"]
    def form(n, one, few, many):
        if n % 10 == 1 and n % 100 != 11:
            return one
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return few
        return many

    # «2 часа 43 минуты», а не «2 часов 43 минут»
    return (f"Сейчас {now.hour} {form(now.hour, 'час', 'часа', 'часов')} "
            f"{now.minute} {form(now.minute, 'минута', 'минуты', 'минут')}, "
            f"{days[now.weekday()]}, {now.day} {months[now.month-1]}.")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core import config
    config.setup_console()
    idx = build_app_index(force=True)
    print(f"Проиндексировано программ: {len(idx)}")
    print("Примеры:", ", ".join(list(idx)[:14]))
    print(what_time())
    print(system_info())
    print(get_volume())
