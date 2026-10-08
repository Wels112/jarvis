# -*- coding: utf-8 -*-
"""Управление окнами, клавиатурой и браузером — «руки» поверх любого приложения.

Почему не Selenium/Playwright: они поднимают отдельный чистый браузер, где нет
твоих залогиненных сессий, и весят сотни мегабайт. Здесь Джарвис работает с тем
самым окном, что открыто у тебя на экране — переключает вкладки, листает,
печатает. Ровно то, что ты сделал бы руками, только голосом.
"""
import sys
import time
from pathlib import Path

import win32api
import win32con
import win32gui
import win32process
import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BROWSERS = ("chrome", "msedge", "firefox", "browser", "opera", "brave", "yandex", "comet")

VK = {
    "enter": 0x0D, "esc": 0x1B, "tab": 0x09, "space": 0x20, "backspace": 0x08,
    "delete": 0x2E, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23, "pgup": 0x21, "pgdn": 0x22, "f5": 0x74,
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
}


# ---------------- клавиатура ----------------
def _tap(vk: int):
    win32api.keybd_event(vk, 0, 0, 0)
    win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)


def hotkey(*keys: str) -> str:
    """hotkey('ctrl','t') — новая вкладка. Модификаторы держатся, последняя клавиша тапается."""
    codes = []
    for k in keys:
        k = k.lower()
        codes.append(VK.get(k, ord(k.upper()) if len(k) == 1 else 0))
    for c in codes[:-1]:
        win32api.keybd_event(c, 0, 0, 0)
    _tap(codes[-1])
    for c in reversed(codes[:-1]):
        win32api.keybd_event(c, 0, win32con.KEYEVENTF_KEYUP, 0)
    return "ok"


# ---- SendInput: единственный способ напечатать любой символ без оглядки на раскладку ----
#
# Раньше печать шла через keybd_event, и русский текст превращался в мусор:
# у keybd_event код символа — ОДИН байт, а у кириллицы коды за 1000. Латиница
# и цифры проходили, поэтому ошибка пряталась до живого теста 15.09.2026, где
# «Ребята, я иду спать» напечаталось нечитаемыми символами.
import ctypes
from ctypes import wintypes

_INPUT_KEYBOARD = 1          # 0 — это мышь: ошибка в этой константе превращала буквы в пустые движения мыши
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004
_ULONG_PTR = ctypes.c_size_t


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", _ULONG_PTR)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", _ULONG_PTR)]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    # Мышиная структура в объединении обязательна, даже если мышь не нужна: иначе
    # размер INPUT выйдет меньше, чем ждёт Windows, и SendInput молча ничего не сделает
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


_SendInput = ctypes.windll.user32.SendInput
_SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int)
_SendInput.restype = wintypes.UINT


def _key_event(vk: int = 0, scan: int = 0, flags: int = 0) -> _INPUT:
    ev = _INPUT(type=_INPUT_KEYBOARD)
    ev.ki = _KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
    return ev


def type_text(text: str) -> str:
    """Напечатать текст в активное окно — любой язык, любая раскладка.

    Enter не нажимается никогда: в мессенджере он отправил бы сообщение.
    Перенос строки печатается как Shift+Enter — там это новая строка, а не отправка.
    """
    text = str(text).replace("\r\n", "\n").replace("\r", "\n")
    events = []
    for ch in text:
        if ch == "\n":
            events += [_key_event(vk=VK["shift"]), _key_event(vk=VK["enter"]),
                       _key_event(vk=VK["enter"], flags=_KEYEVENTF_KEYUP),
                       _key_event(vk=VK["shift"], flags=_KEYEVENTF_KEYUP)]
            continue
        raw = ch.encode("utf-16-le")                   # эмодзи — это две половинки
        for i in range(0, len(raw), 2):
            code = int.from_bytes(raw[i:i + 2], "little")
            events += [_key_event(scan=code, flags=_KEYEVENTF_UNICODE),
                       _key_event(scan=code, flags=_KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP)]

    target = active_window()
    sent = 0
    batch = 40                                         # приложения теряют слишком быстрый ввод
    for i in range(0, len(events), batch):
        chunk = events[i:i + batch]
        arr = (_INPUT * len(chunk))(*chunk)
        n = _SendInput(len(chunk), arr, ctypes.sizeof(_INPUT))
        sent += n
        if n != len(chunk):
            break
        time.sleep(0.01)
    if sent < len(events):
        # Чаще всего — окно запущено от администратора, и Windows не пускает в него ввод
        return (f"Не смог напечатать в окно «{target[:40]}»: Windows не пропустила ввод. "
                "Если программа запущена от администратора, печатать в неё нельзя.")
    where = f" в окно «{target[:40]}»" if target else ""
    return f"Напечатал{where}: «{text[:60]}»."


