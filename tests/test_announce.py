# -*- coding: utf-8 -*-
"""Сам по себе Джарвис говорит важное один раз, а не при каждом запуске.

07.10.2026 его перезапускали несколько раз за день, и каждый раз звучало «На
диске C осталось 1,7 гигабайта…» и «Из плана: …». Теперь предупреждение о
диске — не чаще раза в шесть часов, план дня — раза в три, через перезапуски.
Заодно план дня называет уроки: прежде он искал их время в несуществующем поле.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config


def main():
    config.setup_console()
    import jarvis as J
    from core import memory
    from skills import lessons, cleanup as CL
    J.ANNOUNCED.unlink(missing_ok=True)
    errors = 0

    def fresh():
        j = J.Jarvis(voice_mode=False)
        said = []
        j.voice.say = lambda text: said.append(text)
        j.phone = None
        return j, said

    real = (memory._load, lessons._planned_for, CL.free_space)
    later = datetime.now() + timedelta(minutes=30)
    memory._load = lambda path, default: ([{"id": 1, "text": "ученик", "when": later.isoformat(),
                                            "done": False}] if path == memory.TASKS else real[0](path, default))
    lessons._planned_for = lambda day: [{"name": "Петя", "subject": "", "at": later + timedelta(hours=1),
                                         "duration": 60, "rate": 0}]
    CL.free_space = lambda drive="C:": (int(1.7 * 2**30), 232 * 2**30)
    try:
        j, said = fresh()
        j._tell_today()
        j._disk_check_since = 0                # замер диска «давно идёт» — предупредить и без него
        j._check_disk()
        first = list(said)
        j2, said2 = fresh()                    # «перезапуск»
        j2._tell_today()
        j2._disk_check_since = 0
        j2._check_disk()
    finally:
        memory._load, lessons._planned_for, CL.free_space = real
        J.ANNOUNCED.unlink(missing_ok=True)

    plan = next((s for s in first if s.startswith("Из плана")), "")
    for name, ok in (("план дня сказан и с уроками", "ученик" in plan and "уроков впереди 1" in plan),
                     ("о диске предупредил", any("На диске C" in s for s in first)),
                     ("после перезапуска не повторяет", not said2)):
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} {name}")
    print(f"   первый запуск: {first}\n   второй: {said2}")
    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
