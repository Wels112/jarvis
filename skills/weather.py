# -*- coding: utf-8 -*-
"""Погода. Open-Meteo — бесплатно и вовсе без ключа, что важно при нулевом бюджете.

Город запоминается: спросил один раз «погода в Москве» — дальше просто «погода».
Ответ формулируется для произношения вслух, а не для чтения глазами.
"""
import socket
import sys
from pathlib import Path

import requests
import urllib3.util.connection as urllib3_conn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

urllib3_conn.allowed_gai_family = lambda: socket.AF_INET      # IPv6 тут мёртв

GEO = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
CITY_FILE = config.DATA / "city.txt"

# Коды погоды WMO → живая русская речь
WMO = {
    0: "ясно", 1: "почти ясно", 2: "переменная облачность", 3: "пасмурно",
    45: "туман", 48: "изморозь",
    51: "морось", 53: "морось", 55: "сильная морось",
    56: "ледяная морось", 57: "ледяная морось",
    61: "небольшой дождь", 63: "дождь", 65: "сильный дождь",
    66: "ледяной дождь", 67: "ледяной дождь",
    71: "небольшой снег", 73: "снег", 75: "сильный снег", 77: "снежная крупа",
    80: "ливень", 81: "ливень", 82: "сильный ливень",
    85: "снегопад", 86: "сильный снегопад",
    95: "гроза", 96: "гроза с градом", 99: "сильная гроза с градом",
}


def _saved_city() -> str:
    if CITY_FILE.exists():
        return CITY_FILE.read_text(encoding="utf-8").strip()
    return ""


def remember_city(city: str):
    CITY_FILE.write_text(city.strip(), encoding="utf-8")


# Речь идёт в падеже: «погода в питере» → геокодер ищет «питере» и не находит.
NICKNAMES = {
    "питер": "Санкт-Петербург", "спб": "Санкт-Петербург", "мск": "Москва",
    "нижний": "Нижний Новгород", "ебург": "Екатеринбург", "екб": "Екатеринбург",
    "новосиб": "Новосибирск", "ростов": "Ростов-на-Дону",
}


def _candidates(city: str):
    """Варианты написания: как есть, по прозвищу, с отрезанным падежным окончанием."""
    c = city.strip().lower()
    seen, out = set(), []

    def add(v):
        v = v.strip()
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)

    add(city.strip())
    if c in NICKNAMES:
        add(NICKNAMES[c])
    for nick, full in NICKNAMES.items():
        if c.startswith(nick):
            add(full)
    for end in ("е", "и", "у", "ы", "ах", "ях", "ой", "ом"):
        if len(c) > 4 and c.endswith(end):
            add(city[: -len(end)])
            add(city[: -len(end)] + "а")     # «москве» → «москв» → «москва»
    return out


GEO_CACHE = config.DATA / "geo_cache.json"


def _geocode(city: str):
    """Координаты города. Запоминаются: город не переезжает, а лишний запрос —
    это треть секунды в каждом ответе про погоду в живом разговоре."""
    import json
    key = city.strip().lower()
    cache = {}
    if GEO_CACHE.exists():
        try:
            cache = json.loads(GEO_CACHE.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    if key in cache:
        return tuple(cache[key])

    for cand in _candidates(city):
        try:
            r = requests.get(GEO, params={"name": cand, "count": 1, "language": "ru"},
                             timeout=15)
            r.raise_for_status()
            items = r.json().get("results") or []
            if items:
                it = items[0]
                found = (it["latitude"], it["longitude"], it["name"])
                cache[key] = list(found)
                try:
                    GEO_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass
                return found
        except Exception:
            continue
    return None


def _temp_word(t: float) -> str:
    """«минус пять» звучит лучше, чем «-5», а целые числа лучше дробных."""
    t = round(t)
    if t == 0:
        return "ноль"
    return f"минус {abs(t)}" if t < 0 else str(t)


def _degrees(t: float) -> str:
    n = abs(round(t))
    if n % 10 == 1 and n % 100 != 11:
        return "градус"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "градуса"
    return "градусов"


def weather(city: str = "") -> str:
    city = (city or _saved_city()).strip()
    if not city:
        return "Не знаю твой город. Скажи «погода в Москве», и я запомню."
    try:
        geo = _geocode(city)
        if not geo:
            return f"Не нашёл город «{city}»."
        lat, lon, name = geo
        r = requests.get(FORECAST, params={
            "latitude": lat, "longitude": lon,
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,weather_code",
            "timezone": "auto", "forecast_days": 1,
        }, timeout=15)
        r.raise_for_status()
        d = r.json()
        cur = d["current"]
        day = d["daily"]

        t = cur["temperature_2m"]
        feels = cur["apparent_temperature"]
        desc = WMO.get(cur["weather_code"], "непонятно что")
        wind = round(cur["wind_speed_10m"])
        tmax, tmin = day["temperature_2m_max"][0], day["temperature_2m_min"][0]

        remember_city(name)          # каноническое «Москва», а не услышанное «москве»
        parts = [f"В городе {name} сейчас {_temp_word(t)} {_degrees(t)}, {desc}"]
        if abs(feels - t) >= 3:
            parts.append(f"ощущается как {_temp_word(feels)}")
        if wind >= 8:
            parts.append(f"ветер {wind} метров в секунду")
        parts.append(f"днём от {_temp_word(tmin)} до {_temp_word(tmax)}")
        return ", ".join(parts) + "."
    except Exception as e:
        return f"Погода не отвечает: {e}"


if __name__ == "__main__":
    config.setup_console()
    print(weather("Москва"))
    print(weather())          # проверяем, что город запомнился
