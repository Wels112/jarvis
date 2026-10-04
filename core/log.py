# -*- coding: utf-8 -*-
"""Журнал работы: что услышал, что ответил, где споткнулся.

Нужен ровно для одного: когда ассистент однажды поведёт себя странно, должно
быть что открыть. Голосовой сбой невоспроизводим — момент прошёл, микрофон
слышал что-то своё, и без записи остаётся только гадать.

Файл на день, старые чистятся сами. Личное сюда не пишем: только команды,
ответы и ошибки.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

LOGS = Path(__file__).resolve().parent.parent / "data" / "logs"
LOGS.mkdir(parents=True, exist_ok=True)
KEEP_DAYS = 14


def _today_file() -> Path:
    return LOGS / f"jarvis-{datetime.now():%Y-%m-%d}.log"


def write(kind: str, text: str):
    """kind: heard | said | error | info"""
    try:
        line = f"{datetime.now():%H:%M:%S}  {kind:6} {text}\n"
        with _today_file().open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass          # журнал не должен мешать работе ассистента


def heard(text: str):
    write("heard", text)


def said(text: str):
    write("said", text)


def error(where: str, exc):
    write("error", f"[{where}] {exc}")


def cleanup(days: int = KEEP_DAYS):
    """Старые журналы никому не нужны и тихо копятся."""
    edge = datetime.now() - timedelta(days=days)
    removed = 0
    for f in LOGS.glob("jarvis-*.log"):
        try:
            stamp = datetime.strptime(f.stem.replace("jarvis-", ""), "%Y-%m-%d")
            if stamp < edge:
                f.unlink()
                removed += 1
        except Exception:
            pass
    return removed


def tail(n: int = 30) -> str:
    """Последние строки — чтобы спросить «что там было» без открытия файла."""
    f = _today_file()
    if not f.exists():
        return "Сегодня журнал пуст."
    lines = f.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[-n:])


if __name__ == "__main__":
    from core import config
    config.setup_console()
    heard("тестовая команда")
    said("тестовый ответ")
    error("проверка", ValueError("демонстрация"))
    print(tail(5))
    print(f"\nудалено старых журналов: {cleanup()}")
    print(f"файл: {_today_file()}")
