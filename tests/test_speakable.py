# -*- coding: utf-8 -*-
"""Текст для синтеза: невидимое и разметку выкидываем, срыв связи повторяем.

Повод — проверка установки 05.10.2026. На ответ «что открыто» Microsoft вернул
«No audio was received», и Джарвис заговорил механическим голосом. Первая строка
здесь — тот самый настоящий ответ, с невидимыми метками направления текста,
которые Telegram прячет в заголовках своих окон.

Сразу о неверной догадке: сначала я решил, что синтез падал именно на этих
метках. Проверка показала обратное — строка синтезируется и без очистки, а
«No audio was received» случается от срыва связи и лечится повтором. Очистка
нужна по другой причине: разметку и невидимое не надо читать вслух.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

REAL = ("Открыто 7 окон: (10) Top Twitch Moments | HOUSE TOURS - ; Claude; Jarvis; "
        "Безымянный – Блокнот; \u200eХакатон @ \u200eWels (12944); Калькулятор.")

CASES = [
    (REAL, ["\u200e", "|"]),
    ("Ответ: **важно** и `код`", ["*", "`"]),
    ("Строка\u200bс\u200bневидимыми\u2060пробелами", ["\u200b", "\u2060"]),
    ("Путь C:\\Users\\test\\file", ["\\"]),
    ("Обычный текст без мусора.", []),
]


def main():
    config.setup_console()
    from core.voice import speakable

    errors = 0
    for text, banned in CASES:
        clean = speakable(text)
        left = [b for b in banned if b in clean]
        ok = not left and clean.strip() != ""
        errors += not ok
        shown = clean[:64].replace("\n", " ")
        print(f"{'ok ' if ok else 'НЕТ'} «{shown}»")
        if left:
            print(f"     осталось недопустимое: {[hex(ord(c)) for c in left]}")

    # Пустой и почти пустой текст не должен превращаться в попытку синтеза
    for junk in ("", "   ", "***", "|||", "\u200e\u200b"):
        got = speakable(junk)
        ok = got == ""
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} мусор {junk!r} → {got!r}")

    # Главная проверка: тот самый ответ теперь синтезируется
    print("\nпробую синтез настоящей строки живым голосом...")
    try:
        from core.voice import EdgeSynth
        synth = EdgeSynth(config.CFG)
        pcm, rate = synth.synth(speakable(REAL))
        seconds = len(pcm) / rate
        ok = seconds > 1.0
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} синтез прошёл: {seconds:.1f} с звука")
        # Для записи: первая версия этой проверки считала, что синтез падал
        # из-за невидимых символов. Оказалось нет — та же строка без очистки
        # синтезируется. Настоящая причина «No audio was received» — срыв связи,
        # и лечится он повтором (см. TRANSIENT в core/voice.py).
        try:
            synth.synth(REAL)
            print("   и без очистки прошло — значит дело было не в символах")
        except Exception as e:
            print(f"   без очистки отказ: {str(e)[:60]}")
    except Exception as e:
        print(f"   пропуск: живой синтез недоступен ({type(e).__name__})")

    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
