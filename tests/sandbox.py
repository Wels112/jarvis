# -*- coding: utf-8 -*-
"""Песочница для проверок разбора команд: правило срабатывает, действие — нет.

router.handle не только разбирает фразу, но и выполняет её. Сквозной тест
голоса при каждом прогоне открывал хозяину Блокнот и ставил громкость системы
на 30, а проверка «включи видео…» 08.10.2026 в час ночи открыла ему две вкладки
YouTube. Здесь подменены все умения, которые что-то меняют на компьютере или
отправляют наружу; чтение (время, окна, погода, счёт) работает по-настоящему.

    from tests import sandbox
    calls = sandbox.enable()      # [(«system.set_volume», args), ...]
"""
import importlib

ACTS = {
    "skills.system": ["open_app", "open_site", "search_web", "set_search_engine", "close_app",
                      "set_volume", "change_volume", "mute", "media_key", "screenshot",
                      "lock_screen", "shutdown", "reboot", "cancel_shutdown", "sleep_pc",
                      "clipboard_set"],
    "skills.desktop": ["hotkey", "type_text", "press", "focus_window", "minimize_all",
                       "close_window", "switch_window", "browser", "video"],
    "skills.youtube": ["play_on_youtube", "play_next", "play_number"],
    "skills.telegram": ["open_chat", "send_message_confirmed"],
    "skills.cleanup": ["clean"],
    "skills.tools": ["set_alarm"],
    "skills.lessons": ["add_student", "set_schedule", "start_lesson", "finish_lesson",
                       "cancel_lesson", "add_note", "open_board", "open_tutorlab"],
    "skills.weather": ["remember_city"],
    "skills.files": ["open_found", "open_safely", "latest_download"],
    "skills.ui": ["click"],
}

calls = []
_real = {}


def enable() -> list:
    """Подменить действия заглушками. Повторный вызов ничего не ломает."""
    for name, funcs in ACTS.items():
        module = importlib.import_module(name)
        for fn in funcs:
            if not hasattr(module, fn) or (name, fn) in _real:
                continue
            _real[(name, fn)] = getattr(module, fn)
            label = f"{name.split('.')[-1]}.{fn}"
            setattr(module, fn, lambda *a, _l=label, **k: calls.append((_l, a)) or f"[песочница] {_l}")
    return calls


def disable():
    for (name, fn), real in _real.items():
        setattr(importlib.import_module(name), fn, real)
    _real.clear()
