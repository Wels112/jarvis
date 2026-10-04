# -*- coding: utf-8 -*-
"""Видео в браузере: включить, поставить на паузу — и ЗНАТЬ, что получилось.

Проверка настоящая: открывается настоящее видео на YouTube, и результат сверяется
по уровню звука приложения, а не по бодрому отчёту. Повод — показ 05.10.2026, где
Джарвис трижды сказал «видео остановлено», пока оно играло.

Тест шумит в наушниках несколько секунд и в конце возвращает тишину. Если
хозяин в этот момент сам смотрит видео, тест отказывается работать: он поставил
бы на паузу чужое кино.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

# Короткое и заведомо существующее: гимн тишины не подойдёт, нужен звук
CLIP = "первый полёт ракеты"


def main():
    config.setup_console()
    from skills import desktop as D
    from skills import system as S
    from skills import youtube as YT

    errors = 0
    busy = {k: v for k, v in S.audio_activity().items()
            if v > 0.001 and k not in ("python", "pythonw")}
    if busy:
        print(f"отказываюсь: уже что-то звучит ({', '.join(busy)}) — не трогаю чужое")
        return True

    print(f"1) «включи {CLIP}»")
    said = YT.play_on_youtube(CLIP)
    print(f"   {said}")
    level = 0.0
    for _ in range(40):                      # видео грузится и может начаться с рекламы
        time.sleep(0.5)
        level = S.sound_level()
        if level > 0.001:
            break
    ok = level > 0.001
    errors += not ok
    print(f"   {'ok ' if ok else 'НЕТ'} звук пошёл: уровень {level:.4f} · "
          f"звучит {S.who_sounds()}")
    if not ok:
        print("   (дальше проверять нечего — видео не заиграло)")
        return False

    print("2) «поставь на паузу»")
    said = D.video("pause")
    time.sleep(0.5)
    level = S.sound_level()
    ok = ("паузу" in said) and level <= 0.001
    errors += not ok
    print(f"   {said}\n   {'ok ' if ok else 'НЕТ'} после паузы уровень {level:.4f}")

    print("3) повторная пауза — должен сказать, что звука и так нет, а не «готово»")
    said = D.video("pause")
    ok = "и так" in said
    errors += not ok
    print(f"   {said}\n   {'ok ' if ok else 'НЕТ'} отчёт честный")

    print("4) «включи обратно»")
    said = D.video("play")
    time.sleep(1.2)
    level = S.sound_level()
    ok = level > 0.001
    errors += not ok
    print(f"   {said}\n   {'ok ' if ok else 'НЕТ'} звук вернулся: {level:.4f}")

    print("5) «это не то, следующее»")
    said = YT.play_next()
    print(f"   {said}")
    ok = "Включаю" in said
    errors += not ok
    print(f"   {'ok ' if ok else 'НЕТ'} взят следующий вариант без нового поиска")

    print("\n6) убираю за собой: пауза и закрыть вкладку")
    print(f"   {D.video('pause')}")
    print(f"   {D.browser('close_tab')}")

    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
