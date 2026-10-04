# -*- coding: utf-8 -*-
"""Текст для синтезатора речи: всё, что голос иначе проглотит молча.

Проверено замером: Silero v4 не читает цифры и латиницу — просто пропускает.
«Громкость 30 процентов» звучит ровно столько же, сколько «Громкость процентов»,
а английское название ролика исчезает целиком. Встроенная Windows-Ирина цифры
читает сама, поэтому нормализация нужна только живому голосу.

Что превращается в слова:
  • числа — с согласованием рода: «1 минута» → «одна минута»,
    «2 задачи» → «две задачи», «1500 рублей» → «тысяча пятьсот рублей»
  • время: «16:30» → «шестнадцать тридцать», «16:00» → «шестнадцать ноль-ноль»
  • даты: «10 сентября» → «десятого сентября», «04.09» → «четвёртого сентября»
  • дроби, проценты, единицы («5 км», «1 ч 20 мин»), знаки
  • латиница — русскими буквами, чтобы английское название хотя бы прозвучало
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from skills.numbers import plural

_ONES = {
    "m": ["ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"],
    "f": ["ноль", "одна", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"],
    "n": ["ноль", "одно", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"],
}
_TEENS = ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать",
          "пятнадцать", "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"]
_TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят",
         "семьдесят", "восемьдесят", "девяносто"]
_HUNDREDS = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот",
             "семьсот", "восемьсот", "девятьсот"]
_SCALES = [
    (10 ** 9, ("миллиард", "миллиарда", "миллиардов"), "m"),
    (10 ** 6, ("миллион", "миллиона", "миллионов"), "m"),
    (10 ** 3, ("тысяча", "тысячи", "тысяч"), "f"),
]

_MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
               "августа", "сентября", "октября", "ноября", "декабря"]
_ORD_GEN = {
    1: "первого", 2: "второго", 3: "третьего", 4: "четвёртого", 5: "пятого",
    6: "шестого", 7: "седьмого", 8: "восьмого", 9: "девятого", 10: "десятого",
    11: "одиннадцатого", 12: "двенадцатого", 13: "тринадцатого", 14: "четырнадцатого",
    15: "пятнадцатого", 16: "шестнадцатого", 17: "семнадцатого", 18: "восемнадцатого",
    19: "девятнадцатого", 20: "двадцатого", 30: "тридцатого",
}

# Род существительного после числа определяет форму: «одна минута», «одно окно»
_FEMININE = ("минут", "секунд", "копе", "гривн", "задач", "недел", "штук", "книг",
             "ошиб", "вкладк", "заметк", "запис", "попытк", "страниц", "лир", "иен",
             "тысяч", "учениц", "девочк", "подписк", "программ", "песн", "картин",
             "строк", "букв", "тонн", "целых", "целая")
_NEUTER = ("окн", "окон", "видео", "заняти", "задани", "евро", "сообщени",
           "упражнени", "очк", "слов", "мест", "числ")

# Сокращения единиц после числа: (одна, две, пять, род)
_UNITS = {
    "км": ("километр", "километра", "километров", "m"),
    "см": ("сантиметр", "сантиметра", "сантиметров", "m"),
    "мм": ("миллиметр", "миллиметра", "миллиметров", "m"),
    "м": ("метр", "метра", "метров", "m"),
    "кг": ("килограмм", "килограмма", "килограммов", "m"),
    "г": ("грамм", "грамма", "граммов", "m"),
    "т": ("тонна", "тонны", "тонн", "f"),
    "гб": ("гигабайт", "гигабайта", "гигабайт", "m"),
    "мб": ("мегабайт", "мегабайта", "мегабайт", "m"),
    "кб": ("килобайт", "килобайта", "килобайт", "m"),
    "ч": ("час", "часа", "часов", "m"),
    "мин": ("минута", "минуты", "минут", "f"),
    "сек": ("секунда", "секунды", "секунд", "f"),
}


# ---------------- числа ----------------
def _below_thousand(n: int, gender: str):
    out = []
    h, rest = divmod(n, 100)
    if h:
        out.append(_HUNDREDS[h])
    if 10 <= rest < 20:
        out.append(_TEENS[rest - 10])
    else:
        t, u = divmod(rest, 10)
        if t:
            out.append(_TENS[t])
        if u:
            out.append(_ONES[gender][u])
    return out


def number_to_words(n: int, gender: str = "m") -> str:
    """1500 → «тысяча пятьсот»; род влияет на единицу и двойку."""
    n = int(n)
    if n == 0:
        return "ноль"
    if abs(n) >= 10 ** 12:                      # такие числа вслух всё равно не нужны
        return " ".join(_ONES["m"][int(d)] for d in str(abs(n)))
    sign = "минус " if n < 0 else ""
    n = abs(n)
    out = []
    for scale, forms, scale_gender in _SCALES:
        q, n = divmod(n, scale)
        if q:
            if q == 1 and not out:              # «тысяча», а не «одна тысяча»
                out.append(forms[0])
            else:
                out += _below_thousand(q, scale_gender)
                out.append(plural(q, *forms))
    if n:
        out += _below_thousand(n, gender)
    return sign + " ".join(out)


def _ordinal_gen(n: int) -> str:
    if n in _ORD_GEN:
        return _ORD_GEN[n]
    t, u = divmod(n, 10)
    return f"{_TENS[t]} {_ORD_GEN[u]}"


def _gender_of(following: str) -> str:
    w = following.lower()
    if w.startswith(_FEMININE):
        return "f"
    if w.startswith(_NEUTER):
        return "n"
    return "m"


def _decimal_words(whole: str, frac: str) -> str:
    """«1.5» → «одна целая пять десятых» — единственная форма, что звучит по-русски."""
    i, f = int(whole), int(frac)
    denominators = {1: ("десятая", "десятых"), 2: ("сотая", "сотых"), 3: ("тысячная", "тысячных")}
    k = len(frac)
    if k > 3 or f == 0:
        return number_to_words(i)
    whole_word = "целая" if i % 10 == 1 and i % 100 != 11 else "целых"
    frac_word = denominators[k][0] if f % 10 == 1 and f % 100 != 11 else denominators[k][1]
    return (f"{number_to_words(i, 'f')} {whole_word} "
            f"{number_to_words(f, 'f')} {frac_word}")


# ---------------- латиница ----------------
_LATIN_WORDS = {
    "youtube": "ютуб", "telegram": "телеграм", "miro": "миро", "google": "гугл",
    "chrome": "хром", "windows": "виндоус", "steam": "стим", "discord": "дискорд",
    "python": "пайтон", "tutorlab": "тьюторлаб", "gemini": "джемини", "claude": "клод",
    "jarvis": "джарвис", "ok": "окей", "wifi": "вайфай", "notepad": "блокнот",
    "the": "зе", "of": "оф", "and": "энд", "to": "ту", "you": "ю", "how": "хау",
    "what": "уот", "new": "нью", "best": "бест", "top": "топ", "music": "мьюзик",
    "work": "ворк", "hour": "ауэр", "hours": "ауэрс", "deep": "дип", "focus": "фокус",
    "study": "стади", "relax": "рилакс", "beats": "битс", "mix": "микс", "live": "лайв",
    "video": "видео", "song": "сонг", "game": "гейм", "play": "плей", "news": "ньюс",
    "lesson": "лессон", "math": "мэс", "school": "скул", "ultimate": "ультимейт",
    "me": "ми", "my": "май", "i": "ай", "is": "из", "are": "ар", "wrong": "ронг",
    "lofi": "лоу-фай", "hip": "хип", "hop": "хоп", "part": "парт", "for": "фор",
}
_SPELL = {
    "a": "эй", "b": "би", "c": "си", "d": "ди", "e": "и", "f": "эф", "g": "джи",
    "h": "эйч", "i": "ай", "j": "джей", "k": "кей", "l": "эл", "m": "эм", "n": "эн",
    "o": "оу", "p": "пи", "q": "кью", "r": "ар", "s": "эс", "t": "ти", "u": "ю",
    "v": "ви", "w": "дабл ю", "x": "экс", "y": "уай", "z": "зед",
}
_DIGRAPHS = [("sch", "ш"), ("tch", "ч"), ("sh", "ш"), ("ch", "ч"), ("th", "т"),
             ("ph", "ф"), ("kh", "х"), ("zh", "ж"), ("ts", "ц"), ("oo", "у"),
             ("ee", "и"), ("ea", "и"), ("ou", "ау"), ("ck", "к"), ("qu", "кв"),
             ("wh", "в"), ("gh", "г"), ("ai", "эй"), ("ay", "эй"), ("oy", "ой")]
_LETTERS = {"a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г",
            "h": "х", "i": "и", "j": "дж", "k": "к", "l": "л", "m": "м", "n": "н",
            "o": "о", "p": "п", "q": "к", "r": "р", "s": "с", "t": "т", "u": "у",
            "v": "в", "w": "в", "x": "кс", "y": "и", "z": "з"}


def transliterate(word: str) -> str:
    low = word.lower()
    if low in _LATIN_WORDS:
        return _LATIN_WORDS[low]
    # Короткие аббревиатуры и слова без гласных читаются по буквам: USB, API, PDF
    if word.isupper() and (len(word) <= 3 or not re.search(r"[aeiouy]", low)):
        return " ".join(_SPELL[c] for c in low if c in _SPELL)
    out, i = [], 0
    while i < len(low):
        for lat, cyr in _DIGRAPHS:
            if low.startswith(lat, i):
                out.append(cyr)
                i += len(lat)
                break
        else:
            ch = low[i]
            nxt = low[i + 1] if i + 1 < len(low) else ""
            if ch == "c" and nxt in ("e", "i", "y"):
                out.append("с")
            elif ch == "y" and i == 0:
                out.append("й")
            elif ch == "e" and i == len(low) - 1 and len(low) > 3:
                pass                                     # немая «e» на конце
            else:
                out.append(_LETTERS.get(ch, ""))
            i += 1
    return "".join(out)


# ---------------- главная функция ----------------
_EMOJI = re.compile("[\U00010000-\U0010FFFF☀-➿️‍]")


def for_tts(text: str) -> str:
    """Причесать реплику перед живым голосом. Порядок замен важен:
    сначала время и даты, иначе «16:30» разберётся как два отдельных числа."""
    t = _EMOJI.sub("", str(text))
    t = t.replace("[", " ").replace("]", " ").replace("/", " ")

    # время 16:30
    def _time(m):
        hh, mm = int(m.group(1)), m.group(2)
        if mm == "00":
            tail = "ноль-ноль"
        elif mm.startswith("0"):
            tail = "ноль " + _ONES["f"][int(mm[1])]
        else:
            tail = number_to_words(int(mm), "f")
        return f"{number_to_words(hh)} {tail}"
    t = re.sub(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", _time, t)

    # дата «10 сентября»
    t = re.sub(r"\b([1-9]|[12]\d|3[01])\s+(" + "|".join(_MONTHS_GEN) + r")\b",
               lambda m: f"{_ordinal_gen(int(m.group(1)))} {m.group(2)}", t)

    # дата «04.09» — месяц двузначный, чтобы не спутать с дробью «1.1 миллиона»
    t = re.sub(r"\b(0?[1-9]|[12]\d|3[01])\.(0[1-9]|1[0-2])\b(?!\.\d)",
               lambda m: f"{_ordinal_gen(int(m.group(1)))} {_MONTHS_GEN[int(m.group(2)) - 1]}", t)

    # проценты
    t = re.sub(r"(\d+)\s*%",
               lambda m: f"{number_to_words(int(m.group(1)))} "
                         f"{plural(int(m.group(1)), 'процент', 'процента', 'процентов')}", t)

    # единицы после числа: «5 км», «1 ч 20 мин»
    unit_names = "|".join(sorted(_UNITS, key=len, reverse=True))
    def _unit(m):
        num, unit = m.group(1), m.group(2).lower()
        one, few, many, gender = _UNITS[unit]
        if re.search(r"[.,]", num):
            whole, frac = re.split(r"[.,]", num)
            return f"{_decimal_words(whole, frac)} {few}"
        n = int(num)
        return f"{number_to_words(n, gender)} {plural(n, one, few, many)}"
    t = re.sub(rf"(\d+(?:[.,]\d+)?)\s*({unit_names})\b(?!\w)", _unit, t, flags=re.I)

    # дробные
    t = re.sub(r"(?<![\d:])(\d+)[.,](\d+)(?![\d:])",
               lambda m: _decimal_words(m.group(1), m.group(2)), t)

    # знаки
    t = (t.replace("№", " номер ").replace("+", " плюс ").replace("=", " равно ")
          .replace("×", " умножить на ").replace("&", " и "))

    # целые — с родом и падежом по следующему слову
    def _int(m):
        after = re.match(r"\s*([а-яёА-ЯЁ]+)", t[m.end():m.end() + 24])
        word = after.group(1).lower() if after else ""
        gender = _gender_of(word) if word else "m"
        n = int(m.group(0))
        spoken = number_to_words(n, gender)
        # «на 1 минуту» — винительный падеж: «одну», а не «одна»
        if gender == "f" and n % 10 == 1 and n % 100 != 11 and word.endswith(("у", "ю")):
            spoken = spoken[:-len("одна")] + "одну" if spoken.endswith("одна") else spoken
        return spoken
    t = re.sub(r"\d{1,12}", _int, t)

    # буква диска читается по-русски: «диск цэ», а не «диск си»
    drive_letters = {"c": "цэ", "d": "дэ", "e": "е", "f": "эф", "g": "гэ"}
    t = re.sub(r"\b(диск\w*)\s+([A-Ga-g])\b",
               lambda m: f"{m.group(1)} {drive_letters[m.group(2).lower()]}", t)

    # латиница
    t = re.sub(r"[A-Za-z]+", lambda m: transliterate(m.group(0)), t)

    t = re.sub(r"\s+([.,!?;:])", r"\1", t)       # пробел перед знаком после чисток
    return re.sub(r"\s+", " ", t).strip()


if __name__ == "__main__":
    from core import config
    config.setup_console()
    samples = [
        "Громкость 30 процентов.",
        "Сейчас 12 часов 43 минуты, пятница, 11 сентября.",
        "Сегодня 2 занятия: 16:00 Петя — математика; 18:30 Соня — информатика.",
        "Записал: позвонить маме. Напомню 04.09 в 15:00.",
        "Следующий — Соня через 17 ч 42 мин.",
        "1 доллар стоит 86 рублей 8 копеек.",
        "Канал MrBeast: 515 миллионов подписчиков, 138.9 миллиарда просмотров.",
        "Включаю: Best of lofi hip hop 2021 ✨ [beats to relax/study to].",
        "Таймер на 1 минуту. На диске C свободно 7.6 ГБ.",
        "5 км — это 5000 м. Урок стоит 1500 рублей, открыто 1 окно и 2 вкладки.",
    ]
    for s in samples:
        print(f"• {s}\n  → {for_tts(s)}\n")
