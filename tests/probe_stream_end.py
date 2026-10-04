# -*- coding: utf-8 -*-
"""Нужно ли объявлять конец звукового потока — и не из-за него ли падения 1011.

На показе 02.10.2026 живой режим падал с «1011 Internal error» и разговор уходил
на медленный путь. Подозрение: модуль отправляет audio_stream_end, а затем
продолжает лить звук с микрофона. Поток объявлен законченным и продолжается —
сервер мог отвечать на это внутренней ошибкой.

Три варианта по несколько прогонов: с объявлением конца и продолжением звука
(как сейчас), без объявления, и с объявлением, но без продолжения. Считаются
падения и время до первого звука ответа.
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
RUNS = 3


class Stub:
    def __init__(self):
        self.cfg = config.CFG
        self.ears = type("E", (), {"_noise": 0.006})()
        self.running, self.paused = True, False


async def once(stream_end: bool, keep_mic: bool):
    from google import genai
    from google.genai import types
    from core.live import LiveConversation, trim_silence

    live = LiveConversation(Stub())
    cfg = live._config(types)
    with wave.open(str(config.DATA / "fixtures" / REC)) as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    pcm = (np.clip(trim_silence(audio, 0.006), -1, 1) * 32767).astype("<i2").tobytes()

    client = genai.Client(api_key=config.env("GEMINI_API_KEY"))
    t0 = first = None
    said = ""
    async with client.aio.live.connect(model=live.model, config=cfg) as s:
        step = 6400
        for i in range(0, len(pcm), step):
            await s.send_realtime_input(audio=types.Blob(data=pcm[i:i + step],
                                                         mime_type="audio/pcm;rate=16000"))
        if stream_end:
            await s.send_realtime_input(audio_stream_end=True)
        t0 = time.monotonic()

        async def mic():
            z = b"\x00" * 1440                   # тишина с «микрофона», 45 мс
            while True:
                await s.send_realtime_input(audio=types.Blob(data=z, mime_type="audio/pcm;rate=16000"))
                await asyncio.sleep(0.045)
        pump = asyncio.create_task(mic()) if keep_mic else None

        async def rx():
            nonlocal first, said
            async for msg in s.receive():
                if msg.tool_call:
                    await s.send_tool_response(function_responses=[
                        types.FunctionResponse(id=fc.id, name=fc.name,
                                               response={"result": "15 градусов, ясно"})
                        for fc in msg.tool_call.function_calls])
                sc = msg.server_content
                if not sc:
                    continue
                if first is None and sc.model_turn and any(
                        p.inline_data for p in sc.model_turn.parts or []):
                    first = time.monotonic() - t0
                if sc.output_transcription and sc.output_transcription.text:
                    said += sc.output_transcription.text
                if sc.turn_complete:
                    return
        try:
            await asyncio.wait_for(rx(), 25)
        finally:
            if pump:
                pump.cancel()
    return first, said.strip()


async def main():
    config.setup_console()
    variants = [
        ("как сейчас: конец потока + звук дальше", dict(stream_end=True, keep_mic=True)),
        ("без объявления конца, звук дальше", dict(stream_end=False, keep_mic=True)),
        ("конец потока и тишина в эфир", dict(stream_end=True, keep_mic=False)),
    ]
    for name, kw in variants:
        times, fails = [], []
        for _ in range(RUNS):
            try:
                first, said = await asyncio.wait_for(once(**kw), 40)
                if first is None:
                    fails.append("ответа нет")
                else:
                    times.append(first)
            except asyncio.TimeoutError:
                fails.append("таймаут")
            except Exception as e:
                fails.append(f"{type(e).__name__} {str(e)[:40]}")
            await asyncio.sleep(4)
        good = f"{', '.join(f'{t:.2f}' for t in times)} c" if times else "—"
        print(f"{name:40} удачно {len(times)}/{RUNS} · первый звук {good}")
        if fails:
            print(f"{'':40} сбои: {'; '.join(fails)}")


if __name__ == "__main__":
    asyncio.run(main())
