# -*- coding: utf-8 -*-
"""Планировщик на тестовых данных (data/brain/test) и отдельном порту — посмотреть окно,
не трогая настоящее расписание.  python tests\\planner_demo.py [порт] [--seed]"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config
from skills import planner as P


def seed():
    P.path().unlink(missing_ok=True)
    for ev in [
        {"day": 0, "start": "09:30", "end": "11:00", "title": "Пары: матанализ", "cat": "study",
         "notes": "Принести конспект, сдать ДЗ 3"},
        {"day": 0, "start": "16:00", "end": "17:00", "title": "Урок с Петей — алгебра", "cat": "tutor",
         "notes": "Квадратные уравнения, проверить домашку", "remind": True},
        {"day": 0, "start": "17:30", "end": "18:30", "title": "Урок с Машей — геометрия", "cat": "tutor"},
        {"day": 1, "start": "08:00", "end": "09:00", "title": "Пробежка", "cat": "sport"},
        {"day": 2, "start": "16:00", "end": "17:30", "title": "Урок с Петей — алгебра", "cat": "tutor"},
        {"day": 2, "start": "16:30", "end": "17:15", "title": "Созвон по Джарвису", "cat": "work"},
        {"day": 3, "start": "19:00", "end": "21:00", "title": "Лаба по Java", "cat": "study",
         "notes": "Lab1: классы и наследование"},
        {"day": 4, "start": "18:00", "end": "19:00", "title": "Урок с Машей — геометрия", "cat": "tutor"},
        {"day": 5, "start": "12:00", "end": "14:00", "title": "Ролик для ytfactory", "cat": "work"},
    ]:
        P.add(ev)


if __name__ == "__main__":
    config.setup_console()
    port = int(next((a for a in sys.argv[1:] if a.isdigit()), 8766))
    if "--seed" in sys.argv:
        seed()
    httpd = P.serve(port)
    print(f"планировщик (тестовые данные): http://127.0.0.1:{port}/  файл {P.path()}", flush=True)
    while True:
        time.sleep(3600)
