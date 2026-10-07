# -*- coding: utf-8 -*-
"""Напоминания: понят ли срок так, как его сказали.

Проверка от фразы целиком до записи в списке дел — ровно тем кодом, что работает
вживую. Ожидаемое время считается от «сейчас», поэтому тест не ломается со временем.

Поводом стал показ 02.10.2026: «заказать рамстры через неделю в 15-30» встало на
тот же день, потому что разбор требовал числа и «через неделю» не понимал.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config


def main():
    config.setup_console()
    from core import memory
    now = datetime.now()
    today, tomorrow = now.date(), (now + timedelta(days=1)).date()

    # (фраза, ожидаемый день, ожидаемый час и минута или None если не важно)
    cases = [
        ("заказать рамстры через неделю в 15:30", (now + timedelta(days=7)).date(), (15, 30)),
        ("через неделю в 15-30", (now + timedelta(days=7)).date(), (15, 30)),
        ("напомни через 20 минут выключить плиту", today, None),
        ("через полчаса проверить почту", today, None),
        ("через полтора часа позвонить маме", None, None),
        ("через две недели сдать отчёт", (now + timedelta(days=14)).date(), None),
        ("через месяц продлить подписку", None, None),
        ("завтра в 9 утра зарядка", tomorrow, (9, 0)),
        ("послезавтра в 18:00 тренировка", (now + timedelta(days=2)).date(), (18, 0)),
        ("в среду в 12 созвон", None, (12, 0)),
        ("в пятницу урок с Петей", None, (9, 0)),
        ("в 7 вечера ужин", None, (19, 0)),
        ("в полдень обед", None, (12, 0)),
        ("5 января в 9:30 поезд", None, (9, 30)),
    ]

    errors = 0
    for phrase, want_date, want_time in cases:
        when = memory._parse_when(phrase)
        if when is None:
            print(f"НЕТ  «{phrase}» → срок не понят")
            errors += 1
            continue
        bad = []
        if want_date and when.date() != want_date:
            bad.append(f"день {when:%d.%m} вместо {want_date:%d.%m}")
        if want_time and (when.hour, when.minute) != want_time:
            bad.append(f"время {when:%H:%M} вместо {want_time[0]:02d}:{want_time[1]:02d}")
        if when < now:
            bad.append("срок в прошлом")
        errors += bool(bad)
        print(f"{'НЕТ ' if bad else 'ok  '}«{phrase}» → {when:%d.%m %H:%M}"
              f"{'  — ' + ', '.join(bad) if bad else ''}")

    # Сказано днём, в 13:41 — ровно как на живом разговоре 07.10.2026, где
    # «сегодня в 20:00» встало на 8 утра завтра: «дня» нашлось внутри «сегодня»
    print()
    at = now.replace(hour=13, minute=41, second=0, microsecond=0)
    day, next_day = at.date(), (at + timedelta(days=1)).date()
    afternoon = [
        ("сегодня в 20:00", day, (20, 0)),
        ("Ученик сегодня в 20:00", day, (20, 0)),
        ("сегодня в 20", day, (20, 0)),
        ("сегодня в восемь вечера", day, (20, 0)),
        ("сегодня 20:00", day, (20, 0)),
        ("20:00", day, (20, 0)),
        ("в пятнадцать тридцать", day, (15, 30)),
        ("в 3 дня", day, (15, 0)),
        ("сегодня в 2 дня", day, (14, 0)),
        ("завтра в восемь утра", next_day, (8, 0)),
        ("в девять", day, (21, 0)),             # днём «в девять» — это вечер
        ("через двадцать минут", day, (14, 1)),
    ]
    for phrase, want_date, want_time in afternoon:
        when = memory._parse_when(phrase, now=at)
        ok = when is not None and when.date() == want_date and (when.hour, when.minute) == want_time
        errors += not ok
        print(f"{'ok  ' if ok else 'НЕТ '}в 13:41 «{phrase}» → {when:%d.%m %H:%M}" if when else
              f"НЕТ  в 13:41 «{phrase}» → срок не понят")

    from skills.numbers import words_to_number
    for spoken, want in (("громкость тридцать пять", "громкость 35"),
                         ("двести сорок пять", "245"), ("две тысячи двадцать шесть", "2026"),
                         ("в пятнадцать тридцать", "в 15 30"), ("пять шесть", "5 6")):
        got = words_to_number(spoken)
        errors += got != want
        print(f"{'ok  ' if got == want else 'НЕТ '}числа: «{spoken}» → «{got}»")

    # Текст задачи без формулировки срока: напоминание должно звучать по-человечески
    print()
    for phrase in ["напомни мне через неделю в 15:30 заказать рамстры",
                   "поставь задачу завтра в 10 позвонить в банк",
                   "напомни через 20 минут выключить плиту"]:
        before = len(memory._load(memory.TASKS, []))
        said = memory.add_task(phrase, phrase)
        task = memory._load(memory.TASKS, [])[-1]
        memory._save(memory.TASKS, memory._load(memory.TASKS, [])[:before])   # тест ничего не оставляет
        clean = task["text"]
        noise = [w for w in ("напомни", "завтра", "через", "неделю", "поставь", "задачу")
                 if w in clean.lower()]
        errors += bool(noise)
        print(f"{'НЕТ ' if noise else 'ok  '}«{phrase}»\n      задача: «{clean}» · ответ: {said}")

    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
