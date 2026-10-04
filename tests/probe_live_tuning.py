# -*- coding: utf-8 -*-
"""Настройка живого режима: что ускоряет ответ и что закрепляет русский.

Сравниваются варианты на одной живой записи хозяина, по два прогона каждый.
Мерится время от отправленной фразы до первого звука и язык расшифровки —
от неё зависит защита опасных действий, которая ищет в ней «да».
"""
import asyncio
import re
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config, net

net.prefer_ipv4()
MODEL = "gemini-3.1-flash-live-preview"
REC = "20260914_193550.wav"          # «Джарвис, объясни, что такое простое число»


def variants(types):
    ru = dict(language_codes=["ru-RU"], adaptation_phrases=["Джарвис"])
    return [
        ("как сейчас", {}),
        ("русская расшифровка", {"input_audio_transcription": types.AudioTranscriptionConfig(**ru)}),
        ("+ обдумывание минимум", {
            "input_audio_transcription": types.AudioTranscriptionConfig(**ru),
            "thinking_config": types.ThinkingConfig(thinking_level="MINIMAL")}),
        ("+ обдумывание бюджет 0", {
            "input_audio_transcription": types.AudioTranscriptionConfig(**ru),
            "thinking_config": types.ThinkingConfig(thinking_budget=0)}),
    ]


async def once(types, client, extra, pcm):
    base = dict(
        response_modalities=["AUDIO"],
        system_instruction="Ты Джарвис. Отвечай по-русски, живо и коротко, одной-двумя фразами.",
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Charon"))),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        # Как в core/live.py: без высокой чувствительности к концу фразы сервер
        # иногда не замечает, что фраза отправлена целиком, и молча ждёт
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                silence_duration_ms=500, prefix_padding_ms=200)),
    )
    base.update(extra)
    async with client.aio.live.connect(model=MODEL, config=types.LiveConnectConfig(**base)) as s:
        step = 6400
        for i in range(0, len(pcm), step):
            await s.send_realtime_input(audio=types.Blob(data=pcm[i:i + step],
                                                         mime_type="audio/pcm;rate=16000"))
        await s.send_realtime_input(audio_stream_end=True)
        t_sent = time.monotonic()
        first = None
        heard = said = ""
        async for msg in s.receive():
            sc = msg.server_content
            if not sc:
                continue
            if sc.input_transcription and sc.input_transcription.text:
                heard += sc.input_transcription.text
            if sc.output_transcription and sc.output_transcription.text:
                said += sc.output_transcription.text
            if sc.model_turn and first is None:
                if any(p.inline_data and p.inline_data.data for p in sc.model_turn.parts or []):
                    first = time.monotonic() - t_sent
            if sc.turn_complete:
                break
    return first, heard.strip(), said.strip()


async def main():
    config.setup_console()
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=config.env("GEMINI_API_KEY"))
    with wave.open(str(config.DATA / "logs" / "audio" / REC)) as w:
        pcm = w.readframes(w.getnframes())

    for name, extra in variants(types):
        times, langs = [], []
        last_heard = last_said = ""
        for _ in range(2):
            try:
                first, heard, said = await asyncio.wait_for(once(types, client, extra, pcm), 60)
            except Exception as e:
                print(f"{name:26} сбой {type(e).__name__}: {str(e)[:110]}")
                await asyncio.sleep(5)
                continue
            if first is not None:
                times.append(first)
            langs.append("ру" if re.search(r"[а-яё]", heard.lower()) else "англ")
            last_heard, last_said = heard, said
            await asyncio.sleep(4)            # не открывать сессии очередью
        if times:
            print(f"{name:26} первый звук {', '.join(f'{t:.2f}' for t in times)} c · "
                  f"расшифровка: {'/'.join(langs)} · «{last_heard[:45]}»")
            print(f"{'':26} ответ: «{last_said[:90]}»")


if __name__ == "__main__":
    asyncio.run(main())
