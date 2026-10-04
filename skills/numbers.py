# -*- coding: utf-8 -*-
"""Русские числительные словами ↔ цифры.

Нужно с двух сторон. На входе: распознавание не всегда переводит «двести сорок»
в 240 — в командах вроде «громкость тридцать» переводит, а в длинной фразе часто
оставляет словами. На выходе: 86.08 синтезатор читает как «восемьдесят шесть
точка ноль восемь», что для денег звучит дико — нужно «восемьдесят шесть рублей
восемь копеек».
"""
import re

ONES = {
    "ноль": 0, "один": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4,
    "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
    "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14,
    "пятнадцать": 15, "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18,
    "девятнадцать": 19,
}
TENS = {
    "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50, "шестьдесят": 60,
    "семьдесят": 70, "восемьдесят": 80, "девяносто": 90,
}
HUNDREDS = {
    "сто": 100, "двести": 200, "триста": 300, "четыреста": 400, "пятьсот": 500,
    "шестьсот": 600, "семьсот": 700, "восемьсот": 800, "девятьсот": 900,
}
SCALES = {"тысяча": 1000, "тысячи": 1000, "тысяч": 1000, "миллион": 10**6,
          "миллиона": 10**6, "миллионов": 10**6}

ALL_WORDS = {**ONES, **TENS, **HUNDREDS}


def words_to_number(text: str) -> str:
    """«двести сорок пять» → «245». Слова, не похожие на числа, не трогает."""
    tokens = text.split()
    out = []
    current = 0          # накопленное внутри текущей группы
    total = 0            # сумма с учётом тысяч и миллионов
    active = False

    def flush():
        nonlocal current, total, active
        if active:
            out.append(str(total + current))
        current, total, active = 0, 0, False

    for tok in tokens:
        w = tok.lower().strip(".,!?;:")
        if w in ALL_WORDS:
            current += ALL_WORDS[w]
            active = True
        elif w in SCALES:
            if not active:
                current = 1
            total += current * SCALES[w]
            current = 0
            active = True
        else:
            flush()
            out.append(tok)
    flush()
    return " ".join(out)


# ---------------- числа для произношения ----------------
def plural(n, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def money(value: float, currency: str = "RUB") -> str:
    """86.08 RUB → «86 рублей 8 копеек». Названия валют — по-русски."""
    names = {
        "RUB": ("рубль", "рубля", "рублей", "копейка", "копейки", "копеек"),
        "USD": ("доллар", "доллара", "долларов", "цент", "цента", "центов"),
        "EUR": ("евро", "евро", "евро", "цент", "цента", "центов"),
        "CNY": ("юань", "юаня", "юаней", "фынь", "фыня", "фыней"),
        "KZT": ("тенге", "тенге", "тенге", "тиын", "тиына", "тиынов"),
        "UAH": ("гривна", "гривны", "гривен", "копейка", "копейки", "копеек"),
        "GBP": ("фунт", "фунта", "фунтов", "пенс", "пенса", "пенсов"),
        "JPY": ("иена", "иены", "иен", "сен", "сена", "сенов"),
        "TRY": ("лира", "лиры", "лир", "куруш", "куруша", "курушей"),
        "BTC": ("биткоин", "биткоина", "биткоинов", "сатоши", "сатоши", "сатоши"),
    }
    n = names.get(currency.upper())
    if not n:
        return f"{round(value, 2)} {currency}"

    whole = int(abs(value))
    frac = int(round((abs(value) - whole) * 100))
    if frac == 100:                      # 9.999 → 10.00, а не «9 рублей 100 копеек»
        whole, frac = whole + 1, 0

    # У евро форма не меняется — «1 евро», «5 евро»
    main = f"{whole} {plural(whole, n[0], n[1], n[2])}"
    if whole >= 1000 or frac == 0:
        return main
    return f"{main} {frac} {plural(frac, n[3], n[4], n[5])}"


def say_number(x) -> str:
    """Число для чтения вслух: целое как есть, дробное — через «и»."""
    if isinstance(x, int) or (isinstance(x, float) and abs(x - round(x)) < 1e-9):
        return str(int(round(x)))
    x = round(float(x), 4)
    whole = int(x)
    frac_str = f"{abs(x - whole):.4f}".rstrip("0")[2:]
    return f"{whole} и {frac_str}" if frac_str else str(whole)


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core import config
    config.setup_console()

    for s in ["двести плюс сорок", "три тысячи пятьсот", "громкость тридцать",
              "сколько будет пятнадцать умножить на восемь", "открой блокнот",
              "один миллион двести тысяч"]:
        print(f"{s:45} -> {words_to_number(s)}")
    print()
    for v, c in [(86.08, "RUB"), (1.0, "USD"), (9999.89, "RUB"), (2.5, "EUR"), (101.0, "RUB")]:
        print(f"{v:>10} {c} -> {money(v, c)}")
    print()
    print(say_number(12.5), "|", say_number(144.0))
