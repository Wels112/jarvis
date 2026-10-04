# -*- coding: utf-8 -*-
"""Глобальные горячие клавиши.

Зачем они голосовому ассистенту: иногда говорить нельзя — рядом спят, идёт
запись, ты в наушниках на созвоне. Клавиша будит Джарвиса молча, и дальше можно
шепнуть команду, не выкрикивая имя на всю комнату.

Сделано на системном RegisterHotKey, а не на перехвате клавиатуры: не требует
прав администратора и не выглядит для антивируса как кейлоггер.
"""
import ctypes
import threading
from ctypes import wintypes

user32 = ctypes.windll.user32

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

VK = {chr(c): c for c in range(ord("A"), ord("Z") + 1)}
VK.update({"SPACE": 0x20, "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73})


def parse(combo: str):
    """«ctrl+alt+j» → (модификаторы, код клавиши)."""
    mods, vk = 0, None
    for part in combo.lower().split("+"):
        part = part.strip()
        if part in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif part == "alt":
            mods |= MOD_ALT
        elif part == "shift":
            mods |= MOD_SHIFT
        else:
            vk = VK.get(part.upper())
    return mods | MOD_NOREPEAT, vk


class HotkeyListener:
    """Слушает сочетания в своём потоке с собственным циклом сообщений."""

    def __init__(self):
        self._bindings = {}          # id → (описание, функция)
        self._next_id = 1
        self._thread = None
        self._running = False

    def add(self, combo: str, callback, description: str = ""):
        mods, vk = parse(combo)
        if vk is None:
            return False
        self._bindings[self._next_id] = (mods, vk, callback, description or combo)
        self._next_id += 1
        return True

    def _loop(self):
        registered = []
        for hid, (mods, vk, _cb, desc) in self._bindings.items():
            if user32.RegisterHotKey(None, hid, mods, vk):
                registered.append(desc)
            else:
                # Чаще всего сочетание уже занято другой программой
                print(f"[клавиши] «{desc}» занято другой программой")
        if registered:
            print(f"[клавиши] работают: {', '.join(registered)}")

        msg = wintypes.MSG()
        while self._running:
            got = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if got in (0, -1):
                break
            if msg.message == WM_HOTKEY:
                binding = self._bindings.get(msg.wParam)
                if binding:
                    try:
                        binding[2]()
                    except Exception as e:
                        print(f"[клавиши] сбой обработчика: {e}")

        for hid in self._bindings:
            user32.UnregisterHotKey(None, hid)

    def start(self):
        if not self._bindings:
            return False
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._running = False


if __name__ == "__main__":
    import sys, time
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core import config
    config.setup_console()

    hk = HotkeyListener()
    hk.add("ctrl+alt+j", lambda: print("  → сработало: вызов Джарвиса"), "ctrl+alt+j")
    hk.add("ctrl+alt+s", lambda: print("  → сработало: стоп"), "ctrl+alt+s")
    if hk.start():
        print("Нажми Ctrl+Alt+J или Ctrl+Alt+S. Выход через 12 секунд.")
        time.sleep(12)
        hk.stop()
        print("готово")
