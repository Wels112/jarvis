# -*- coding: utf-8 -*-
"""«Проверь связь» — почему умный режим не работает: VPN выключен или сервер не тот.

09.10.2026 хозяин включил VPN, а Gemini всё равно отвечал «User location is not
supported»: интернет шёл через Германию, но Google считал адрес того сервера
российским. Джарвис говорил «похоже, выключен VPN» — неправда, и непонятно,
что делать. Здесь — выход в интернет (страна по адресу) и ответ самого Gemini,
и из них — что именно сказать.
"""
import time

import requests

COUNTRIES = {"RU": "Россию", "DE": "Германию", "NL": "Нидерланды", "US": "США", "FI": "Финляндию",
             "GB": "Великобританию", "FR": "Францию", "SE": "Швецию", "PL": "Польшу", "LV": "Латвию",
             "EE": "Эстонию", "LT": "Литву", "KZ": "Казахстан", "TR": "Турцию", "AE": "ОАЭ",
             "JP": "Японию", "SG": "Сингапур", "CH": "Швейцарию", "AT": "Австрию", "CZ": "Чехию",
             "RO": "Румынию", "MD": "Молдову", "GE": "Грузию", "AM": "Армению", "BY": "Беларусь",
             "HK": "Гонконг", "CN": "Китай", "IR": "Иран"}
_cache = {"at": 0.0, "country": ""}


def exit_country(max_age: float = 300) -> str:
    """Код страны, через которую компьютер выходит в интернет ('' — не узнать)."""
    if time.time() - _cache["at"] < max_age:
        return _cache["country"]
    country = ""
    for url, field in (("https://ipinfo.io/json", "country"), ("http://ip-api.com/json", "countryCode")):
        try:
            country = (requests.get(url, timeout=8).json().get(field) or "").upper()
            if country:
                break
        except Exception:
            continue
    _cache.update(at=time.time(), country=country)
    return country


def where(country: str) -> str:
    return COUNTRIES.get(country, country or "неизвестную страну")


def gemini_status(cloud) -> str:
    """'ok' | 'location' | 'key' | 'quota' | 'net' | 'nokey' — крошечным запросом, один токен ответа."""
    if cloud is None or not getattr(cloud, "ready", False):
        return "nokey"
    try:
        cloud._post({"contents": [{"role": "user", "parts": [{"text": "1"}]}],
                     "generationConfig": {"maxOutputTokens": 1}}, timeout=12)
        return "ok"
    except Exception as e:
        text = str(e)
        if "location is not supported" in text or "FAILED_PRECONDITION" in text:
            return "location"
        if "429" in text or "RESOURCE_EXHAUSTED" in text:
            return "quota"
        if "403" in text or "API key" in text:
            return "key"
        return "net"


def blocked_phrase(country: str) -> str:
    """Что сказать, когда Google не пускает по стране, — с учётом того, где выход."""
    if not country:
        return "Google не пускает умный режим. Проверь VPN."
    if country == "RU":
        return "Google не пускает из России — VPN выключен или не работает. Включи его."
    return (f"VPN включён, интернет идёт через {where(country)}, но Google считает адрес этого сервера "
            "российским и не пускает. Выбери в VPN другой сервер — например, Нидерланды или США.")


def check(cloud=None) -> str:
    """Ответ на «проверь связь»."""
    country = exit_country(max_age=0)
    status = gemini_status(cloud)
    if status == "ok":
        return (f"Связь в порядке: интернет идёт через {where(country)}, умный режим работает."
                if country else "Связь в порядке, умный режим работает.")
    if status == "location":
        return blocked_phrase(country)
    if status == "nokey":
        return "Ключа Gemini нет — умный режим не подключён. Простые команды работают."
    if status == "quota":
        return "Связь есть, но лимит запросов Gemini на сейчас исчерпан — подожди минуту."
    if status == "key":
        return "Связь есть, но ключ Gemini не подходит — проверь его в config\\.env."
    if not country:
        return "Интернета нет — ни Google, ни проверка адреса не отвечают."
    return f"Интернет есть (через {where(country)}), но Google не отвечает. Попробуй через минуту."


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core import config
    from core.brain import Brain
    config.setup_console()
    print(check(Brain(config.CFG)))
