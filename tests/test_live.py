# -*- coding: utf-8 -*-
"""Живой разговор целиком — без человека у микрофона.

Микрофон подменён очередью: в неё идёт тишина в темпе реального времени, а в
нужный момент — озвученная фраза, будто человек заговорил. Первая фраза — живая
запись хозяина. Так проверяется весь путь: отправка записанной фразы, вызов
инструментов, продолжение разговора по микрофону, закрытие по тишине.

Опасное действие подменено безобидной заглушкой: тест проверяет, что оно
выполняется только после «да» голосом, и ничего на диске не трогает.
"""
import asyncio
import io
import queue
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

FRAME = 480                                   # 30 мс при 16 кГц


class FakeEars:
    def __init__(self):
        self._q = queue.Queue()
        self._noise = 0.006
        self._script = queue.Queue()          # фразы, которые «скажет человек»
        self._alive = True
        threading.Thread(target=self._feed, daemon=True).start()

    def _feed(self):
        rng = np.random.default_rng(1)
        pending = None
        while self._alive:
            if pending is None:
                try:
                    pending = self._script.get_nowait()
                except queue.Empty:
                    pending = None
            if pending is not None and len(pending):
                frame, pending = pending[:FRAME], pending[FRAME:]
                if len(frame) < FRAME:
                    frame = np.pad(frame, (0, FRAME - len(frame)))
                if not len(pending):
                    pending = None
            else:
                frame = (rng.standard_normal(FRAME) * 0.0008).astype(np.float32)
            self._q.put(frame.astype(np.float32))
            time.sleep(0.03)

    def say(self, audio):
        self._script.put(np.concatenate([audio, np.zeros(16000, dtype=np.float32)]))

    def flush(self):
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                return

    def close(self):
        self._alive = False


class Stub:
    def __init__(self, idle=8):
        import copy
        self.cfg = copy.deepcopy(config.CFG)
        self.cfg.setdefault("live", {})["idle_timeout_s"] = idle
        self.ears = FakeEars()
        self.running = True
        self.paused = False


def load_wav(name):
    """Живая запись хозяина из data/fixtures — журнал звука периодически чистится."""
    with wave.open(str(config.DATA / "fixtures" / name)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def synth(text, voice="ru-RU-SvetlanaNeural"):
    """Озвучить реплику «человека» живым голосом Microsoft."""
    import av
    import edge_tts

    async def fetch():
        out = bytearray()
        async for ch in edge_tts.Communicate(text, voice).stream():
            if ch["type"] == "audio":
                out.extend(ch["data"])
        return bytes(out)

    data = asyncio.run(fetch())
    with av.open(io.BytesIO(data)) as c:
        s = c.streams.audio[0]
        rate = s.rate
        pcm = np.concatenate([f.to_ndarray().mean(axis=0) for f in c.decode(s)]).astype(np.float32)
    idx = np.arange(0, len(pcm), rate / 16000).astype(int)
    return pcm[idx[idx < len(pcm)]]


def run_scenario(title, first, script, idle=8, patch=None):
    """script: [(через сколько секунд после старта, текст реплики)]"""
    from core.live import LiveConversation
    from core import log

    stub = Stub(idle)
    live = LiveConversation(stub)
    calls = []
    if patch:
        patch(live, calls)

    log_file = log._today_file()
    start_size = log_file.stat().st_size if log_file.exists() else 0
    lines = []
    for item in script:
        delay, text = item[0], item[1]
        raw = item[2] if len(item) > 2 else None
        lines.append((delay, raw if raw is not None else synth(text)))

    def speaker():
        t0 = time.time()
        for delay, audio in lines:
            while time.time() - t0 < delay:
                time.sleep(0.1)
            stub.ears.say(audio)

    threading.Thread(target=speaker, daemon=True).start()
    t0 = time.time()
    result = live.run(first_audio=first)
    took = time.time() - t0
    stub.ears.close()

    journal = log_file.read_text(encoding="utf-8")[start_size:] if log_file.exists() else ""
    print(f"\n=== {title} ===")
    lat = (f"{live.t_first_audio - live.t_sent:.2f} c"
           if live.t_first_audio and live.t_sent else "нет данных")
    print(f"  итог: {result} за {took:.0f} c · первый звук после отправки фразы: {lat}")
    for line in journal.splitlines():
        if any(k in line for k in ("heard", "said", "tool", "подтвержд", "открыт", "закрыт")):
            print("   ", line[:150])
    return result, journal, calls


def main():
    config.setup_console()
    from tests import quiet
    quiet.install()                                 # звук ответа — в никуда, система не трогается
    only_confirm = "--confirm" in sys.argv
    try:
        # 1. Живая запись хозяина → погода → вопрос вдогонку по микрофону → тишина
        if not only_confirm:
            run_scenario(
                "погода, затем уроки вдогонку",
                load_wav("привет.wav"),
                [(16, "А какие у меня уроки сегодня?")],
                idle=8)

        # 1б. Помехи поверх ответа: мычание и шум не обрывают, вопрос — обрывает
        if not only_confirm:
            import numpy as _np
            noise = (_np.random.default_rng(3).standard_normal(16000) * 0.004).astype(_np.float32)
            stub_first = synth("Джарвис, расскажи подробно, минуты на две, как устроена Солнечная система.",
                               "ru-RU-DmitryNeural")
            res, journal, _ = run_scenario(
                "шум и «м-м» поверх ответа, потом настоящий вопрос",
                stub_first,
                [(9, None, noise), (12, "Мм.", None), (16, None, noise),
                 (24, "Подожди, а сколько всего планет?", None)],
                idle=8)
            said_lines = [l for l in journal.splitlines() if "said" in l]
            cut = [l for l in said_lines if "[перебили]" in l]
            print(f"\n  ответов прервано: {len(cut)} (ожидаю ровно 1 — настоящим вопросом)")

        # 2. Опасное действие: без «да» не выполнять, после «да» — выполнить
        def patch(live, calls):
            from skills import cleanup as CL
            CL.clean = lambda dry_run=False: (calls.append(dry_run) or
                                              "Освободил 0.5 ГБ (заглушка теста)") \
                if not dry_run else "Могу освободить примерно 0.5 ГБ."
        r2, j2, calls = run_scenario(
            "очистка диска: сначала спросить, выполнить только после «да»",
            synth("Джарвис, почисти диск от мусора.", "ru-RU-DmitryNeural"),
            [(9, "Да, давай."), (22, "Да.")],
            idle=8, patch=patch)
        executed = [c for c in calls if c is False]
        print(f"\n  очистка реально вызвана: {len(executed)} раз(а) — ожидаю 1")
    finally:
        pass


if __name__ == "__main__":
    main()
