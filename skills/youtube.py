# -*- coding: utf-8 -*-
"""YouTube: статистика канала, свежие ролики, поиск.

Работает на обычном API-ключе (он у хозяина уже был от проекта ytfactory).
Ключ даёт публичные данные любого канала — этого хватает, чтобы голосом
спрашивать «сколько подписчиков» и «как зашёл последний ролик». Приватные
операции (загрузка, ответы на комментарии) требуют OAuth — под них оставлен
задел в upload_ready().
"""
import socket
import sys
from pathlib import Path

import requests
import urllib3.util.connection as urllib3_conn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

urllib3_conn.allowed_gai_family = lambda: socket.AF_INET      # IPv6 на этой машине мёртв

BASE = "https://www.googleapis.com/youtube/v3"


def _key():
    return config.env("YOUTUBE_API_KEY")


def _get(endpoint: str, **params):
    params["key"] = _key()
    r = requests.get(f"{BASE}/{endpoint}", params=params, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"{r.status_code} {r.text[:200]}")
    return r.json()


def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _human(n) -> str:
    """Числа для произношения: 515000000 → «515 миллионов», а не цифра за цифрой."""
    n = int(n)
    if n >= 1_000_000_000:
        v = n / 1_000_000_000
        return f"{v:.1f}".rstrip("0").rstrip(".") + " " + _plural(round(v), "миллиард", "миллиарда", "миллиардов")
    if n >= 1_000_000:
        v = n / 1_000_000
        return f"{v:.1f}".rstrip("0").rstrip(".") + " " + _plural(round(v), "миллион", "миллиона", "миллионов")
    if n >= 10_000:
        v = round(n / 1000)
        return f"{v} " + _plural(v, "тысяча", "тысячи", "тысяч")
    return str(n)


def _qty(n, one: str, few: str, many: str) -> str:
    """«515 миллионов подписчиков» — склонение по видимому числу, а не по исходному."""
    n = int(n)
    for div, u1, u2, u5 in ((1_000_000_000, "миллиард", "миллиарда", "миллиардов"),
                            (1_000_000, "миллион", "миллиона", "миллионов"),
                            (10_000, "тысяча", "тысячи", "тысяч")):
        if n >= div:
            shown = n / div if div > 10_000 else round(n / 1000)
            num = f"{shown:.1f}".rstrip("0").rstrip(".") if div > 10_000 else str(shown)
            whole = float(num.replace(",", "."))
            unit = _plural(int(whole) if whole == int(whole) else 2, u1, u2, u5)
            return f"{num} {unit} {many}"
    return f"{n} {_plural(n, one, few, many)}"


def _clean(text: str) -> str:
    """YouTube отдаёт заголовки с HTML-мусором вроде &#39; — вслух это каша."""
    import html
    return html.unescape(text or "")


def resolve_channel(handle_or_id: str) -> str:
    """@handle или название → channelId."""
    h = handle_or_id.strip().lstrip("@")
    if h.startswith("UC") and len(h) > 20:
        return h
    try:
        d = _get("channels", part="id", forHandle=h)
        if d.get("items"):
            return d["items"][0]["id"]
    except Exception:
        pass
    d = _get("search", part="snippet", q=h, type="channel", maxResults=1)
    if d.get("items"):
        return d["items"][0]["snippet"]["channelId"]
    raise RuntimeError(f"канал «{handle_or_id}» не найден")


def channel_stats(channel: str = None) -> str:
    if not _key():
        return "Нет ключа YouTube."
    channel = channel or config.env("YOUTUBE_CHANNEL", "")
    if not channel:
        return "Не знаю, какой канал смотреть. Скажи «мой канал такой-то», я запомню."
    try:
        cid = resolve_channel(channel)
        d = _get("channels", part="snippet,statistics", id=cid)
        it = d["items"][0]
        s, sn = it["statistics"], it["snippet"]
        subs = int(s.get("subscriberCount", 0))
        views = int(s.get("viewCount", 0))
        vids = int(s.get("videoCount", 0))
        return (f"Канал {_clean(sn['title'])}: "
                f"{_qty(subs,'подписчик','подписчика','подписчиков')}, "
                f"{_qty(views,'просмотр','просмотра','просмотров')}, "
                f"{vids} видео.")
    except Exception as e:
        return f"YouTube не ответил: {e}"


