# -*- coding: utf-8 -*-
"""Написать через Telegram на компьютере — только в открытый чат и после «да».

Окна, печать и нажатия подменены: ничего не печатается и никуда не уходит.
Проверяется решение: куда писать, что спросить, что ответить, если что-то не так.
Заголовок «Хомяк Туп @ Wels (14253)» — из журнала живого разговора 07.10.2026.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config


def main():
    config.setup_console()
    from skills import tg_desktop as T, desktop as D, ui as UI, telegram as TG
    from core import brain as B
    from core.honesty import failed

    windows = []
    typed, clicked = [], []
    real = (D.list_windows, D.focus_window, D.type_text, UI.find, UI._invoke, TG.ready)
    D.list_windows = lambda limit=12: windows
    D.focus_window = lambda name: f"Переключился на {name}."
    D.type_text = lambda text: typed.append(text) or f"Напечатал: «{text}»."
    send_button = ["Send"]
    UI.find = lambda name, window="": ((object(), send_button[0], "кнопка", "Telegram")
                                       if send_button[0] else (None, "не найдено", [], "Telegram"))
    UI._invoke = lambda el, *a: clicked.append(el) or True
    TG.ready = lambda: False                       # личный Telegram не подключён
    errors = 0

    def check(name, ok, detail=""):
        nonlocal errors
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} {name}{' — ' + str(detail)[:110] if detail else ''}")

    try:
        desc, why = T.prepare("Хомяк Туп", "привет")
        check("нет приложения — не отправляет и просит открыть", desc is None and failed(why), why)

        windows[:] = [(1, "Telegram", "Telegram.exe")]
        desc, why = T.prepare("Хомяк Туп", "привет")
        check("чат не открыт — просит открыть", desc is None and "не открыт ни один чат" in why)

        windows[:] = [(1, "Хомяк Туп @ Wels (14253)", "Telegram.exe")]
        desc, action = T.prepare("хомяку тупу", "буду через 10 минут")
        check("падеж не мешает, в вопросе — настоящее название чата",
              desc and "«Хомяк Туп @ Wels»" in desc and "буду через 10 минут" in desc, desc)
        desc2, why = T.prepare("Саше", "привет")
        check("открыт другой чат — не пишет и не переключает", desc2 is None and "а не «Саше»" in why, why)

        check("до «да» ничего не напечатано", not typed and not clicked)
        result = action()
        check("после «да» напечатал и нажал «Send»", typed == ["буду через 10 минут"] and clicked
              and result.startswith("Отправил"), result)

        typed.clear(); clicked.clear()
        windows[:] = [(1, "Саша (2)", "Telegram.exe")]       # пока думал, чат сменили
        result = action()
        check("чат сменили до «да» — не отправляет", not typed and failed(result), result)

        windows[:] = [(1, "Хомяк Туп @ Wels (14253)", "Telegram.exe")]
        send_button[0] = "Record voice message"               # текст ушёл не в поле — кнопки нет
        result = action()
        check("нет кнопки «Send» — Enter вслепую не жмёт", not clicked and failed(result), result)
        send_button[0] = "Send"

        b = B.Brain(config.CFG)
        said = b._run_tool("telegram_send", {"chat": "Хомяк Туп", "text": "привет"})
        check("инструмент мозга спрашивает с настоящим названием", b.pending_confirm
              and "Хомяк Туп @ Wels" in said and said.startswith("ТРЕБУЕТСЯ"), said)
    finally:
        D.list_windows, D.focus_window, D.type_text, UI.find, UI._invoke, TG.ready = real

    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
