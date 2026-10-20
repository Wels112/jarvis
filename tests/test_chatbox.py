# -*- coding: utf-8 -*-
"""Окно-чат на компьютере: проверяем логику без самого окна (tkinter не поднимаем).

Важно, что ответ модели считается в рабочем потоке и кладётся в очередь для потока
окна, пустой ответ подменяется на «Сделал.», ошибка не роняет окно, а show()
просто поднимает флаг. Само окно (отрисовка, код привязки в шапке) — глазами.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import config
from skills.chatbox import ChatBox


class FakeJarvis:
    def __init__(self, reply=None, boom=False):
        self._reply, self._boom = reply, boom
        self.seen = []

    def answer_text(self, text, source="phone"):
        self.seen.append((text, source))
        if self._boom:
            raise RuntimeError("тест")
        return self._reply


def main():
    config.setup_console()
    errors = 0

    def check(name, ok, detail=""):
        nonlocal errors
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} {name}{' — ' + str(detail)[:110] if detail else ''}")

    j = FakeJarvis(reply="Готово")
    box = ChatBox(j)
    box._answer("открой ютуб")
    kind, text = box._q.get_nowait()
    check("ответ ушёл в очередь как reply", kind == "reply" and text == "Готово")
    check("в answer_text передан source=text", j.seen == [("открой ютуб", "text")], j.seen)

    j2 = FakeJarvis(reply="")
    b2 = ChatBox(j2)
    b2._answer("сделай громче")
    _, text2 = b2._q.get_nowait()
    check("пустой ответ → «Сделал.»", text2 == "Сделал.", text2)

    j3 = FakeJarvis(boom=True)
    b3 = ChatBox(j3)
    b3._answer("что-то")
    _, text3 = b3._q.get_nowait()
    check("ошибка не роняет окно, а уходит текстом", text3.startswith("Споткнулся"), text3)

    b = ChatBox(FakeJarvis())
    check("show() поднимает флаг показа", not b._want_show.is_set())
    b.show()
    check("после show() флаг взведён", b._want_show.is_set())

    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
