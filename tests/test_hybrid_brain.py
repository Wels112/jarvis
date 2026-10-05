# -*- coding: utf-8 -*-
"""Переключение мозгов: облако, пока оно живо, своя модель — когда нет.

Облако по-настоящему не роняем: подменяется только его отправка запроса —
то возвращает ошибку сети, то лимит 429. Своя модель настоящая, на видеокарте.
Действия заглушены — инструменты только записываются.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config


def main():
    config.setup_console()
    from core.brain import Brain
    from core.local_brain import HybridBrain

    cloud = Brain(config.CFG)
    tools = []
    cloud._run_tool = lambda name, args: (tools.append(name), f"[выполнено: {name}]")[1]
    brain = HybridBrain(cloud, config.CFG)
    errors = 0
    if not brain.local.available:
        print("своей модели нет — проверять нечего")
        return False

    # 1. Облако отвечает — своя модель не нужна, видеокарта не занимается
    real_post = cloud._post
    brain._net_ok, brain._net_checked = True, time.time()
    answer = brain.ask("скажи одним словом: два плюс два")
    ok = brain.last_source == "облако" and brain.local._proc is None
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} облако живо: ответило «{answer[:40]}», "
          f"своя модель не запускалась: {brain.local._proc is None}")

    # 2. Облако упало сетью — тот же вопрос подхватывает своя модель
    def broken(payload, timeout=45):
        raise RuntimeError("все модели недоступны — сеть (ConnectionError)")
    cloud._post = broken
    tools.clear()
    t0 = time.monotonic()
    answer = brain.ask("поставь таймер на пять минут")
    took = time.monotonic() - t0
    ok = brain.last_source == "своя модель" and bool(tools)
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} облако упало: ответила своя модель за {took:.1f} c, "
          f"инструменты {tools} · «{answer[:40]}»")

    # 3. Пять минут облако не дёргаем: следующий вопрос сразу своей модели
    calls = []
    cloud._post = lambda payload, timeout=45: (calls.append(1), real_post(payload, timeout))[1]
    brain.ask("который час")
    ok = not calls and brain.last_source == "своя модель"
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} в паузе облако не трогали: запросов к облаку {len(calls)}")

    # 4. Пауза прошла, облако вернулось — снова отвечает облако
    brain.cloud_off_until = 0
    brain._net_ok, brain._net_checked = True, time.time()
    brain.ask("скажи одним словом: привет")
    ok = brain.last_source == "облако"
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} облако вернулось — отвечает снова оно")

    # 5. Глухой интернет: проверка дороги не ждёт минутами
    brain._net_checked = 0
    import requests
    real_head = requests.head
    requests.head = lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("нет сети"))
    calls.clear()
    t0 = time.monotonic()
    brain.ask("который час")
    took = time.monotonic() - t0
    requests.head = real_head
    ok = not calls and brain.last_source == "своя модель" and took < 15
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} нет дороги до облака: сразу своя модель, {took:.1f} c, "
          f"облако не ждали")

    brain.local.stop()
    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
