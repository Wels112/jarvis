# -*- coding: utf-8 -*-
"""Сквозная проверка голосового тракта без живого человека.

Идея: Windows-синтезатор наговаривает фразу в WAV, распознаватель слушает этот
файл, роутер разбирает результат. Так проверяется вся цепочка — синтез,
распознавание русского, разбор команды — тем же кодом, что работает вживую.

Живой микрофон это не заменяет (нет фонового шума и акустики комнаты), но
ловит главное: не развалилась ли цепочка целиком.
"""
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

FRASES = [
    ("Джарвис, который час", "время"),
    ("Джарвис, открой блокнот", "программа"),
    ("Джарвис, громкость тридцать", "громкость"),
    ("Джарвис, какие у меня задачи", "задачи"),
    ("Джарвис, запомни что я работаю по ночам", "память"),
    ("Джарвис, сделай потише", "громкость"),
    ("Джарвис, что открыто", "окна"),
    ("Джарвис, какие уроки сегодня", "уроки"),
    ("Джарвис, сколько будет двести плюс сорок", "счёт"),
]

TMP = config.ROOT / "data" / "tts_test"
TMP.mkdir(parents=True, exist_ok=True)


def synth_to_wav(text: str, path: Path) -> bool:
    """Наговорить фразу в файл голосом Ирины."""
    import win32com.client
    try:
        sp = win32com.client.Dispatch("SAPI.SpVoice")
        for v in sp.GetVoices():
            if "irina" in v.GetDescription().lower():
                sp.Voice = v
                break
        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        stream.Format.Type = 22          # 16 кГц, 16 бит, моно — как ждёт whisper
        stream.Open(str(path), 3, False)
        sp.AudioOutputStream = stream
        sp.Speak(text)
        stream.Close()
        return path.exists() and path.stat().st_size > 1000
    except Exception as e:
        print(f"  синтез не удался: {e}")
        return False


def wav_to_float(path: Path):
    import wave
    with wave.open(str(path), "rb") as w:
        frames = w.readframes(w.getnframes())
        rate = w.getframerate()
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if rate != 16000:                    # whisper работает на 16 кГц
        idx = np.round(np.arange(0, len(audio), rate / 16000)).astype(int)
        audio = audio[idx[idx < len(audio)]]
    return audio


def main():
    config.setup_console()
    from faster_whisper import WhisperModel
    from core import router

    print("=" * 66)
    print("  СКВОЗНОЙ ТЕСТ: синтез → распознавание → разбор команды")
    print("=" * 66)
    print("\nподнимаю распознаватель...")
    t0 = time.time()
    model = WhisperModel(config.CFG["ears"]["model"], device="cpu",
                         compute_type="int8", download_root=str(config.MODELS))
    print(f"готов за {time.time()-t0:.1f} c\n")

    good = 0
    total_rt = 0.0
    for i, (phrase, kind) in enumerate(FRASES, 1):
        wav = TMP / f"t{i}.wav"
        if not synth_to_wav(phrase, wav):
            print(f"{i}. [пропуск] {phrase}")
            continue

        audio = wav_to_float(wav)
        dur = len(audio) / 16000
        t1 = time.time()
        segs, _ = model.transcribe(audio, language="ru", beam_size=1,
                                   vad_filter=True, temperature=0.0)
        heard = " ".join(s.text.strip() for s in segs).strip()
        took = time.time() - t1
        total_rt += took / max(dur, 0.01)

        clean = router.strip_wake(router.normalize(heard))
        reply = router.handle(clean, config.CFG)
        answer = reply.say or ("→ отдал бы модели" if reply.to_llm else "")
        hit = bool(reply.say) and not reply.to_llm
        good += hit

        print(f"{i}. сказано:  {phrase}")
        print(f"   услышано: {heard}")
        print(f"   ответ:    {answer[:70]}")
        print(f"   {'OK' if hit else 'мимо'} · звук {dur:.1f} c, распознано за {took:.1f} c\n")

    print("=" * 66)
    print(f"  Понято и выполнено: {good} из {len(FRASES)}")
    print(f"  Скорость распознавания: {total_rt/max(len(FRASES),1):.2f}x от длины фразы")
    print("=" * 66)


if __name__ == "__main__":
    main()
