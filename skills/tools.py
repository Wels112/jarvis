# -*- coding: utf-8 -*-
"""Бытовые мелочи: счёт, деньги, единицы, будильник, перевод.

Всё, что человек спрашивает у ассистента между делом. Курсы валют берутся
с бесплатного открытого API без ключа; счёт и единицы считаются на месте,
поэтому работают даже без сети.

Важно про счёт: выражение не отдаётся eval, а разбирается ограниченным
парсером. Голосом легко надиктовать что угодно, и eval превратил бы ассистента
в дыру размером с систему.
"""
import ast
import math
import operator
import re
import socket
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests
import urllib3.util.connection as urllib3_conn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config, memory
from skills.numbers import words_to_number, money, say_number

urllib3_conn.allowed_gai_family = lambda: socket.AF_INET


# ---------------- калькулятор ----------------
_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.USub: operator.neg, ast.UAdd: operator.pos, ast.FloorDiv: operator.floordiv,
}
_FUNCS = {
    "корень": math.sqrt, "sqrt": math.sqrt, "квадрат": lambda x: x * x,
    "синус": math.sin, "косинус": math.cos, "логарифм": math.log,
    "модуль": abs, "округли": round,
}

WORDS_TO_SIGNS = [
    (r"\bплюс\b", "+"), (r"\bминус\b", "-"),
    (r"\b(умножить на|умножить|на|умноженное на|раз)\b", "*"),
    (r"\b(разделить на|разделить|делить на|поделить на|поделить)\b", "/"),
    (r"\b(в степени|степень)\b", "**"),
    (r"\bпроцентов? от\b", "%OF%"),
    (r"\bзапятая\b", "."),
]


def _safe_eval(node):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("только числа")
    if isinstance(node, ast.BinOp):
        op = _OPS.get(type(node.op))
        if not op:
            raise ValueError("неизвестная операция")
        return op(_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp):
        op = _OPS.get(type(node.op))
        if not op:
            raise ValueError("неизвестная операция")
        return op(_safe_eval(node.operand))
    raise ValueError("так считать не умею")


def _pretty(x: float) -> str:
    return say_number(x)


def calculate(expr: str) -> str:
    """«сколько будет двести плюс сорок» → «240»."""
    # Сначала числительные словами: распознавание часто оставляет их как есть
    e = words_to_number(expr.lower().strip())
    for pattern, sign in WORDS_TO_SIGNS:
        e = re.sub(pattern, sign, e)

    # «15 процентов от 2000» — отдельная форма, в обычную арифметику не ложится
    m = re.search(r"([\d.]+)\s*%OF%\s*([\d.]+)", e)
    if m:
        val = float(m.group(1)) / 100 * float(m.group(2))
        return f"Это {_pretty(val)}."

    for name, fn in _FUNCS.items():
        m = re.search(rf"{name}\s+(?:из\s+)?([\d.]+)", e)
        if m:
            try:
                return f"Это {_pretty(fn(float(m.group(1))))}."
            except Exception:
                return "Так посчитать не выйдет."

    e = re.sub(r"[^\d+\-*/%.() ]", " ", e).strip()
    if not e or not re.search(r"\d", e):
        return "Не понял, что считать."
    try:
        tree = ast.parse(e, mode="eval")
        return f"Получается {_pretty(_safe_eval(tree.body))}."
    except ZeroDivisionError:
        return "На ноль делить нельзя."
    except Exception:
        return "Не смог это посчитать."


# ---------------- валюты ----------------
# Ключ — основа слова: голосом валюта приходит в любом падеже
# («курс доллара», «сто долларов», «перевести в рубли»).
CUR_STEMS = [
    ("доллар", "USD"), ("долар", "USD"), ("бакс", "USD"), ("usd", "USD"),
    ("евро", "EUR"), ("eur", "EUR"),
    ("рубл", "RUB"), ("руб", "RUB"), ("rub", "RUB"),
    ("юан", "CNY"), ("тенге", "KZT"), ("гривн", "UAH"), ("гривен", "UAH"),
    ("фунт", "GBP"), ("иен", "JPY"), ("лир", "TRY"),
    ("биткоин", "BTC"), ("btc", "BTC"),
]


def _currency_code(word: str) -> str:
    w = word.lower().strip()
    for stem, code in CUR_STEMS:
        if w.startswith(stem):
            return code
    return w.upper()


RATES_URL = "https://open.er-api.com/v6/latest/{base}"


def _rate(base: str, quote: str):
    r = requests.get(RATES_URL.format(base=base), timeout=15)
    r.raise_for_status()
    data = r.json()
    if data.get("result") != "success":
        raise RuntimeError("сервис курсов недоступен")
    rate = data["rates"].get(quote)
    if rate is None:
        raise RuntimeError(f"нет курса {quote}")
    return rate


def convert_currency(amount: float, frm: str, to: str = "RUB") -> str:
    frm, to = _currency_code(frm), _currency_code(to)
    try:
        value = float(amount) * _rate(frm, to)
        # money() говорит «сто евро», а не «100 EUR» — латиницу синтезатор коверкает
        return f"{money(float(amount), frm)} — это {money(value, to)}."
    except Exception as e:
        return f"Курс не получил: {e}"