def press(key: str) -> str:
    # Буква — это её же код в верхнем регистре: нужно для горячих клавиш YouTube
    # (k — пауза, f — весь экран, m — звук), а их в таблице спецклавиш нет
    vk = VK.get(key.lower()) or (ord(key.upper()) if len(key) == 1 else 0)
    if not vk:
        return f"Не знаю клавишу {key}."
    _tap(vk)
    return "ok"


# ---------------- окна ----------------
def list_windows(limit: int = 12):
    out = []

    from skills.system import is_cloaked

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd) or is_cloaked(hwnd):
            return                          # «спящие» окна Store-приложений на экране не видны
        title = win32gui.GetWindowText(hwnd)
        if not title or len(title) < 2 or title == "Program Manager":
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = psutil.Process(pid).name()
        except Exception:
            proc = "?"
        out.append((hwnd, title, proc))

    win32gui.EnumWindows(cb, None)
    return out[:limit]


def windows_report() -> str:
    ws = list_windows()
    if not ws:
        return "Открытых окон не вижу."
    names = [t[:40] for _, t, _ in ws[:6]]
    return f"Открыто {len(ws)} окон: " + "; ".join(names) + "."


def focus_window(name: str) -> str:
    """Переключиться на окно по куску заголовка или имени программы.

    Название берём и как сказано, и по синонимам программ: «Cloud Code» и «клод» —
    это окно Claude (05.10.2026 модель не нашла его и полезла печатать в браузер).
    """
    from skills.system import _forms
    name = name.lower().strip()
    forms = sorted(_forms(name), key=len, reverse=True)
    for hwnd, title, proc in list_windows(50):
        if any(f in title.lower() or f in proc.lower() for f in forms):
            try:
                if win32gui.IsIconic(hwnd):
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
                return f"Переключился на {title[:40]}."
            except Exception:
                # Windows не отдаёт фокус, если окно не «наше» — подталкиваем через alt
                win32api.keybd_event(VK["alt"], 0, 0, 0)
                win32gui.SetForegroundWindow(hwnd)
                win32api.keybd_event(VK["alt"], 0, win32con.KEYEVENTF_KEYUP, 0)
                return f"Переключился на {title[:40]}."
    return f"Окно «{name}» не найдено."


def active_window() -> str:
    try:
        return win32gui.GetWindowText(win32gui.GetForegroundWindow())
    except Exception:
        return ""


def minimize_all() -> str:
    hotkey("win", "d")
    return "Свернул всё."


def _keeps(name: str) -> set:
    """Как узнать программу, которую оставить: «телеграма» → telegram, «хром» → chrome."""
    from skills.system import ALIASES, _forms
    name = name.strip().lower()
    out = set()
    for cut in (0, 1, 2):                      # падеж: «телеграма», «хрома», «стима»
        base = name[:-cut] if cut else name
        if len(base) >= 3:
            out |= _forms(base) | ({ALIASES[base]} if base in ALIASES else set())
    return {k for k in out if len(k) >= 3}


PROC_LABEL = {"browser": "Яндекс Браузер", "chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox",
              "claude": "Claude", "telegram": "Telegram", "code": "VS Code", "explorer": "Проводник",
              "notepad": "Блокнот", "applicationframehost": "приложение Windows", "steam": "Steam",
              "discord": "Discord", "comet": "Comet"}


def _label(proc: str) -> str:
    stem = proc[:-4] if proc.lower().endswith(".exe") else proc
    return PROC_LABEL.get(stem.lower(), stem)


def _windows_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "окно"
    return "окна" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "окон"


def close_all_windows(keep=()):
    """(описание, действие) — закрыть все окна, кроме названных.

    Проверка 08.10.2026: на «закрой все окна кроме телеграма» модель собрала
    PowerShell Stop-Process — он убивает программы, и несохранённое пропадает.
    Здесь — как крестиком (WM_CLOSE): программа сама спросит про сохранение.
    Окно самого Джарвиса не трогаем никогда. (None, причина) — закрывать нечего.
    """
    marks = set().union(*[_keeps(k) for k in keep]) if keep else set()
    victims, kept = [], set()
    for hwnd, title, proc in list_windows(80):
        low_t, low_p = title.lower(), proc.lower()
        if low_t.split(" - ")[0].strip() == "jarvis":
            continue                          # консоль самого Джарвиса
        if any(m in low_t or m in low_p for m in marks):
            kept.add(_label(proc))
            continue
        victims.append((hwnd, title, proc))
    if not victims:
        return None, "Закрывать нечего." + (f" Оставлено: {', '.join(sorted(kept))}." if kept else "")
    names = sorted({_label(p) for _, _, p in victims})
    desc = (f"закрыть {len(victims)} {_windows_word(len(victims))}: {', '.join(names[:6])}"
            f"{'…' if len(names) > 6 else ''}" + (f"; оставить {', '.join(sorted(kept))}" if kept else ""))

    def act():
        for hwnd, _t, _p in victims:
            try:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                pass
        return f"Закрыл {len(victims)} окон — как крестиком: где не сохранено, программа спросит."
    return desc, act


