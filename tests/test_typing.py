# -*- coding: utf-8 -*-
"""Печать текста: русский, английский, цифры, знаки, эмодзи, перенос строки.

Проверка настоящая: открывается Блокнот, в него печатается строка, потом текст
читается прямо из поля ввода Блокнота и сравнивается. Тест сначала убеждается,
что в фокусе именно его Блокнот, — иначе текст ушёл бы в чужое окно, — а в
конце закрывает свой процесс, ничего не сохраняя.
"""
import subprocess
import sys
import time
from pathlib import Path

import win32con
import win32gui
import win32process

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

SAMPLES = [
    "Ребята, я иду спать, вам нужно продолжить работу.",
    "я спать",
    "Hello, World! 123 + 45 = 168; ёЁ «кавычки» — тире",
    "Эмодзи тоже: 🙂👍 и строка\nвторая строка",
]


def find_window(pid, timeout=6):
    end = time.time() + timeout
    while time.time() < end:
        found = []

        def cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                _, wpid = win32process.GetWindowThreadProcessId(hwnd)
                if wpid == pid:
                    found.append(hwnd)
        win32gui.EnumWindows(cb, None)
        if found:
            return found[0]
        time.sleep(0.2)
    return None


def edit_text(hwnd):
    """Текст из поля ввода Блокнота — у старого Блокнота это Edit, у нового RichEdit."""
    child = None
    for cls in ("Edit", "RichEditD2DPT", "RICHEDIT50W"):
        child = win32gui.FindWindowEx(hwnd, 0, cls, None)
        if child:
            break
    if not child:
        return None
    n = win32gui.SendMessage(child, win32con.WM_GETTEXTLENGTH, 0, 0)
    import ctypes
    buf = ctypes.create_unicode_buffer(n + 1)
    ctypes.windll.user32.SendMessageW(child, win32con.WM_GETTEXT, n + 1, buf)
    return buf.value


def main():
    config.setup_console()
    from skills import desktop as D

    proc = subprocess.Popen(["notepad.exe"])
    ok_all = True
    try:
        hwnd = find_window(proc.pid)
        if not hwnd:
            print("Блокнот не открылся — тест не проводился")
            return False
        for sample in SAMPLES:
            D.focus_window(win32gui.GetWindowText(hwnd))
            time.sleep(0.4)
            fg = win32gui.GetForegroundWindow()
            _, fg_pid = win32process.GetWindowThreadProcessId(fg)
            if fg_pid != proc.pid:
                print("В фокусе не тестовый Блокнот — печатать не буду, чтобы не попасть в чужое окно")
                return False
            before = edit_text(hwnd) or ""
            reply = D.type_text(sample)
            time.sleep(0.6)
            got = (edit_text(hwnd) or "")[len(before):]
            got_norm = got.replace("\r\n", "\n")
            ok = got_norm == sample
            ok_all &= ok
            print(f"{'ok ' if ok else 'НЕТ'} «{sample}»")
            if not ok:
                print(f"     получилось: «{got_norm}»")
            print(f"     ответ инструмента: {reply}")
            D.type_text("\n")
    finally:
        proc.kill()                                  # свой Блокнот, без сохранения
    print(f"\nитог: {'всё напечаталось верно' if ok_all else 'есть ошибки'}")
    return ok_all


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
