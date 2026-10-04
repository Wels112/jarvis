# -*- coding: utf-8 -*-
"""Узнаётся ли обращение — на том, как его реально слышит распознаватель.

Строки слева взяты из журналов живых разговоров: так whisper расслышал хозяина.
Справа — слова, на которые Джарвис просыпаться не должен: из-за одного лишнего
срабатывания он влезает в разговор и начинает слушать комнату.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

# Как его звали вживую (журналы 13.09, 14.09 и показ 02.10.2026)
CALLS = [
    "Джарвис, который час",
    "Джервис, расскажи про Солнечную систему",
    "Жарвис, какая погода",
    "Джарвиз, открой блокнот",
    "Джарвес, привет",
    "Дарвис, что по задачам",
    "Джарви, ты можешь написать в блокноте привет Артем",
    "Джарвицы включи калькулятор",
    "Джарвик, включи музыку",
    "Джарвис, объясни, что такое простое число",
    "Джаррус, расскажи",
    "Открой браузер, Джарвис",
]

# На это просыпаться нельзя
NOT_CALLS = [
    "привет",
    "Тёмыч, держи",
    "Сервис, подскажи",
    "Марина, иди сюда",
    "архив открой",
    "жарим картошку",
    "на улице жарко",
    "котлеты жарятся",
    "Дарвин придумал эволюцию",
    "жара невозможная",
    "жаркий день сегодня",
    "давай поговорим",
    "открой блокнот",
    "сколько будет двести плюс сорок",
]


def main():
    config.setup_console()
    from core import wake

    missed, false = [], []
    for phrase in CALLS:
        found, rest = wake.find(phrase.lower())
        if not found:
            missed.append(phrase)
        print(f"{'ok  ' if found else 'НЕТ '}«{phrase[:46]:46}» → команда: «{rest[:30]}»")

    print()
    for phrase in NOT_CALLS:
        found, _ = wake.find(phrase.lower())
        if found:
            false.append(phrase)
        print(f"{'ok  ' if not found else 'НЕТ '}«{phrase[:46]:46}» → "
              f"{'не моё дело' if not found else 'ПРОСНУЛСЯ ЗРЯ'}")

    print(f"\nузнано {len(CALLS) - len(missed)} из {len(CALLS)} обращений · "
          f"ложных пробуждений {len(false)} из {len(NOT_CALLS)}")
    if missed:
        print(f"  не узнал: {'; '.join(missed)}")
    if false:
        print(f"  проснулся зря: {'; '.join(false)}")
    return not false and len(missed) <= 1


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
