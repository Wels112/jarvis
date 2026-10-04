# -*- coding: utf-8 -*-
"""Исправление того, что распознавание услышало криво.

Whisper силён, но на коротких командах регулярно промахивается в одних и тех же
местах: «джарвиз» вместо «джарвис», «пауз» вместо «паузу», «в контакте» вместо
«вконтакте». Каждая такая ослышка роняет команду целиком, хотя человек сказал всё
правильно.

Словарь лежит в data/corrections.json и дополняется на ходу: если Джарвис
регулярно не понимает конкретную фразу, туда добавляется пара «услышанное →
правильное», и правило начинает срабатывать. Числительные словами приводятся
к цифрам здесь же — «громкость тридцать» и «громкость 30» должны работать
одинаково.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skills.numbers import words_to_number

FILE = Path(__file__).resolve().parent.parent / "data" / "corrections.json"

# Базовый набор: собран из реальных промахов на тестах голосового тракта
BUILTIN = {
    r"\bпауз\b": "паузу",
    r"\bв контакте\b": "вконтакте",
    r"\bю туб\w*\b": "ютуб",
    r"\bтелеграмм\b": "телеграм",
    r"\bскрин\s?шот\b": "скриншот",
    r"\bпо тише\b": "потише",
    r"\bпо громче\b": "погромче",
    r"\bна помни\b": "напомни",
    r"\bза помни\b": "запомни",
    r"\bвы ключи\b": "выключи",
    r"\bв ключи\b": "включи",
    r"\bот крой\b": "открой",
    r"\bза крой\b": "закрой",
    r"\bкомпьютор\b": "компьютер",
    r"\bгугл\s?хром\b": "хром",
    # из живого теста 13.09.2026
    r"\bкоторой час\b": "который час",
    r"\bдобавишь\b": "добавь",
}


_cache = {"mtime": None, "data": {}}


def _load_custom() -> dict:
    """Читается на каждой команде, поэтому держим в памяти и перечитываем
    только когда файл действительно менялся."""
    if not FILE.exists():
        _cache["mtime"], _cache["data"] = None, {}
        return {}
    try:
        mtime = FILE.stat().st_mtime
        if _cache["mtime"] != mtime:
            _cache["data"] = json.loads(FILE.read_text(encoding="utf-8"))
            _cache["mtime"] = mtime
    except Exception:
        return _cache["data"]
    return _cache["data"]


def add(heard: str, meant: str) -> str:
    """Запомнить новую ослышку, чтобы впредь понимал."""
    custom = _load_custom()
    custom[heard.strip().lower()] = meant.strip().lower()
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(custom, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"Понял: «{heard}» — это «{meant}»."


def apply(text: str) -> str:
    """Причесать распознанное перед разбором правилами."""
    t = text
    for pattern, fix in BUILTIN.items():
        t = re.sub(pattern, fix, t, flags=re.I)
    for heard, meant in _load_custom().items():
        t = re.sub(rf"\b{re.escape(heard)}\b", meant, t, flags=re.I)
    # «двести сорок» → «240»: команды с числами должны работать в обеих формах
    t = words_to_number(t)
    return re.sub(r"\s+", " ", t).strip()


if __name__ == "__main__":
    from core import config
    config.setup_console()
    tests = [
        "поставь на пауз", "громкость тридцать", "от крой блокнот",
        "что в телеграмм", "сделай по тише", "напомни через двадцать минут",
        "сколько будет двести плюс сорок",
    ]
    for s in tests:
        print(f"{s:38} -> {apply(s)}")
