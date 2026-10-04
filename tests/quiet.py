# -*- coding: utf-8 -*-
"""Тихий режим для тестов живого разговора.

Раньше тесты глушили звук всей системы, чтобы ответы модели не играли в
наушниках. 15.09.2026 это ударило по хозяину: у него в этот момент работал
настоящий Джарвис, звук пропал посреди разговора, а в конце тест сбросил его
громкость. Тест не должен трогать ничего, кроме себя.

Поэтому вместо глушения подменяется только проигрыватель живого режима: звук
принимается и отбрасывается, а отметки времени идут как у настоящего — чтобы
замеры задержки и логика «пока говорит, не закрываться» работали честно.
"""
import threading
import time


class SilentPlayer:
    OUT_BYTES_PER_S = 24000 * 2

    def __init__(self, device=None):
        self._lock = threading.Lock()
        self._queued_s = 0.0
        self._started = None
        self.last_audio_at = 0.0

    def feed(self, data: bytes):
        with self._lock:
            now = time.monotonic()
            if self._started is None or now > self._started + self._queued_s:
                self._started, self._queued_s = now, 0.0
            self._queued_s += len(data) / self.OUT_BYTES_PER_S
            self.last_audio_at = self._started + self._queued_s

    def turn_done(self):
        pass

    def clear(self):
        with self._lock:
            self._started, self._queued_s = None, 0.0
            self.last_audio_at = time.monotonic()

    @property
    def busy(self) -> bool:
        with self._lock:
            return self.last_audio_at > time.monotonic()

    def close(self):
        pass


def install():
    """Подменить проигрыватель живого режима на беззвучный."""
    import core.live as live
    live._Player = SilentPlayer
