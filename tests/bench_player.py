# -*- coding: utf-8 -*-
"""Проигрыватель живого режима: старый против нового, на настоящем ритме и устройстве.

Звук подаётся нулями — ничего не играет, — но через настоящую звуковую карту и
в том ритме, в каком приходил настоящий ответ (tests/capture_audio_pattern.py).

Условия как у Джарвиса в разговоре: одновременно открыт микрофон на той же
гарнитуре и работают потоки Python, которые делят с проигрывателем очередь
выполнения. Мерится то, что реально слышно:
  • опустошения буфера карты — щелчок или пауза в наушниках;
  • опоздания обработчика звука — насколько позже положенного он вызван.
    Опоздание больше запаса устройства и есть щелчок.

Первая версия этого замера считала «провалы» по пустому буферу — и насчитала их
у старого проигрывателя из-за того, что сама проверка конца записи опаздывала.
Такое число ничего не доказывало, поэтому здесь только измерения самой карты.
"""
import json
import queue
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

OUT_RATE = 24000


class Timing:
    """Интервалы между вызовами обработчика звука."""
    def __init__(self, block_s):
        self.block_s = block_s
        self.last = None
        self.late = []
        self.underflows = 0

    def tick(self, status):
        now = time.perf_counter()
        if status.output_underflow:
            self.underflows += 1
        if self.last is not None:
            self.late.append(now - self.last - self.block_s)
        self.last = now


class OldPlayer:
    """Копия проигрывателя до исправления."""
    BLOCK = OUT_RATE // 50

    def __init__(self):
        import sounddevice as sd
        self._buf = bytearray()
        self._lock = threading.Lock()
        self.t = Timing(self.BLOCK / OUT_RATE)
        self._stream = sd.RawOutputStream(samplerate=OUT_RATE, channels=1, dtype="int16",
                                          blocksize=self.BLOCK, callback=self._cb)
        self._stream.start()

    def _cb(self, outdata, frames, time_info, status):
        self.t.tick(status)
        need = frames * 2
        with self._lock:
            n = min(need, len(self._buf))
            chunk = bytes(self._buf[:n])
            del self._buf[:n]
        if n:
            outdata[:n] = chunk
        if n < need:
            outdata[n:need] = b"\x00" * (need - n)

    def feed(self, data):
        with self._lock:
            self._buf.extend(data)

    def turn_done(self):
        pass

    def close(self):
        self._stream.stop()
        self._stream.close()


def make_new():
    from core.live import _Player

    class NewTimed(_Player):
        def __init__(self):
            self.t = Timing(_Player.BLOCK / OUT_RATE)
            super().__init__()

        def _cb(self, outdata, frames, time_info, status):
            self.t.tick(status)
            super()._cb(outdata, frames, time_info, status)
    return NewTimed()


def spin_load(stop):
    def spin():
        x = 0
        while not stop.is_set():
            for i in range(20000):
                x = (x * 31 + i) % 1000003
            json.dumps({"k": [x] * 50})
    for _ in range(3):
        threading.Thread(target=spin, daemon=True).start()


def run(make_player, pattern):
    import numpy as np
    import sounddevice as sd
    stop = threading.Event()
    spin_load(stop)
    mic_q = queue.Queue()
    mic = sd.InputStream(samplerate=16000, blocksize=480, dtype="float32", channels=1,
                         callback=lambda d, f, ti, st: mic_q.put(d[:, 0].copy()))
    mic.start()

    def drain():
        while not stop.is_set():
            try:
                np.concatenate([mic_q.get(timeout=0.25)])
            except queue.Empty:
                pass
    threading.Thread(target=drain, daemon=True).start()

    player = make_player()
    time.sleep(0.3)
    t0 = time.monotonic()
    total = 0
    for t, n in pattern:
        while time.monotonic() - t0 < t:
            time.sleep(0.002)
        player.feed(b"\x00" * n)
        total += n
    player.turn_done()
    time.sleep(total / (OUT_RATE * 2) - (time.monotonic() - t0) + 0.5)
    stop.set()
    mic.stop()
    mic.close()
    player.close()
    late = sorted(player.t.late)
    p99 = late[int(len(late) * 0.99)] if late else 0
    return player.t.underflows, max(late) if late else 0, p99, len(late)


def main():
    config.setup_console()
    import sounddevice as sd
    out_dev = sd.query_devices(kind="output")
    print(f"устройство: {out_dev['name']} · запас карты при высокой задержке: "
          f"{out_dev['default_high_output_latency'] * 1000:.0f} мс")
    pattern = json.loads((config.DATA / "logs" / "audio_pattern.json").read_text(encoding="utf-8"))
    print(f"ритм настоящего ответа: {len(pattern)} кусков, "
          f"{sum(n for _, n in pattern) / 48000:.1f} c звука; микрофон открыт, нагрузка включена\n")
    for name, make in (("старый (блок 20 мс)", OldPlayer), ("новый (блок 50 мс)", make_new)):
        under, worst, p99, n = run(make, pattern)
        print(f"  {name:22} опустошений карты: {under} · опоздание обработчика: "
              f"худшее {worst * 1000:.0f} мс, 99% вызовов в пределах {p99 * 1000:.0f} мс ({n} вызовов)")


if __name__ == "__main__":
    main()