# Криптовалюты — у сервиса курсов их нет, «сколько стоит биткоин» кончалось
# «сервис курсов недоступен» (проверка 08.10.2026). CoinGecko отдаёт цену без ключа
CRYPTO = {"биткоин": ("bitcoin", "Биткоин"), "биткойн": ("bitcoin", "Биткоин"),
          "bitcoin": ("bitcoin", "Биткоин"), "btc": ("bitcoin", "Биткоин"),
          "эфир": ("ethereum", "Эфир"), "ethereum": ("ethereum", "Эфир"), "eth": ("ethereum", "Эфир"),
          "тон": ("the-open-network", "TON"), "toncoin": ("the-open-network", "TON"),
          "ton": ("the-open-network", "TON"), "солан": ("solana", "Солана"),
          "solana": ("solana", "Солана"), "usdt": ("tether", "USDT"), "тезер": ("tether", "USDT"),
          "догикоин": ("dogecoin", "Догикоин"), "dogecoin": ("dogecoin", "Догикоин")}


def crypto_price(word: str) -> str:
    """Цена криптовалюты в долларах и рублях; '' — это не криптовалюта."""
    w = word.lower().strip()
    key = next((k for k in CRYPTO if w.startswith(k)), None)
    if not key or (key == "тон" and w not in ("тон", "тона", "тоне", "тону")):  # «тонна» — не монета
        return ""
    coin, title = CRYPTO[key]
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price",
                         params={"ids": coin, "vs_currencies": "usd,rub"}, timeout=15)
        r.raise_for_status()
        price = r.json()[coin]
        return f"{title} стоит {money(price['usd'], 'USD')} — это {money(price['rub'], 'RUB')}."
    except Exception as e:
        return f"Цену {title} не получил: {e}"


def exchange_rate(cur: str = "USD") -> str:
    crypto = crypto_price(cur)
    if crypto:
        return crypto
    cur = _currency_code(cur)
    try:
        value = _rate(cur, "RUB")
        return f"{money(1, cur)} стоит {money(value, 'RUB')}."
    except Exception as e:
        return f"Курс не получил: {e}"


# ---------------- единицы ----------------
UNITS = {
    ("км", "м"): 1000, ("м", "см"): 100, ("см", "мм"): 10, ("км", "миль"): 0.621371,
    ("кг", "г"): 1000, ("кг", "фунтов"): 2.20462, ("т", "кг"): 1000,
    ("час", "минут"): 60, ("минут", "секунд"): 60, ("сутки", "час"): 24,
    ("гб", "мб"): 1024, ("мб", "кб"): 1024,
}


def convert_unit(amount: float, frm: str, to: str) -> str:
    frm, to = frm.lower().strip(), to.lower().strip()
    k = UNITS.get((frm, to))
    if k is None:
        k_back = UNITS.get((to, frm))
        if k_back:
            k = 1 / k_back
    if k is None:
        return f"Не знаю, как перевести {frm} в {to}."
    return f"{_pretty(float(amount))} {frm} — это {_pretty(round(float(amount) * k, 4))} {to}."


def celsius_to_f(c: float) -> str:
    return f"{_pretty(c)} градусов Цельсия — это {_pretty(round(c * 9 / 5 + 32, 1))} по Фаренгейту."


# ---------------- будильник ----------------
def set_alarm(time_text: str) -> str:
    """«разбуди в 7 утра» — обычная задача с пометкой, чтобы звучала иначе."""
    now = datetime.now()
    m = re.search(r"(\d{1,2})(?:[:.\s](\d{2}))?", time_text)
    if not m:
        return "Не понял, на сколько ставить будильник."
    hh, mm = int(m.group(1)), int(m.group(2) or 0)
    low = time_text.lower()
    if "вечера" in low and hh < 12:
        hh += 12
    if "утра" in low and hh == 12:
        hh = 0
    when = now.replace(hour=hh % 24, minute=mm, second=0, microsecond=0)
    if when <= now:
        when += timedelta(days=1)          # «в 7» после семи — значит завтра
    minutes = (when - now).total_seconds() / 60
    memory.add_timer(minutes, "будильник")
    day = "сегодня" if when.date() == now.date() else "завтра"
    return f"Будильник на {when:%H:%M}, {day}."


# ---------------- перевод ----------------
def translate(text: str, to: str = "en") -> str:
    """Перевод без ключа.

    Основной путь — MyMemory: у него честный бесплатный лимит и он не отвечает
    отказом на первый же запрос. Публичный эндпоинт Google оставлен запасным:
    он быстрее и качественнее, но регулярно отдаёт 429.
    """
    src = "ru" if to != "ru" else "en"
    try:
        r = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"q": text[:480], "langpair": f"{src}|{to}"},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        out = (data.get("responseData") or {}).get("translatedText", "").strip()
        if out and "MYMEMORY WARNING" not in out.upper():
            return out
    except Exception:
        pass

    try:
        r = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "auto", "tl": to, "dt": "t", "q": text},
            timeout=15,
        )
        r.raise_for_status()
        return "".join(p[0] for p in r.json()[0] if p and p[0])
    except Exception as e:
        return f"Перевести не вышло: {e}"


if __name__ == "__main__":
    config.setup_console()
    print(calculate("двести плюс сорок"))
    print(calculate("15 процентов от 2000"))
    print(calculate("корень из 144"))
    print(calculate("18 умножить на 7"))
    print(convert_unit(5, "км", "м"))
    print(celsius_to_f(25))
    print(exchange_rate("доллар"))
    print(convert_currency(100, "евро", "рубль"))
    print(translate("Привет, как дела?"))
    print(set_alarm("в 7 утра"))
