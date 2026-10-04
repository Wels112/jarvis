# -*- coding: utf-8 -*-
"""Почему модель молчит на живой записи про погоду.

Та же запись и та же настройка, что у core/live.py, отправка тем же способом.
Печатается каждое сообщение сервера — чтобы увидеть, где обрывается путь:
не услышал речь, услышал, но не ответил, или ответил инструментом и завис.
Варианты отличаются одним изменением из ночных правок каждый.
"""
import asyncio
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config, net

net.prefer_ipv4()
REC = "рассказ.wav"                  # живая запись: «твоя задача — сгенерировать короткий рассказ»


class Stub:
    def __init__(self):
        self.cfg = config.CFG
        self.ears = type("E", (), {"_noise": 0.006})()
        self.running, self.paused = True, False


async def run(label, trim=True, stream_end=True, mic_silence=False, weather_tool=True):
    from google import genai
    from google.genai import types
    from core.live import LiveConversation, trim_silence

    live = LiveConversation(Stub())
    cfg = live._config(types)
    if not weather_tool:
        cfg.tools = None
    with wave.open(str(config.DATA / "fixtures" / REC)) as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    if trim:
        audio = trim_silence(audio, 0.006)
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()

    client = genai.Client(api_key=config.env("GEMINI_API_KEY"))
    events = []
    t0 = time.monotonic()
    async with client.aio.live.connect(model=live.model, config=cfg) as s:
        step = 6400
        for i in range(0, len(pcm), step):
            await s.send_realtime_input(audio=types.Blob(data=pcm[i:i + step], mime_type="audio/pcm;rate=16000"))
        if stream_end:
            await s.send_realtime_input(audio_stream_end=True)

        async def silence():
            z = b"\x00" * 1440
            while True:
                await s.send_realtime_input(audio=types.Blob(data=z, mime_type="audio/pcm;rate=16000"))
                await asyncio.sleep(0.045)
        sil = asyncio.create_task(silence()) if mic_silence else None

        async def rx():
            while True:
                async for msg in s.receive():
                    t = time.monotonic() - t0
                    if msg.tool_call:
                        names = [fc.name for fc in msg.tool_call.function_calls]
                        events.append(f"{t:5.2f} инструмент {names}")
                        await s.send_tool_response(function_responses=[
                            types.FunctionResponse(id=fc.id, name=fc.name,
                                                   response={"result": "15 градусов, ясно"})
                            for fc in msg.tool_call.function_calls])
                    sc = msg.server_content
                    if not sc:
                        continue
                    if sc.input_transcription and sc.input_transcription.text:
                        events.append(f"{t:5.2f} расшифровка: {sc.input_transcription.text!r}")
                    if sc.model_turn and any(p.inline_data for p in sc.model_turn.parts or []):
                        if not any("звук" in e for e in events):
                            events.append(f"{t:5.2f} первый звук ответа")
                    if sc.output_transcription and sc.output_transcription.text:
                        events.append(f"{t:5.2f} говорит: {sc.output_transcription.text[:40]!r}")
                    if sc.interrupted:
                        events.append(f"{t:5.2f} ПЕРЕБИТ")
                    if sc.turn_complete:
                        events.append(f"{t:5.2f} реплика закончена")
                        return
        try:
            await asyncio.wait_for(rx(), 20)
        except asyncio.TimeoutError:
            events.append("  20.00 ТАЙМАУТ: за 20 секунд ответа нет")
        if sil:
            sil.cancel()
    print(f"\n=== {label} ===")
    compact = []
    for e in events:
        if e.split(" ", 1)[-1].startswith("говорит") and compact and "говорит" in compact[-1]:
            continue
        compact.append(e)
    for e in compact[:14]:
        print("  " + e)


async def main():
    config.setup_console()
    variants = [
        ("как в модуле: обрезка + конец потока + тишина с микрофона", dict(mic_silence=True)),
        ("без тишины с микрофона после фразы", dict(mic_silence=False)),
        ("без обрезки тишины", dict(trim=False, mic_silence=True)),
        ("без инструментов", dict(mic_silence=True, weather_tool=False)),
    ]
    for label, kw in variants:
        try:
            await run(label, **kw)
        except Exception as e:
            print(f"\n=== {label} ===\n  сбой: {type(e).__name__}: {str(e)[:200]}")
        await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())
