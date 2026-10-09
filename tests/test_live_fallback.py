# -*- coding: utf-8 -*-
"""Живой режим не открылся — Джарвис не теряет просьбу и честно говорит почему.

06.10.2026 Gemini ответил «1007 User location is not supported»: VPN был
выключен. Джарвис молча перешёл на простой режим, и хозяин не знал, отчего
тот стал «глупее». Живой режим и микрофон подменены — сеть не нужна.
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config


def main():
    config.setup_console()
    import jarvis as J
    j = J.Jarvis(voice_mode=False)
    spoken = []
    j.voice.say = lambda text: spoken.append(text)
    j.voice.stop = lambda: None

    class Ears:
        interrupt = threading.Event()

        def flush(self):
            pass

        def transcribe(self, audio):
            return "который час"

    class Live:
        t_first_audio = None

        def __init__(self, result):
            self.result = result

        def run(self, first_audio=None, reason="name"):
            return self.result

    j.ears = Ears()
    errors = 0

    j.live = Live("error: 1007 None. User location is not supported for the API use.")
    j._converse(audio=None)
    ok = any("VPN" in s for s in spoken) and spoken[-1] == "Да?"
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} не пустили по стране — сказал про VPN и слушает: {spoken}")

    spoken.clear()
    j._converse(audio=None)
    ok = not any("VPN" in s for s in spoken)
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} второй раз за полчаса про VPN не повторяет: {spoken}")

    spoken.clear()
    j.live = Live("error: 1011 Internal error encountered.")
    j._converse(audio=b"\0" * 3200)
    ok = not any("VPN" in s for s in spoken) and any("час" in s for s in spoken)
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} другой сбой — без VPN, просьба не пропала: {spoken}")

    # Разговор в комнате после такого сбоя: окно открыто, но фраза — не просьба
    # и без имени. 09.10.2026 на «Я уже встал» Джарвис полез смотреть экран
    import time
    asked = []
    j.brain.ask = lambda text, image_path=None: asked.append(text) or "ответ"
    j.live = Live("error: 1007 None. User location is not supported for the API use.")
    j.ears.transcribe = lambda audio: "Я уже встал"
    spoken.clear()
    j._converse(audio=b"\0" * 3200)
    ignored = not asked and not spoken
    j.awake_until = time.time() + 30
    j.process("Глаза автомобиля Mercedes", from_voice=True)
    ignored = ignored and not asked
    j.process("кто такой илон маск", from_voice=True)               # вопрос — отвечает
    j.process("Джарвис, мы завтра едем на дачу", from_voice=True)   # по имени — отвечает
    ok = ignored and asked == ["кто такой илон маск", "мы завтра едем на дачу"]
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} разговор в комнате без имени — молчит; вопрос и обращение по имени — "
          f"отвечает: {asked}")

    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
