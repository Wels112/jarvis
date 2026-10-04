# -*- coding: utf-8 -*-
"""Живой голос → распознавание: говорит ли Джарвис то, что написано.

Тест родился из реальной регрессии. Silero молча пропускал цифры и латиницу,
и «Громкость 30 процентов» звучала как «Громкость процентов». В журнале всё
было в порядке — текст-то правильный. Поймать такое можно только ушами, а уши
здесь — распознаватель: синтезируем реплику, распознаём и проверяем, что
ключевые слова на месте.

Каждая реплика прогоняется дважды — как есть и после нормализации, — чтобы
разница была видна цифрами, а не на словах.
"""
import sys
import time
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

# (реплика, группы ожидаемого — из каждой группы должен найтись хотя бы один вариант)
CASES = [
    ("Громкость 30 процентов.", [["30", "тридцат"], ["процент"]]),
    ("Сейчас 12 часов 43 минуты.", [["12", "двенадцат"], ["43", "сорок три"]]),
    ("Урок с Петей в 16:30.", [["16", "шестнадцат"], ["30", "тридцат"]]),
    ("Напомню 04.09 в 15:00.", [["сентябр"], ["15", "пятнадцат"]]),
    ("1 доллар стоит 86 рублей 8 копеек.", [["86", "восемьдесят шесть"], ["доллар"]]),
    ("Таймер на 1 минуту.", [["1", "одну"], ["минут"]]),
    ("Сегодня 2 занятия: 16:00 Петя, 18:30 Соня.", [["2", "два", "две"], ["18", "восемнадцат"]]),
    ("Включаю Best of lofi hip hop.", [["хип", "hip"], ["хоп", "hop"]]),
]


def _clean(text: str) -> str:
    from skills.numbers import words_to_number
    # Распознаватель пишет «30%», хотя голос сказал «тридцать процентов» — это не потеря
    t = text.lower().replace("ё", "е").replace("%", " процентов")
    return words_to_number(t)


def _ok(heard: str, groups) -> bool:
    h = _clean(heard)
    return all(any(alt.replace("ё", "е") in h for alt in group) for group in groups)


def main():
    config.setup_console()
    import torch
    from faster_whisper import WhisperModel
    from skills.speech_text import for_tts

    torch.hub.set_dir(str(config.MODELS / "torch" / "hub"))
    torch.set_num_threads(4)
    print("поднимаю голос и слух...")
    tts, _ = torch.hub.load("snakers4/silero-models", "silero_tts", language="ru",
                            speaker="v4_ru", trust_repo=True, verbose=False)
    stt = WhisperModel(config.CFG["ears"]["model"], device="cpu", compute_type="int8",
                       download_root=str(config.MODELS))
    speaker = config.CFG.get("voice", {}).get("silero_speaker", "aidar")

    def hear(text: str) -> str:
        try:
            audio = tts.apply_tts(text=text, speaker=speaker, sample_rate=48000).numpy()
        except Exception:
            return ""                                  # синтезу нечего было сказать
        n = len(audio) // 3 * 3                        # 48 кГц → 16 кГц для распознавания
        a16 = audio[:n].reshape(-1, 3).mean(axis=1).astype(np.float32)
        segs, _ = stt.transcribe(a16, language="ru", beam_size=1, temperature=0.0)
        return " ".join(s.text.strip() for s in segs).strip()

    raw_ok = norm_ok = 0
    t0 = time.time()
    for i, (text, groups) in enumerate(CASES, 1):
        heard_raw = hear(text)
        spoken = for_tts(text)
        heard_norm = hear(spoken)
        r, n = _ok(heard_raw, groups), _ok(heard_norm, groups)
        raw_ok += r
        norm_ok += n
        print(f"\n{i}. {text}")
        print(f"   как есть:          {'OK ' if r else 'ПОТЕРЯ'} «{heard_raw}»")
        print(f"   после нормализации: {'OK ' if n else 'ПОТЕРЯ'} «{heard_norm}»")

    total = len(CASES)
    print("\n" + "=" * 66)
    print(f"  Без нормализации донесено смысла: {raw_ok} из {total}")
    print(f"  С нормализацией:                  {norm_ok} из {total}")
    print(f"  Время прогона: {time.time() - t0:.0f} c")
    print("=" * 66)
    return norm_ok == total


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
