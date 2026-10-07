# -*- coding: utf-8 -*-
"""Голосовое из телефона: дошло, разобрано, выполнено, отвечено голосом.

Telegram подменён, а всё остальное настоящее: голосовое синтезируется и
упаковывается в ogg/opus ровно так, как его присылает телефон, разбирается тем
же распознавателем, что слушает микрофон, и выполняется тем же роутером.
"""
import asyncio
import io
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

OWNER = 111222333
PHRASES = ["который час", "сколько будет двести плюс сорок", "открой блокнот",
           "какие ещё новости"]          # последнее — мимо правил, к мозгу


def make_ogg(text: str) -> bytes:
    """Голосовое, как его прислал бы телефон: ogg/opus, живой голос Microsoft."""
    import av
    import edge_tts

    async def fetch():
        out = bytearray()
        async for chunk in edge_tts.Communicate(text, "ru-RU-DmitryNeural").stream():
            if chunk["type"] == "audio":
                out.extend(chunk["data"])
        return bytes(out)

    mp3 = asyncio.run(fetch())
    with av.open(io.BytesIO(mp3)) as c:
        st = c.streams.audio[0]
        rate = st.rate
        pcm = np.concatenate([f.to_ndarray().mean(axis=0) for f in c.decode(st)])
    pcm = (np.clip(pcm, -1, 1) * 32767).astype("<i2")
    buf = io.BytesIO()
    with av.open(buf, "w", format="ogg") as out:
        stream = out.add_stream("libopus", rate=rate)
        stream.layout = "mono"
        frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="s16", layout="mono")
        frame.rate = rate
        for p in stream.encode(frame):
            out.mux(p)
        for p in stream.encode(None):
            out.mux(p)
    return buf.getvalue()


def main():
    config.setup_console()
    import jarvis as J
    from core.ears import Ears
    from core.phone import Phone

    from tests import sandbox
    acted = sandbox.enable()               # «открой блокнот» разбирается, но не открывает
    j = J.Jarvis(voice_mode=False)
    j.voice.say = lambda text: None
    # Мозг думает дольше двух секунд, как без сети со своей моделью. 07.10.2026
    # в таком случае телефон получал «Не получилось ответить», не дождавшись ответа
    import time as _time
    j.brain.ask = lambda text, image_path=None: _time.sleep(3) or "Новостей нет, всё спокойно."
    print("поднимаю распознаватель...")
    j.ears = Ears(j.cfg, str(config.MODELS))

    phone = Phone(j)
    phone.token, phone.owner = "тест", OWNER
    sent = []
    phone._call = lambda method, _wait=20, _files=None, **p: (
        sent.append((method, p.get("text", ""), bool(_files))) or [])

    errors = 0
    for phrase in PHRASES:
        sent.clear()
        ogg = make_ogg(phrase)
        phone._download = lambda fid, data=ogg: data
        phone._handle({"chat": {"id": OWNER}, "voice": {"file_id": "x"}})
        texts = [t for m, t, _ in sent if m == "sendMessage"]
        heard = next((t[len("Услышал: "):] for t in texts if t.startswith("Услышал: ")), "")
        answer = next((t for t in texts if not t.startswith("Услышал: ")), "")
        voices = sum(1 for m, _, f in sent if m == "sendVoice" and f)
        ok = bool(answer) and bool(heard) and "Не получилось" not in answer
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} голосовое «{phrase}»")
        print(f"     разобрал: «{heard}» → ответ: «{answer[:70]}»")
        print(f"     голосовым ответил: {'да' if voices else 'нет'} (режим {phone.voice_replies})")

    # Раньше тест открывал настоящий Блокнот, а в конце закрывал — вместе с
    # блокнотом хозяина, если тот был открыт
    ok = [name for name, _ in acted] == ["system.open_app"]
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} «открой блокнот» дошло до запуска программы (в песочнице): {acted}")
    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
