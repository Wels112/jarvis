# -*- coding: utf-8 -*-
"""Telegram на компьютере: найти чат, спросить «да», открыть, вписать, нажать «Send».

Окно Telegram подменено: строки списка, поле сообщения и кнопка — свои, ничего
не печатается и никуда не уходит. Проверяется решение: кому писать, что
спросить, когда отказаться. Заголовок «Хомяк Туп @ Wels (14253)» — из журнала
живого разговора 07.10.2026; устройство окна (строки «Имя, последнее сообщение»,
кнопка Send / Record Voice Message) снято с настоящего Telegram 08.10.2026.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config


class FakeWindow:
    """Окно Telegram: какой чат открыт, что в поле, нажата ли кнопка."""

    def __init__(self, windows, chats, messages=()):
        self.windows, self.chats, self.msgs = windows, chats, list(messages)
        self.text, self.sent, self.opened = "", [], []
        self.press_works, self.button_ok = True, True

    def __call__(self, hwnd):                     # T.Window(hwnd) → само окно
        return self

    def rows(self):
        return [(t, t) for t in self.chats]

    def open(self, row):
        self.opened.append(row)
        self.windows[:] = [(1, f"{row} @ Wels", "Telegram.exe")]
        return True

    def messages(self):
        return self.msgs

    def get_text(self, search=False):
        return self.text

    def set_text(self, text, search=False):
        self.text = text
        return True

    def send_button(self):
        if not self.button_ok:
            return object(), "Record Voice Message"
        return "send", ("Send" if self.text else "Record Voice Message")

    def press(self, button):
        if self.press_works:
            self.sent.append(self.text)
            self.text = ""
        return self.press_works


def main():
    config.setup_console()
    from skills import tg_desktop as T, desktop as D, telegram as TG, system as S
    from core import brain as B
    from core.honesty import failed

    windows = []
    chats = ["Хомяк Туп", "Саша Петрова", "Саша Иванова", "Мама", "Saved Messages", "Работа"]
    w = FakeWindow(windows, chats, ["Мама\nты где?\nReceived at 19:52",
                                    "Wels\nскоро буду\nSent at 19:56"])
    launched = []
    real = (D.list_windows, D.focus_window, T.Window, TG.ready, S.open_app, T.time.sleep)
    D.list_windows = lambda limit=12: windows
    D.focus_window = lambda name: f"Переключился на {name}."
    T.Window = w
    TG.ready = lambda: False                       # личный Telegram не подключён
    S.open_app = lambda name: launched.append(name) or "Запускаю Telegram."
    T.time.sleep = lambda s: None
    errors = 0

    def check(name, ok, detail=""):
        nonlocal errors
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} {name}{' — ' + str(detail)[:110] if detail else ''}")

    try:
        desc, why = T.prepare("Хомяк Туп", "привет")
        check("нет приложения — запускает Telegram, не вышло — честно", desc is None and failed(why)
              and launched == ["telegram"], why)

        windows[:] = [(1, "Хомяк Туп @ Wels (14253)", "Telegram.exe")]
        desc, action = T.prepare("хомяку тупу", "буду через 10 минут")
        check("открытый чат: падеж не мешает, в вопросе — настоящее название",
              desc and "«Хомяк Туп»" in desc and "буду через 10 минут" in desc, desc)
        check("до «да» ничего не вписано и не отправлено", not w.text and not w.sent and not w.opened)
        result = action()
        check("после «да» вписал и нажал «Send», поле опустело", w.sent == ["буду через 10 минут"]
              and result.startswith("Отправил"), result)

        w.sent.clear()
        desc, action = T.prepare("маме", "ужинать не буду")
        check("другой чат открыт — находит «Мама» в списке и спрашивает", desc and "«Мама»" in desc, desc)
        check("до «да» чат не переключён", not w.opened and "Хомяк" in windows[0][1])
        result = action()
        check("после «да» открыл «Мама», вписал, отправил", w.opened == ["Мама"] and w.sent == ["ужинать не буду"]
              and result.startswith("Отправил в «Мама»"), result)

        desc, why = T.prepare("Саше", "привет")
        check("две Саши — не гадает, переспрашивает", desc is None and "Саша Петрова" in why
              and "Саша Иванова" in why and failed(why), why)
        desc, why = T.prepare("Саше Ивановой", "привет")
        check("«Саше Ивановой» — одна", desc and "«Саша Иванова»" in desc, desc)
        desc, why = T.prepare("Коле", "привет")
        check("такого чата нет — честно и без отправки", desc is None and failed(why), why)

        desc, action = T.prepare("в избранное", "купить хлеб")
        check("«в избранное» — это Saved Messages", desc and "«Saved Messages»" in desc, desc)

        w.sent.clear()
        desc, action = T.prepare("работа", "созвон в 15")
        w.text = "недописанное"
        result = action()
        check("в поле черновик хозяина — не затирает и не отправляет", not w.sent and w.text == "недописанное"
              and failed(result), result)
        w.text = ""

        w.button_ok = False
        result = action()
        check("нет кнопки «Send» — текст убран, ничего не нажато", not w.sent and not w.text and failed(result), result)
        w.button_ok = True

        w.press_works = False
        result = action()
        check("кнопка не нажалась — честное «не отправлено»", not w.sent and failed(result), result)
        w.press_works = True
        w.text = ""

        check("«Хомяк Туп привет как дела» — имя из двух слов",
              T.split_recipient("хомяк туп привет как дела") == ("хомяк туп", "привет как дела"))
        check("«саше что буду поздно» — «что» разделяет",
              T.split_recipient("саше что буду поздно") == ("саше", "буду поздно"))
        check("адресата нет в списке — не гадает", T.split_recipient("письмо маме завтра") == (None, None))

        said = T.open_chat("работу")
        check("«открой чат с работой» — открыл и показал окно", said == "Открыл чат «Работа» в Telegram.", said)
        said = T.read_chat("маму", 5)
        check("«прочитай чат с мамой» — последние сообщения с экрана", "Мама в 19:52: ты где?" in said
              and "Wels в 19:56: скоро буду" in said, said)

        windows[:] = [(1, "Работа @ Wels", "Telegram.exe")]
        b = B.Brain(config.CFG)
        said = b._run_tool("telegram_send", {"chat": "Хомяк Туп", "text": "привет"})
        check("инструмент мозга спрашивает с настоящим названием", b.pending_confirm
              and "«Хомяк Туп»" in said and said.startswith("ТРЕБУЕТСЯ"), said)

        from core import router
        r = router.handle(router.normalize("открой телеграм и напиши хомяку тупу привет как дела"), config.CFG)
        check("голосом: «открой телеграм и напиши …» — вопрос «да?»", r.pending and "«Хомяк Туп»" in r.say
              and "привет как дела" in r.say, r.say)
    finally:
        D.list_windows, D.focus_window, T.Window, TG.ready, S.open_app, T.time.sleep = real

    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
