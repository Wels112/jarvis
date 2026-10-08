# -*- coding: utf-8 -*-
"""Новости — свежие заголовки из открытых RSS-лент, без ключей.

08.10.2026 на «какие новости» модель открыла поиск в браузере и сказала «в мире
всё относительно спокойно» — заголовков она не видела, это была выдумка. Здесь
заголовки берутся по-настоящему: РИА Новости, а если лента молчит — ТАСС и
Интерфакс. «Новости про биткоин» — из всех лент, что совпало по словам.
"""
import re
import xml.etree.ElementTree as ET

import requests

FEEDS = [("РИА Новости", "https://ria.ru/export/rss2/archive/index.xml"),
         ("ТАСС", "https://tass.ru/rss/v2.xml"),
         ("Интерфакс", "https://www.interfax.ru/rss.asp")]


def _titles(url: str) -> list:
    r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    root = ET.fromstring(r.content)          # кодировку берёт из самого XML (у Интерфакса — 1251)
    out = []
    for item in root.iter("item"):
        title = re.sub(r"\s+", " ", (item.findtext("title") or "")).strip()
        if title:
            out.append(title)
    return out


def _stems(text: str) -> list:
    return [w[:max(4, len(w) - 2)] for w in re.findall(r"[а-яёa-z0-9]+", text.lower()) if len(w) >= 3]


def headlines(n: int = 5, topic: str = "") -> str:
    """«Главное у РИА Новости: …» — или по теме из всех лент."""
    stems = _stems(topic)
    found, source, errors = [], "", []
    for name, url in FEEDS:
        try:
            titles = _titles(url)
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}")
            continue
        if stems:
            titles = [t for t in titles if all(any(w.startswith(s) for w in re.findall(r"[а-яёa-z0-9]+", t.lower()))
                                               for s in stems)]
            found += [t for t in titles if t not in found]
            continue
        if titles:
            found, source = titles, name
            break
    if not found:
        if stems and len(errors) < len(FEEDS):
            return f"В свежих заголовках про «{topic}» ничего нет."
        return "Новостные ленты не ответили — похоже, нет интернета."
    lines = "; ".join(f"{i}) {t.rstrip('.')}" for i, t in enumerate(found[:n], 1))
    if stems:
        return f"Про «{topic}» в свежих новостях: {lines}."
    return f"Главное у {source}: {lines}."


if __name__ == "__main__":
    from core import config
    config.setup_console()
    print(headlines())
    print(headlines(3, "биткоин"))
