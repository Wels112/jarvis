# -*- coding: utf-8 -*-
"""Записать, как на самом деле приходят куски звука живого ответа.

Сохраняются только моменты прихода и размеры кусков, сам звук — нет. По этому
ритму потом сравниваются проигрыватели: прерывистость рождается именно тут —
когда между кусками пауза длиннее, чем запас в буфере.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config, net

net.prefer_ipv4()
OUT = config.DATA / "logs" / "audio_pattern.json"
PROMPT = ("Расскажи подробно, секунд на сорок, как люди придумали ноль и почему это "
          "было так важно для математики.")


async def main():
    config.setup_console()
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=config.env("GEMINI_API_KEY"))
    cfg = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction="Ты Джарвис. Говори по-русски, живо.",
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Charon"))),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH)),
    )
    chunks = []
    async with client.aio.live.connect(model="gemini-3.1-flash-live-preview", config=cfg) as s:
        await s.send_realtime_input(text=PROMPT)
        t0 = time.monotonic()
        async for msg in s.receive():
            sc = msg.server_content
            if sc and sc.model_turn:
                for p in sc.model_turn.parts or []:
                    if p.inline_data and p.inline_data.data:
                        chunks.append((round(time.monotonic() - t0, 4), len(p.inline_data.data)))
            if sc and sc.turn_complete:
                break

    OUT.write_text(json.dumps(chunks), encoding="utf-8")
    audio_s = sum(n for _, n in chunks) / 48000
    arrive_s = chunks[-1][0] - chunks[0][0]
    sizes = sorted(n / 48 for _, n in chunks)
    # Самые длинные паузы между кусками — относительно того, сколько звука уже пришло
    lag, received, worst = 0.0, 0.0, []
    start = chunks[0][0]
    for i, (t, n) in enumerate(chunks):
        playback_pos = t - start                    # сколько уже проиграли бы без буфера
        if received < playback_pos:
            worst.append((round(playback_pos - received, 3), i))
            received = playback_pos
        received += n / 48000
    worst.sort(reverse=True)
    print(f"кусков: {len(chunks)} · звука {audio_s:.1f} c пришло за {arrive_s:.1f} c")
    print(f"размер куска: от {sizes[0]:.0f} до {sizes[-1]:.0f} мс, медиана {sizes[len(sizes)//2]:.0f} мс")
    print(f"провалов без буфера: {len(worst)}, худшие: {[w[0] for w in worst[:5]]} c")


if __name__ == "__main__":
    asyncio.run(main())
