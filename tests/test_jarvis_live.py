# -*- coding: utf-8 -*-
"""Настоящий jarvis.py с живым режимом — от записанной фразы до конца разговора.

В отличие от test_live.py, здесь работает сам главный цикл: быстрый поиск имени
моделью tiny, открытие разговора, страховка при сбое. Микрофон не включается:
в очередь ушей идёт тишина, а фраза — живая запись хозяина.
"""
import sys
import threading
import time
import warnings
import wave
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config


def load_wav(name):
    """Образцы живого голоса лежат в data/fixtures: журнал звука периодически чистится."""
    with wave.open(str(config.DATA / "fixtures" / name)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def feed_silence(ears, stop):
    rng = np.random.default_rng(0)
    while not stop.is_set():
        ears._q.put((rng.standard_normal(480) * 0.0008).astype(np.float32))
        time.sleep(0.03)


def main():
    config.setup_console()
    config.CFG.setdefault("live", {})["idle_timeout_s"] = 7

    import jarvis
    from core.ears import Ears
    from core.live import LiveConversation
    from tests import quiet

    quiet.install()                                 # звук ответа — в никуда, система не трогается
    stop = threading.Event()
    try:
        j = jarvis.Jarvis(voice_mode=True)
        j.ears = Ears(j.cfg, str(config.MODELS))         # модели настоящие, микрофон — нет
        threading.Thread(target=feed_silence, args=(j.ears, stop), daemon=True).start()
        j.live = LiveConversation(j)
        print("живой режим доступен:", j.live.available)

        # 1. Живая запись хозяина с показа: «Джарвис, сгенерируй короткий рассказ»
        audio = load_wav("рассказ.wav")
        t0 = time.monotonic()
        found, head = j.ears.quick_wake(audio)
        t_wake = time.monotonic() - t0
        print(f"\n1) имя в начале: {found} за {t_wake:.2f} c («{head}»)")
        t0 = time.monotonic()
        ok = j._handle_phrase(audio)
        total = time.monotonic() - t0
        if j.live.t_first_audio:
            print(f"   от готовой фразы до первого звука ответа: "
                  f"{j.live.t_first_audio - (t0 - 0):.2f} c (включая поиск имени и подключение)")
        print(f"   разговор закрыт, главный цикл продолжает: {ok} · всё заняло {total:.0f} c")

        # 2. Сбой живого режима: несуществующая модель → ответ по-старому
        j.live.model = "gemini-no-such-live-model"
        said = []
        original_say = j.voice.say
        j.voice.say = lambda text, block=False: (said.append(text), original_say(text, block))[1]
        t0 = time.monotonic()
        ok = j._handle_phrase(audio)
        j.voice.wait()
        print(f"\n2) при сбое живого режима: продолжает={ok}, пауза живого режима "
              f"{max(0, j.live_off_until - time.time()) / 60:.0f} мин")
        print(f"   ответил по-старому за {time.monotonic() - t0:.1f} c: «{' '.join(said)[:160]}»")
    finally:
        stop.set()


if __name__ == "__main__":
    main()
