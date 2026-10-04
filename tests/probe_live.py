# -*- coding: utf-8 -*-
"""Проба живого голосового диалога Gemini на настоящих записях хозяина.

Главный вопрос — задержка: сколько проходит от конца фразы человека до первого
звука ответа. В обычном конвейере (распознать → понять → придумать → озвучить)
на этом процессоре выходило 5–8 секунд. Живая модель слушает звук сама, поэтому
этапов меньше.

Аудио отправляется в темпе реального времени, как шло бы с микрофона, —
иначе замер задержки был бы нечестным.
"""
import asyncio
import socket
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

# IPv6 на этой машине не маршрутизируется — websockets без этого ждёт таймаут
_orig_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = lambda host, port, family=0, type=0, proto=0, flags=0: \
    _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

MODELS = ["gemini-3.1-flash-live-preview", "gemini-2.5-flash-native-audio-latest"]
RECORDINGS = [
    "20260914_193550.wav",   # «Джарвис, объясни, что такое простое число»
    "20260914_193536.wav",   # «Джарвис, какая погода в Санкт-Петербурге»
]
OUT = config.DATA / "voice_samples"
PERSONA = ("Ты Джарвис — голосовой помощник. Говоришь по-русски, живо и тепло, как "
           "человек в разговоре, а не как диктор. Отвечаешь коротко: одна-две фразы. "
           "Если нужны данные, которых у тебя нет, например погода, честно скажи, что "
           "сейчас проверишь.")


async def probe(model: str, wav_name: str, voice: str = "Charon"):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.env("GEMINI_API_KEY"))
    cfg = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=PERSONA,
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )

    with wave.open(str(config.DATA / "logs" / "audio" / wav_name)) as w:
        pcm = w.readframes(w.getnframes())
    step = 16000 * 2 * 40 // 1000                    # 40 мс звука, 16 кГц, 16 бит

    t0 = time.time()
    async with client.aio.live.connect(model=model, config=cfg) as session:
        t_connect = time.time() - t0

        async def sender():
            for i in range(0, len(pcm), step):
                await session.send_realtime_input(
                    audio=types.Blob(data=pcm[i:i + step], mime_type="audio/pcm;rate=16000"))
                await asyncio.sleep(0.04)
            await session.send_realtime_input(audio_stream_end=True)
            return time.time()

        send_task = asyncio.create_task(sender())
        audio = bytearray()
        first_audio_at = None
        heard, said = "", ""

        async for msg in session.receive():
            sc = msg.server_content
            if not sc:
                continue
            if sc.input_transcription and sc.input_transcription.text:
                heard += sc.input_transcription.text
            if sc.output_transcription and sc.output_transcription.text:
                said += sc.output_transcription.text
            if sc.model_turn:
                for part in sc.model_turn.parts:
                    if part.inline_data and part.inline_data.data:
                        if first_audio_at is None:
                            first_audio_at = time.time()
                        audio.extend(part.inline_data.data)
            if sc.turn_complete:
                break

        sent_at = await send_task
        speech_end = t0 + t_connect + len(pcm) / 32000   # когда в реальности замолк бы человек
        latency = (first_audio_at - speech_end) if first_audio_at else None

    out = OUT / f"live_{model}_{wav_name[:-4]}.wav"
    if audio:
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(bytes(audio))
    return {
        "connect": t_connect, "latency": latency, "heard": heard.strip(),
        "said": said.strip(), "audio_s": len(audio) / 48000, "file": out if audio else None,
    }


async def main():
    config.setup_console()
    OUT.mkdir(parents=True, exist_ok=True)
    for model in MODELS:
        print(f"\n=== {model} ===")
        for rec in RECORDINGS:
            try:
                r = await asyncio.wait_for(probe(model, rec), timeout=90)
            except Exception as e:
                print(f"  {rec}: не вышло — {str(e)[:200]}")
                continue
            lat = f"{r['latency']:.2f} c" if r["latency"] is not None else "нет звука"
            print(f"  подключение {r['connect']:.2f} c · от конца фразы до первого звука: {lat}")
            print(f"  услышал: «{r['heard']}»")
            print(f"  ответил: «{r['said']}» ({r['audio_s']:.1f} c звука)")


if __name__ == "__main__":
    asyncio.run(main())
