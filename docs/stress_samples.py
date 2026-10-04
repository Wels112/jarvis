# -*- coding: utf-8 -*-
"""Образцы для проверки ударений: одна фраза с «ловушками» — разные голоса.

Фраза собрана из слов, где ударение ломают чаще всего: звонИт, договОр,
красИвее, тОрты, катАлог, включИт, начАлся. Автоматически ударения не
проверить — распознаватель их не слышит, — поэтому только на слух.
"""
import asyncio
import io
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config, net

net.prefer_ipv4()
OUT = config.DATA / "voice_samples" / "stress"
PHRASE = ("Звонит Петя, включить тебе громкость погромче? Урок начался в четыре. "
          "Договор я положил в каталог, а торты сегодня красивее, чем вчера.")
LIVE_MODEL = "gemini-3.1-flash-live-preview"


async def live_sample(voice: str, language_code: str | None, path: Path):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=config.env("GEMINI_API_KEY"))
    speech = dict(voice_config=types.VoiceConfig(
        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)))
    if language_code:
        speech["language_code"] = language_code
    cfg = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction="Ты диктор. Произнеси текст пользователя дословно, ничего не добавляя, "
                           "с правильными русскими ударениями.",
        speech_config=types.SpeechConfig(**speech),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH)),
    )
    audio = bytearray()
    async with client.aio.live.connect(model=LIVE_MODEL, config=cfg) as s:
        await s.send_realtime_input(text=f"Произнеси дословно: {PHRASE}")
        async for msg in s.receive():
            sc = msg.server_content
            if sc and sc.model_turn:
                for p in sc.model_turn.parts or []:
                    if p.inline_data and p.inline_data.data:
                        audio.extend(p.inline_data.data)
            if sc and sc.turn_complete:
                break
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(bytes(audio))
    return len(audio) / 48000


async def edge_sample(voice: str, path: Path):
    import edge_tts
    await edge_tts.Communicate(PHRASE, voice).save(str(path))


async def main():
    config.setup_console()
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [
        ("1_google_Charon_как_сейчас.wav", "live", ("Charon", None)),
        ("2_google_Charon_русский_закреплён.wav", "live", ("Charon", "ru-RU")),
        ("3_google_Orus_русский_закреплён.wav", "live", ("Orus", "ru-RU")),
        ("4_microsoft_Дмитрий.mp3", "edge", ("ru-RU-DmitryNeural",)),
        ("5_microsoft_Светлана.mp3", "edge", ("ru-RU-SvetlanaNeural",)),
    ]
    for name, kind, args in jobs:
        path = OUT / name
        try:
            if kind == "live":
                dur = await asyncio.wait_for(live_sample(*args, path), 60)
                print(f"  {name}: {dur:.1f} c")
            else:
                await edge_sample(*args, path)
                print(f"  {name}: готово")
        except Exception as e:
            print(f"  {name}: не вышло — {str(e)[:150]}")
        await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())
