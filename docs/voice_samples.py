# -*- coding: utf-8 -*-
"""Образцы голосов на прослушивание: одна фраза — разные движки.

Выбирать голос по описанию бессмысленно, только на слух. Скрипт генерирует
одну и ту же реплику ассистента всеми доступными движками, сохраняет в
data/voice_samples и замеряет задержку до готового звука — для ассистента она
важна не меньше тембра.
"""
import asyncio
import base64
import socket
import sys
import time
import wave
from pathlib import Path

import requests
import urllib3.util.connection as urllib3_conn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

urllib3_conn.allowed_gai_family = lambda: socket.AF_INET

OUT = config.DATA / "voice_samples"
OUT.mkdir(parents=True, exist_ok=True)

PHRASE = ("Добрый вечер. На сегодня два урока: Петя в шестнадцать ноль-ноль "
          "и Соня в восемнадцать тридцать. На улице плюс четырнадцать, пасмурно.")

EDGE_VOICES = [
    ("ru-RU-DmitryNeural", "Microsoft Дмитрий, мужской"),
    ("ru-RU-SvetlanaNeural", "Microsoft Светлана, женский"),
    ("ru-RU-DariyaNeural", "Microsoft Дарья, женский"),
]
GEMINI_VOICES = [
    ("Charon", "Google Charon, мужской, спокойный"),
    ("Orus", "Google Orus, мужской, твёрдый"),
    ("Kore", "Google Kore, женский, уверенный"),
    ("Aoede", "Google Aoede, женский, лёгкий"),
]
GEMINI_TTS_MODELS = ["gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts"]


def edge_sample(voice: str, path: Path) -> float:
    import edge_tts

    async def run():
        await edge_tts.Communicate(PHRASE, voice).save(str(path))

    t = time.time()
    asyncio.run(run())
    return time.time() - t


def gemini_sample(voice: str, path: Path):
    key = config.env("GEMINI_API_KEY")
    payload = {
        "contents": [{"parts": [{"text": PHRASE}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    last = ""
    for model in GEMINI_TTS_MODELS:
        t = time.time()
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": key}, json=payload, timeout=90)
        el = time.time() - t
        if r.status_code != 200:
            last = f"{model}: HTTP {r.status_code} {r.text[:120]}"
            continue
        part = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
        pcm = base64.b64decode(part["data"])
        rate = 24000
        mime = part.get("mimeType", "")
        if "rate=" in mime:
            rate = int(mime.split("rate=")[1].split(";")[0])
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm)
        return el, model
    raise RuntimeError(last)


def main():
    config.setup_console()
    results = []
    n = 0

    print("Microsoft (Edge):")
    for voice, label in EDGE_VOICES:
        n += 1
        path = OUT / f"{n:02d}_edge_{voice}.mp3"
        try:
            el = edge_sample(voice, path)
            results.append((n, label, path, f"{el:.1f} c"))
            print(f"  {n}. {label} — готово за {el:.1f} c")
        except Exception as e:
            print(f"  {n}. {label} — не вышло: {e}")

    print("\nGoogle (Gemini):")
    for voice, label in GEMINI_VOICES:
        n += 1
        path = OUT / f"{n:02d}_gemini_{voice}.wav"
        try:
            el, model = gemini_sample(voice, path)
            results.append((n, label, path, f"{el:.1f} c"))
            print(f"  {n}. {label} — готово за {el:.1f} c ({model})")
        except Exception as e:
            print(f"  {n}. {label} — не вышло: {str(e)[:150]}")

    print(f"\nОбразцы лежат в {OUT}")
    return results


if __name__ == "__main__":
    main()
