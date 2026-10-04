# -*- coding: utf-8 -*-
"""Открыть и закрыть программу — по-настоящему, на безобидных Калькуляторе и Блокноте.

Калькулятор — приложение из Microsoft Store, как Claude: проверяет запуск через
список приложений Windows, которого раньше не было. Блокнот — обычная программа.

Если у хозяина уже открыто такое же окно, тест эту программу пропускает:
закрытие по названию задело бы и его окно с несохранённым текстом.
"""
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

CASES = [("калькулятор", "калькулятор"), ("блокнот", "блокнот")]


def windows_with(word):
    from skills.system import _visible_windows
    return [w for w in _visible_windows() if word in w[1].lower()]


def main():
    config.setup_console()
    from skills import system as S
    S.build_app_index(force=True)
    errors = 0
    for spoken, title_word in CASES:
        if windows_with(title_word):
            print(f"пропуск «{spoken}»: у хозяина уже открыто такое окно — не трогаю")
            continue
        print(f"«открой {spoken}» → {S.open_app(spoken)}")
        appeared = None
        for _ in range(30):
            time.sleep(0.3)
            wins = windows_with(title_word)
            if wins:
                appeared = wins
                break
        ok_open = bool(appeared)
        errors += not ok_open
        print(f"  {'ok ' if ok_open else 'НЕТ'} окно появилось: "
              f"{[w[1] for w in appeared] if appeared else 'нет'}")
        if not ok_open:
            continue
        time.sleep(1.0)
        print(f"«закрой {spoken}» → {S.close_app(spoken)}")
        time.sleep(1.0)
        ok_close = not windows_with(title_word)
        errors += not ok_close
        print(f"  {'ok ' if ok_close else 'НЕТ'} окно закрылось")
    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
