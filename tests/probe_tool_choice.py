# -*- coding: utf-8 -*-
"""Кто правильнее выбирает инструмент — на живых фразах хозяина.

Хозяин решил, что Джарвис «тупит» из-за бесплатного ключа. Проверяем это
измерением: берём фразы прямо из журнала показа 05.10.2026, где он промахнулся,
и смотрим, какой инструмент вызывает каждая модель. Ответ вслух не нужен — важно
только попадание в инструмент и время.

Ничего на компьютере не выполняется: инструменты объявлены, но вызовы
перехватываются и записываются.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config, net

net.prefer_ipv4()

MODELS = ["gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-3.5-flash",
          "gemini-flash-latest"]

# (фраза, какие инструменты считаем верным выбором)
CASES = [
    ("открой видео Глеб Отис TikTok'с номер 74", {"youtube_play"}),
    ("включи самое первое видео", {"youtube_play"}),
    ("нет, это совсем не то, включи следующее", {"youtube_play"}),
    ("останови видео", {"video", "who_sounds"}),
    ("нет, Джарвис, видео не остановлено, посмотри внимательно",
     {"video", "who_sounds", "look_at_screen"}),
    ("закрой эту вкладку", {"browser"}),
    ("разверни видео на весь экран", {"video"}),
    ("что сейчас играет", {"who_sounds", "look_at_screen"}),
    ("открой ютуб", {"open_site", "open_app"}),
    ("напомни через неделю в 15:30 заказать рамстры", {"add_task"}),
    ("запиши в заметки клиент хочет такого же джарвиса", {"note"}),
    ("открой текстовый документ в блокноте", {"open_app"}),
    ("сделай музыку потише", {"volume"}),
    ("какая погода в Питере", {"weather"}),
]


def ask(model: str, brain, phrase: str):
    payload = {
        "contents": [{"role": "user", "parts": [{"text": phrase}]}],
        "systemInstruction": brain._system_block(),
        "tools": [{"function_declarations": brain.TOOLS_SNAPSHOT}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 300},
    }
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
           f":generateContent?key={brain.key}")
    t0 = time.monotonic()
    r = brain.session.post(url, json=payload, timeout=60)
    took = time.monotonic() - t0
    if r.status_code != 200:
        return None, took, f"{r.status_code} {r.text[:60]}"
    parts = ((r.json().get("candidates") or [{}])[0].get("content", {}).get("parts") or [])
    calls = [p["functionCall"]["name"] for p in parts if "functionCall" in p]
    return calls, took, None


def main():
    config.setup_console()
    from core import brain as B

    br = B.Brain(config.CFG)
    if not br.ready:
        print("нет ключа Gemini — проверять нечего")
        return
    br.TOOLS_SNAPSHOT = B.TOOLS
    br.key = config.env("GEMINI_API_KEY")
    br.session = __import__("requests").Session()

    print(f"инструментов объявлено: {len(B.TOOLS)} · фраз: {len(CASES)}\n")
    for model in MODELS:
        hits, times, wrong, fails = 0, [], [], 0
        for phrase, want in CASES:
            calls, took, err = ask(model, br, phrase)
            if err:
                fails += 1
                if fails == 1:
                    print(f"{model:26} недоступна: {err}")
                break
            times.append(took)
            if calls and set(calls) & want:
                hits += 1
            else:
                wrong.append(f"«{phrase[:28]}» → {calls or 'ответил словами'}")
        if fails:
            continue
        avg = sum(times) / len(times)
        print(f"{model:26} верный инструмент {hits}/{len(CASES)} · "
              f"в среднем {avg:.2f} c (худшее {max(times):.2f})")
        for w in wrong[:4]:
            print(f"{'':26}   мимо: {w}")


if __name__ == "__main__":
    main()
