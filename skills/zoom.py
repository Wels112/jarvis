# -*- coding: utf-8 -*-
"""Zoom во время урока: микрофон, камера, демонстрация экрана — голосом.

Руки на доске Miro, ученик решает задачу — а надо выключить микрофон или
показать экран. У Zoom есть свои сочетания клавиш, но срабатывают они только
когда окно конференции в фокусе. Поэтому навык находит окно встречи, выводит его
вперёд, жмёт сочетание и возвращает фокус туда, где ты работал.

Проверить на живой конференции без хозяина нельзя, поэтому навык честно
отвечает, когда Zoom не запущен или встречи сейчас нет, — а не делает вид,
что нажал.
"""
import sys
import time
from pathlib import Path

import psutil
import win32api
import win32con
import win32gui
import win32process

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from skills import desktop as D

# действие → (сочетание, ответ, вернуть ли фокус обратно)
ACTIONS = {
    "mic": (("alt", "a"), "Микрофон переключил.", True),
    "video": (("alt", "v"), "Камеру переключил.", True),
    "share": (("alt", "s"), "Открываю демонстрацию экрана.", False),
    "chat": (("alt", "h"), "Открыл чат.", False),
    "participants": (("alt", "u"), "Открыл список участников.", False),
    "record": (("alt", "r"), "Запись переключил.", True),
    "hand": (("alt", "y"), "Руку переключил.", True),
    "end": (("alt", "q"), "Открыл завершение конференции — подтверди в окне Zoom.", False),
}


def running() -> bool:
    for p in psutil.process_iter(["name"]):
        if (p.info["name"] or "").lower().startswith("zoom"):
            return True
    return False


def _meeting_window():
    """Окно именно конференции, а не главное окно приложения."""
    found = []

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd).lower()
        if not title:
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if not psutil.Process(pid).name().lower().startswith("zoom"):
                return
        except Exception:
            return
        if "meeting" in title or "конференц" in title or "встреч" in title:
            found.append(hwnd)

    win32gui.EnumWindows(cb, None)
    return found[0] if found else None


def _activate(hwnd):
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        # Windows отдаёт фокус чужому окну только после нажатия клавиши — жмём Alt
        win32api.keybd_event(0x12, 0, 0, 0)
        win32gui.SetForegroundWindow(hwnd)
        win32api.keybd_event(0x12, 0, win32con.KEYEVENTF_KEYUP, 0)


def control(action: str) -> str:
    if action not in ACTIONS:
        return "Не знаю такой команды для Zoom."
    if not running():
        return "Zoom не запущен."
    hwnd = _meeting_window()
    if not hwnd:
        return "Zoom открыт, но конференции сейчас нет."

    keys, reply, restore = ACTIONS[action]
    previous = win32gui.GetForegroundWindow()
    try:
        _activate(hwnd)
        time.sleep(0.15)
        D.hotkey(*keys)
        time.sleep(0.1)
    except Exception as e:
        return f"Не смог достучаться до Zoom: {e}"
    finally:
        if restore and previous and previous != hwnd:
            try:
                _activate(previous)
            except Exception:
                pass
    return reply


if __name__ == "__main__":
    from core import config
    config.setup_console()
    print("Zoom запущен:", running())
    print("окно конференции:", _meeting_window())
    print(control("mic"))