def close_window() -> str:
    hwnd = win32gui.GetForegroundWindow()
    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    return "Закрыл окно."


def switch_window() -> str:
    hotkey("alt", "tab")
    return "Переключил."


# ---------------- браузер ----------------
def _focus_browser() -> bool:
    for hwnd, title, proc in list_windows(50):
        if any(b in proc.lower() for b in BROWSERS):
            try:
                if win32gui.IsIconic(hwnd):
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
                time.sleep(0.15)
                return True
            except Exception:
                return False
    return False


def browser(action: str, text: str = "") -> str:
    """Управление уже открытым браузером: вкладки, навигация, прокрутка, поиск."""
    if not _focus_browser():
        return "Браузер не запущен."
    a = action.lower()
    if a in ("new_tab", "новая вкладка"):
        hotkey("ctrl", "t")
        return "Новая вкладка."
    if a in ("close_tab", "закрой вкладку"):
        hotkey("ctrl", "w")
        return "Закрыл вкладку."
    if a in ("next_tab", "следующая вкладка"):
        hotkey("ctrl", "tab")
        return "Следующая вкладка."
    if a in ("reopen_tab",):
        hotkey("ctrl", "shift", "t")
        return "Вернул закрытую вкладку."
    if a in ("back", "назад"):
        hotkey("alt", "left")
        return "Назад."
    if a in ("forward", "вперед"):
        hotkey("alt", "right")
        return "Вперёд."
    if a in ("reload", "обнови"):
        press("f5")
        return "Обновил."
    if a in ("scroll_down", "вниз"):
        for _ in range(3):
            press("pgdn")
            time.sleep(0.05)
        return "Пролистал вниз."
    if a in ("scroll_up", "вверх"):
        for _ in range(3):
            press("pgup")
            time.sleep(0.05)
        return "Пролистал вверх."
    if a in ("top",):
        hotkey("ctrl", "home")
        return "Наверх."
    if a in ("goto", "открой"):
        hotkey("ctrl", "l")
        time.sleep(0.15)
        type_text(text)
        press("enter")
        return f"Открываю {text}."
    if a in ("find", "найди на странице"):
        hotkey("ctrl", "f")
        time.sleep(0.15)
        type_text(text)
        press("enter")
        return f"Ищу на странице: {text}."
    if a in ("type", "напечатай"):
        type_text(text)
        return "Напечатал."
    return f"Не знаю действия «{action}»."


# ---------------- видео в браузере ----------------
# Горячие клавиши самого YouTube. Они надёжнее глобальных мультимедийных:
# те уходят тому плееру, который Windows сочтёт главным, а эти — той вкладке,
# что открыта в окне браузера, которое мы перед нажатием вывели вперёд.
VIDEO_KEYS = {
    "pause": ("k", "Поставил на паузу."), "play": ("k", "Включил."),
    "stop": ("k", "Остановил."), "mute": ("m", "Заглушил."),
    "fullscreen": ("f", "Развернул на весь экран."),
    "theater": ("t", "Расширил окно плеера."),
    "forward": ("l", "Перескочил на десять секунд вперёд."),
    "back": ("j", "Отмотал на десять секунд назад."),
    "next": ("shift+n", "Включил следующее."),
    "prev": ("shift+p", "Вернулся к предыдущему."),
    "captions": ("c", "Переключил субтитры."),
}


def video(action: str) -> str:
    """Управление видео в браузере — с проверкой звука, а не на веру.

    На показе 05.10.2026 Джарвис трижды сказал «видео остановлено», пока оно
    играло: он жал глобальную клавишу паузы, никто её не принимал, а отчёт был
    бодрый. Теперь он выводит браузер вперёд, нажимает клавишу самого YouTube и
    слушает, изменилось ли что-нибудь. Если нет — так и говорит.
    """
    from skills.system import sound_level
    a = action.lower().strip()
    key, done = VIDEO_KEYS.get(a, (None, None))
    if not key:
        return f"С видео я умею: {', '.join(VIDEO_KEYS)}."
    if not _focus_browser():
        return "Браузер не запущен — видео в нём я не вижу."

    silencing = a in ("pause", "stop", "mute")
    before = sound_level()
    if silencing and before <= 0.001:
        return "Звука и так нет: либо видео уже стоит, либо оно без звука."
    if a == "play" and before > 0.001:
        return "Оно и так играет."

    if "+" in key:
        hotkey(*key.split("+"))
    else:
        press(key)
    time.sleep(0.8)
    after = sound_level()

    if silencing:
        if after > 0.001:
            return ("Нажал — но звук идёт дальше. Похоже, на странице нет плеера "
                    "или фокус ушёл в поле поиска. Скажи, и попробую иначе.")
        return done
    if a == "play" and after <= 0.001:
        return "Нажал, но звука не слышно — возможно, видео ещё грузится."
    return done


if __name__ == "__main__":
    from core import config
    config.setup_console()
    print(windows_report())
    print("активное окно:", active_window())
