# -*- coding: utf-8 -*-
"""Написать человеку через Telegram на компьютере, когда личный Telegram не подключён.

07.10.2026 хозяин попросил «напиши Хомяк Туп»: личный Telegram (вход через
my.telegram.org) не подключён, и Джарвис, ведомый хозяином, напечатал текст
в открытое окно Telegram и нажал «Send» — сработало. Но правила это запрещали:
однажды модель сама печатала в Telegram нажатиями клавиш, и текст ушёл не в тот
чат. Здесь тот же путь, но с предохранителями:

* Пишем только в чат, открытый сейчас: его название — в заголовке окна
  Telegram («Хомяк Туп @ Wels (14253)»). Сам Джарвис чаты не переключает.
* В вопросе «отправить?» звучит настоящее название из заголовка, а не
  сказанное голосом: подтверждают ровно то, что случится.
* Перед отправкой заголовок проверяется ещё раз: пока хозяин думал, чат могли
  сменить.
* Кнопку отправки ищем точным названием («Send» / «Отправить»). Её нет —
  значит, текст попал не в поле сообщения: честно говорим и ничего не жмём,
  Enter вслепую не нажимаем никогда.
"""
import re
import time

from skills import desktop as D
from skills import ui as UI

SEND_NAMES = ("send", "отправить")


def telegram_window():
    """(hwnd, заголовок) окна Telegram Desktop или (None, '')."""
    for hwnd, title, proc in D.list_windows(80):
        if proc.lower().startswith("telegram"):
            return hwnd, title
    return None, ""


def chat_title(window_title: str) -> str:
    """Открытый чат по заголовку окна; '' — чат не открыт (в заголовке просто «Telegram»)."""
    t = re.sub(r"\s*\(\d+\)\s*$", "", window_title or "").strip()     # счётчик непрочитанного
    t = re.sub(r"\s*[–—-]\s*Telegram\s*$", "", t, flags=re.I).strip()
    return "" if t.lower() in ("", "telegram") else t


def matches(name: str, title: str) -> bool:
    """«Хомяку» — это «Хомяк Туп», «Саше» — «Саша»: по основам слов, падеж не важен."""
    n, t = UI._norm(name), UI._norm(title)
    if not n or not t:
        return False
    if n in t:
        return True
    stems = [w[:max(3, len(w) - 2)] for w in n.split() if len(w) >= 3]
    return bool(stems) and all(s in t for s in stems)


def prepare(name: str, text: str):
    """(описание для подтверждения, действие) или (None, почему нельзя)."""
    hwnd, wtitle = telegram_window()
    if not hwnd:
        return None, ("НЕ ОТПРАВЛЕНО: личный Telegram не подключён, и приложения Telegram на "
                      "компьютере не вижу. Открой его и нужный чат — тогда напишу туда.")
    title = chat_title(wtitle)
    if not title:
        return None, (f"НЕ ОТПРАВЛЕНО: в Telegram на компьютере не открыт ни один чат. Открой чат "
                      f"«{name}» — и я напишу туда.")
    if not matches(name, title):
        return None, (f"НЕ ОТПРАВЛЕНО: в Telegram на компьютере открыт чат «{title}», а не «{name}». "
                      "Открой нужный — сам переключать чаты не буду: так легко ошибиться адресатом.")
    desc = f"отправить в чат «{title}» (Telegram на компьютере) сообщение: «{text}»"
    return desc, (lambda: send_to_open_chat(title, text))


def send_to_open_chat(title: str, text: str) -> str:
    """Напечатать в открытый чат и нажать «Send». Вызывается только после «да»."""
    _hwnd, wtitle = telegram_window()
    now_open = chat_title(wtitle)
    if now_open != title:
        return f"НЕ ОТПРАВЛЕНО: в Telegram уже открыт другой чат — «{now_open or 'никакой'}»."
    D.focus_window("telegram")
    time.sleep(0.4)
    typed = D.type_text(text)
    if not typed.startswith("Напечатал"):
        return "НЕ ОТПРАВЛЕНО: " + typed
    time.sleep(0.4)
    el, found, _kind, _title = UI.find("Send", "telegram")
    if el is None or UI._norm(found) not in SEND_NAMES:
        return ("НЕ ОТПРАВЛЕНО: текст напечатан, но кнопку отправки не нашёл — возможно, он попал "
                "не в поле сообщения. Проверь окно Telegram.")
    if not UI._invoke(el):
        return "НЕ ОТПРАВЛЕНО: кнопка отправки не нажалась. Текст в поле — проверь окно Telegram."
    return f"Отправил в «{title}» через Telegram на компьютере."
