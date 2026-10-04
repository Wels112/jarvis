# -*- coding: utf-8 -*-
"""Проба механики живого диалога до того, как строить на ней модуль.

Проверяю допущения, на которых будет держаться весь режим:
  1. записанную фразу можно отправить быстрее реального времени — иначе первый
     ответ задерживается на длину самой фразы;
  2. модель вызывает настоящие инструменты, а не выдумывает погоду;
  3. посреди разговора можно подсунуть текст — так Джарвис скажет напоминание
     тем же голосом, не обрывая диалог;
  4. настройка чувствительности конца фразы принимается этой моделью.
"""
import asyncio
import socket
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

_orig = socket.getaddrinfo
socket.getaddrinfo = lambda h, p, f=0, t=0, pr=0, fl=0: _orig(h, p, socket.AF_INET, t, pr, fl)

MODEL = "gemini-3.1-flash-live-preview"
WEATHER_REC = "20260914_193536.wav"   # «Джарвис, какая погода в Санкт-Петербурге»


def weather_tool_decl(types):
    return types.FunctionDeclaration(
        name="weather",
        description="Погода сейчас и на сегодня. Любые вопросы о погоде — только через этот инструмент.",
        parameters=types.Schema(type="OBJECT", properties={
            "city": types.Schema(type="STRING", description="город"),
        }),
    )


async def run_case(name, pace, use_vad_cfg=True, inject=None):
    from google import genai
    from google.genai import types
    from skills import weather as W

    client = genai.Client(api_key=config.env("GEMINI_API_KEY"))
    kwargs = dict(
        response_modalities=["AUDIO"],
        system_instruction=("Ты Джарвис, голосовой помощник. Говоришь по-русски, живо и коротко. "
                            "Погоду никогда не придумывай — только через инструмент weather."),
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Charon"))),
        tools=[types.Tool(function_declarations=[weather_tool_decl(types)])],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )
    if use_vad_cfg:
        kwargs["realtime_input_config"] = types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                silence_duration_ms=500, prefix_padding_ms=200))
    cfg = types.LiveConnectConfig(**kwargs)

    with wave.open(str(config.DATA / "logs" / "audio" / WEATHER_REC)) as w:
        pcm = w.readframes(w.getnframes())
    step = 16000 * 2 * 40 // 1000

    log = []
    t0 = time.time()
    async with client.aio.live.connect(model=MODEL, config=cfg) as s:
        log.append(f"подключение {time.time() - t0:.2f} c")
        t_start = time.time()
        for i in range(0, len(pcm), step):
            await s.send_realtime_input(audio=types.Blob(data=pcm[i:i + step],
                                                         mime_type="audio/pcm;rate=16000"))
            if pace:
                await asyncio.sleep(0.04 / pace)
        await s.send_realtime_input(audio_stream_end=True)
        t_sent = time.time()
        log.append(f"фраза {len(pcm) / 32000:.1f} c отправлена за {t_sent - t_start:.2f} c")

        first_audio = None
        heard = said = ""
        tool_calls = []
        turns = 0
        injected = False
        deadline = time.time() + 40
        while time.time() < deadline:
            async for msg in s.receive():
                if msg.tool_call:
                    responses = []
                    for fc in msg.tool_call.function_calls:
                        tool_calls.append(f"{fc.name}({dict(fc.args or {})})")
                        result = await asyncio.to_thread(W.weather, (fc.args or {}).get("city", ""))
                        responses.append(types.FunctionResponse(id=fc.id, name=fc.name,
                                                                response={"result": result}))
                    await s.send_tool_response(function_responses=responses)
                sc = msg.server_content
                if not sc:
                    continue
                if sc.input_transcription and sc.input_transcription.text:
                    heard += sc.input_transcription.text
                if sc.output_transcription and sc.output_transcription.text:
                    said += sc.output_transcription.text
                if sc.model_turn:
                    for p in sc.model_turn.parts:
                        if p.inline_data and p.inline_data.data and first_audio is None:
                            first_audio = time.time() - t_sent
                if sc.turn_complete:
                    turns += 1
                    break
            if inject and not injected and turns >= 1:
                injected = True
                said += "  ‖ВСТАВКА‖  "
                try:
                    await s.send_realtime_input(text=inject)
                    log.append("текст посреди разговора: send_realtime_input принят")
                except Exception as e:
                    log.append(f"send_realtime_input(text) не принят: {str(e)[:90]}")
                    await s.send_client_content(
                        turns=types.Content(role="user", parts=[types.Part(text=inject)]),
                        turn_complete=True)
                    log.append("текст посреди разговора: ушёл через send_client_content")
                continue
            if turns >= (2 if inject else 1):
                break

    print(f"\n=== {name} ===")
    for line in log:
        print("  " + line)
    lat = f"{first_audio:.2f} c" if first_audio is not None else "нет звука"
    print(f"  от отправки до первого звука: {lat}")
    print(f"  инструменты: {tool_calls or 'не вызывал'}")
    print(f"  услышал: «{heard.strip()}»")
    print(f"  ответил: «{said.strip()}»")


async def main():
    config.setup_console()
    cases = [
        ("темп реального времени", 1, True, None),
        ("в 10 раз быстрее", 10, True, None),
        ("всё разом", 0, True, None),
        ("всё разом + вставка текста", 0, True,
         "Системное напоминание: скажи хозяину вслух, что через десять минут урок с Петей."),
    ]
    for name, pace, vad, inject in cases:
        try:
            await asyncio.wait_for(run_case(name, pace, vad, inject), timeout=90)
        except Exception as e:
            print(f"\n=== {name} ===\n  не вышло: {str(e)[:300]}")


if __name__ == "__main__":
    asyncio.run(main())
