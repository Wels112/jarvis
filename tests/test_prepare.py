# -*- coding: utf-8 -*-
"""Заготовка подключения: насколько раньше звучит первый ответ.

Сравниваются два прогона одной живой записи хозяина через настоящий главный
цикл: с заготовкой (подключение начато в момент, когда человек заговорил) и
без неё. Отдельно — что холостые заготовки выключаются после трёх подряд.
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

REC = "рассказ.wav"                  # живая запись: «твоя задача — сгенерировать рассказ»


def load_wav(name):
    """Образцы живого голоса лежат в data/fixtures: журнал звука периодически чистится."""
    with wave.open(str(config.DATA / "fixtures" / name)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def main():
    config.setup_console()
    config.CFG.setdefault("live", {})["idle_timeout_s"] = 5

    import jarvis
    from core.ears import Ears
    from core.live import LiveConversation
    from tests import quiet

    quiet.install()                                 # звук ответа — в никуда, система не трогается
    stop = threading.Event()
    try:
        j = jarvis.Jarvis(voice_mode=True)
        j.ears = Ears(j.cfg, str(config.MODELS))

        def silence():
            rng = np.random.default_rng(0)
            while not stop.is_set():
                j.ears._q.put((rng.standard_normal(480) * 0.0008).astype(np.float32))
                time.sleep(0.03)
        threading.Thread(target=silence, daemon=True).start()

        j.live = LiveConversation(j)
        j.ears.on_speech_start = j._on_speech_start
        audio = load_wav(REC)
        j.ears.quick_wake(audio)                    # прогрев модели, чтобы замер был честным

        results = {}
        for mode in ("холодный старт", "с заготовкой"):
            if mode == "с заготовкой":
                j._on_speech_start()                # человек заговорил
            time.sleep(len(audio) / 16000)          # пока он договаривает фразу
            t_ready = time.monotonic()              # фраза записана
            j._handle_phrase(audio)
            first = j.live.t_first_audio
            results[mode] = (first - t_ready) if first else None
            time.sleep(4)

        print("\nот записанной фразы до первого звука ответа (поиск имени + подключение + ответ):")
        for mode, v in results.items():
            print(f"  {mode:15} {v:.2f} c" if v else f"  {mode:15} нет звука")
        if all(results.values()):
            print(f"  выигрыш: {results['холодный старт'] - results['с заготовкой']:.2f} c")

        # Холостые заготовки: три впустую — дальше не подключаемся
        live = j.live
        for i in range(3):
            live.prepare()
            time.sleep(1.5)
            live.discard()
        live.prepare()
        suppressed = live._prepared is None
        print(f"\nпосле трёх холостых заготовок новая не начата: {suppressed}")
        live.discard()
    finally:
        stop.set()


if __name__ == "__main__":
    main()
