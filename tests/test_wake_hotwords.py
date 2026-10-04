# -*- coding: utf-8 -*-
"""Подсказка распознавателю: помогает ли hotwords узнавать «Джарвис».

Проверка в обе стороны, потому что у подсказок известный побочный эффект:
распознаватель начинает вставлять подсказанное слово туда, где его не было.
Для ассистента это хуже, чем не узнать имя, — он будет срабатывать на
посторонний разговор. Поэтому считаем и узнавания, и ложные «Джарвисы».

Фразы озвучиваются нейросетевыми голосами Microsoft: они звучат как живые люди
и гораздо ближе к голосу хозяина, чем механическая Ирина, на которой
подгонялся прошлый шаблон.
"""
import asyncio
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

WITH_NAME = [
    "Джарвис, который час?",
    "Джарвис, какая погода в Санкт-Петербурге?",
    "Джарвис, объясни, что такое простое число.",
    "Джарвис, расскажи подробную историю математики.",
    "Джарвис, добавь ученика Петя.",
    "Открой браузер, Джарвис.",
]
WITHOUT_NAME = [
    "Какая сегодня погода?",
    "Мы жарим картошку на ужин.",
    "Громкость пятьдесят.",
    "Сегодня был жаркий день.",
    "Добавь ученика Петя, математика.",
    "Стоп.",
]
VOICES = ["ru-RU-DmitryNeural", "ru-RU-SvetlanaNeural"]

MODES = {
    "без подсказки": {},
    "hotwords": {"hotwords": "Джарвис"},
    "initial_prompt": {"initial_prompt": "Джарвис"},
}

TMP = config.DATA / "wake_test"
TMP.mkdir(parents=True, exist_ok=True)


def synth(text: str, voice: str, path: Path):
    import edge_tts
    if path.exists() and path.stat().st_size > 1000:
        return
    asyncio.run(edge_tts.Communicate(text, voice).save(str(path)))


def main():
    config.setup_console()
    from faster_whisper import WhisperModel
    from core import wake

    print("готовлю аудио...")
    clips = []
    i = 0
    for voice in VOICES:
        for text in WITH_NAME + WITHOUT_NAME:
            i += 1
            path = TMP / f"{i:02d}.mp3"
            synth(text, voice, path)
            clips.append((text, text in WITH_NAME, voice, path))

    model = WhisperModel(config.CFG["ears"]["model"], device="cpu", compute_type="int8",
                         download_root=str(config.MODELS), cpu_threads=4)

    summary = {}
    for mode, extra in MODES.items():
        hits = false_wakes = 0
        misses = []
        t0 = time.time()
        for text, has_name, voice, path in clips:
            segs, _ = model.transcribe(str(path), language="ru", beam_size=1,
                                       vad_filter=True, temperature=0.0,
                                       condition_on_previous_text=False, **extra)
            heard = " ".join(s.text.strip() for s in segs).strip()
            found, _rest = wake.find(heard.lower())
            if has_name and found:
                hits += 1
            elif has_name:
                misses.append(heard)
            elif found:
                false_wakes += 1
                misses.append(f"ЛОЖНОЕ: {heard}")
        n_name = sum(1 for c in clips if c[1])
        n_plain = len(clips) - n_name
        summary[mode] = (hits, n_name, false_wakes, n_plain, time.time() - t0)
        print(f"\n=== {mode} ===")
        print(f"  узнал имя: {hits} из {n_name} · ложных срабатываний: {false_wakes} из {n_plain}")
        for m in misses:
            print(f"    · {m}")

    print("\n" + "=" * 66)
    for mode, (h, nh, f, nf, el) in summary.items():
        print(f"  {mode:15} имя {h}/{nh} · ложные {f}/{nf} · {el:.0f} c")
    print("=" * 66)


if __name__ == "__main__":
    main()