def latest_videos(channel: str = None, n: int = 3) -> str:
    if not _key():
        return "Нет ключа YouTube."
    channel = channel or config.env("YOUTUBE_CHANNEL", "")
    if not channel:
        return "Не задан канал."
    try:
        cid = resolve_channel(channel)
        d = _get("search", part="snippet", channelId=cid, order="date",
                 type="video", maxResults=n)
        items = d.get("items", [])
        if not items:
            return "Роликов нет."
        ids = ",".join(i["id"]["videoId"] for i in items)
        stats = {v["id"]: v["statistics"] for v in
                 _get("videos", part="statistics", id=ids).get("items", [])}
        out = []
        for i in items:
            vid = i["id"]["videoId"]
            title = _clean(i["snippet"]["title"])
            vc = int(stats.get(vid, {}).get("viewCount", 0))
            out.append(f"{title} — {_qty(vc,'просмотр','просмотра','просмотров')}")
        return "Последние ролики: " + "; ".join(out) + "."
    except Exception as e:
        return f"YouTube не ответил: {e}"


def search_videos(query: str, n: int = 3) -> str:
    if not _key():
        return "Нет ключа YouTube."
    try:
        d = _get("search", part="snippet", q=query, type="video", maxResults=n)
        items = d.get("items", [])
        if not items:
            return f"По запросу «{query}» ничего не нашлось."
        return "Нашёл: " + "; ".join(_clean(i["snippet"]["title"]) for i in items) + "."
    except Exception as e:
        return f"YouTube не ответил: {e}"


# Последняя выдача поиска и сколько из неё уже включили — чтобы «это не то,
# давай следующее» работало без нового поиска. На показе 05.10.2026 по
# расплывчатому описанию нашлось чужое видео, и дальше было некуда идти.
_last = {"query": "", "items": [], "played": -1}


def _play(item) -> str:
    import webbrowser
    webbrowser.open("https://www.youtube.com/watch?v=" + item["id"]["videoId"])
    sn = item["snippet"]
    return f"Включаю: {_clean(sn['title'])} — канал {_clean(sn['channelTitle'])}."


def play_on_youtube(query: str) -> str:
    """Найти и сразу включить самое подходящее видео в браузере."""
    import webbrowser
    if not _key():
        webbrowser.open("https://www.youtube.com/results?search_query=" + query)
        return f"Открыл поиск по запросу {query}."
    try:
        # Пять вариантов, а не один: если хозяин скажет «не то», следующий уже под рукой
        d = _get("search", part="snippet", q=query, type="video", maxResults=5,
                 relevanceLanguage="ru")
        items = d.get("items", [])
        if not items:
            return f"По запросу «{query}» на Ютубе ничего нет."
        _last.update(query=query, items=items, played=0)
        more = f" Если не то — скажи «следующее», в запасе ещё {len(items) - 1}."
        return _play(items[0]) + more
    except Exception:
        webbrowser.open("https://www.youtube.com/results?search_query=" + query)
        return f"Открыл поиск по запросу {query}."


def play_next() -> str:
    """«Это не то, включи следующее» — следующий вариант из той же выдачи."""
    items, i = _last["items"], _last["played"]
    if not items:
        return "Я ещё ничего не искал — скажи, что включить."
    if i + 1 >= len(items):
        return (f"Варианты по запросу «{_last['query']}» закончились. "
                "Скажи по-другому, и поищу заново.")
    _last["played"] = i + 1
    left = len(items) - _last["played"] - 1
    tail = f" Ещё {left} в запасе." if left else " Это последний вариант."
    return _play(items[_last["played"]]) + tail


def search_titles(query: str, n: int = 5) -> str:
    """Названия вариантов, чтобы хозяин выбрал сам, а не угадывать за него."""
    if not _key():
        return "Нет ключа YouTube."
    try:
        d = _get("search", part="snippet", q=query, type="video", maxResults=n,
                 relevanceLanguage="ru")
        items = d.get("items", [])
        if not items:
            return f"По запросу «{query}» ничего не нашлось."
        _last.update(query=query, items=items, played=-1)
        lines = [f"{i}. {_clean(it['snippet']['title'])} — {_clean(it['snippet']['channelTitle'])}"
                 for i, it in enumerate(items, 1)]
        return "Нашёл: " + "; ".join(lines) + ". Скажи номер, и включу."
    except Exception as e:
        return f"YouTube не ответил: {e}"


def play_number(n: int) -> str:
    """«Включи второе» — из показанного списка."""
    items = _last["items"]
    if not items:
        return "Списка нет — сначала поищем."
    if not 1 <= int(n) <= len(items):
        return f"В списке {len(items)} вариантов, назови номер от 1 до {len(items)}."
    _last["played"] = int(n) - 1
    return _play(items[_last["played"]])


def upload_ready() -> bool:
    """Есть ли OAuth для приватных операций (загрузка, ответы на комментарии)."""
    return (Path("D:/ytfactory/client_secret.json").exists()
            or (config.ROOT / "config" / "client_secret.json").exists())


if __name__ == "__main__":
    config.setup_console()
    print("ключ:", "есть" if _key() else "НЕТ")
    print(search_videos("lofi hip hop", 2))
    print(channel_stats("@MrBeast"))
    print(latest_videos("@veritasium", 2))
    print("OAuth для загрузки:", "готов" if upload_ready() else "нет")
