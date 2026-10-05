# -*- coding: utf-8 -*-
"""Учебник для своей модели: Gemini — учитель, Qwen3.5-2B — ученица.

Живых примеров мало (журналы чистятся), поэтому набор собирается так:

1. Фразы. Под каждый из 55 инструментов Gemini придумывает по 25 реплик, какими
   живой человек просит голосового помощника, — разговорных, коротких, иногда с
   ошибками распознавания речи. Плюс болтовня без инструментов и просьбы, для
   которых инструмента нет.

2. Ответы. Каждую фразу Gemini отрабатывает с НАСТОЯЩИМИ инструментами и тем же
   характером, что у Джарвиса. Что он вызвал — то и правильный ответ для
   ученицы. Фразы, где он выбрал не тот инструмент, под который их придумывали,
   выбрасываются как двусмысленные: учить на спорном — учить путанице.

3. Честность. Часть вызовов получает выдуманный результат инструмента, в том
   числе ошибку, и Gemini отвечает на него вслух. Так ученица учится говорить
   «не получилось», а не «готово» — главная болезнь, найденная на замере.

4. Проверочная часть. Фразы с показа и десятая часть сгенерированных в учёбу не
   попадают: на них потом сравниваются исходная и дообученная модели.

Всё дописывается в train/data/*.jsonl по строке, так что прерванный сбор
продолжается с места остановки. Лимит бесплатного ключа обходится паузами.
"""
import json
import random
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config, net

net.prefer_ipv4()
OUT = Path(__file__).resolve().parent / "data"
MODELS = ["gemini-3.5-flash-lite", "gemini-flash-lite-latest"]
PER_TOOL = 25
API = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"

session = requests.Session()


def gemini(payload: dict, tries: int = 8) -> dict:
    """Запрос к учителю с паузами на лимит: бесплатный ключ отвечает 429 часто."""
    key = config.env("GEMINI_API_KEY")
    wait = 15
    for attempt in range(tries):
        for model in MODELS:
            try:
                r = session.post(API.format(m=model), params={"key": key}, json=payload, timeout=90)
            except requests.RequestException:
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code not in (429, 500, 503):
                raise RuntimeError(f"{r.status_code}: {r.text[:200]}")
        time.sleep(wait)
        wait = min(wait * 2, 120)
    raise RuntimeError("учитель не отвечает — лимит не отпускает")


def text_of(resp: dict) -> str:
    parts = ((resp.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts)


def calls_of(resp: dict):
    parts = ((resp.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    return [p["functionCall"] for p in parts if "functionCall" in p]


def load_jsonl(path: Path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append(path: Path, row: dict):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---------- 1. фразы ----------
PHRASE_PROMPT = """Ты помогаешь собрать примеры для обучения русского голосового помощника.
Помощник умеет вызывать инструмент:

{name}: {description}
Параметры: {params}

Напиши {n} разных реплик, которыми живой человек попросил бы об этом помощника ГОЛОСОМ.
Требования:
- По-русски, разговорно, как говорят вслух: коротко, иногда с «ну», «слушай», «давай».
- Разные формулировки и разные значения параметров (названия, числа, имена, время).
- Примерно каждая пятая — с ошибкой распознавания речи (слово искажено на слух).
- Без обращения по имени в начале. Без нумерации и кавычек.
Ответ — только JSON-массив строк."""

EXTRA = {
    "chat": ("Напиши {n} разных реплик голосовому помощнику, где НЕ нужно ничего делать на "
             "компьютере: вопросы на знание, просьба объяснить, пошутить, поболтать, совет. "
             "Разговорно, по-русски. Ответ — только JSON-массив строк."),
    "impossible": ("Напиши {n} разных просьб к голосовому помощнику на компьютере, которые он "
                   "НЕ может выполнить: заказать пиццу, вызвать такси, позвонить по телефону, "
                   "перевести деньги, починить машину, сходить в магазин и тому подобное. "
                   "Разговорно, по-русски. Ответ — только JSON-массив строк."),
}


def make_phrases(tools):
    path = OUT / "phrases.jsonl"
    done = {row["intent"] for row in load_jsonl(path)}
    jobs = [(t["name"], PHRASE_PROMPT.format(
        name=t["name"], description=t.get("description", ""),
        params=json.dumps(t.get("parameters", {}).get("properties", {}), ensure_ascii=False),
        n=PER_TOOL)) for t in tools]
    jobs += [(k, v.format(n=60 if k == "chat" else 40)) for k, v in EXTRA.items()]
    for intent, prompt in jobs:
        if intent in done:
            continue
        resp = gemini({"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": 1.0, "maxOutputTokens": 4000,
                                            "responseMimeType": "application/json"}})
        try:
            phrases = [p.strip() for p in json.loads(text_of(resp)) if isinstance(p, str) and p.strip()]
        except json.JSONDecodeError:
            print(f"  {intent}: учитель ответил не JSON, пропускаю")
            continue
        for p in dict.fromkeys(phrases):          # без повторов, порядок сохраняем
            append(path, {"intent": intent, "text": p})
        print(f"  {intent:24} {len(phrases)} фраз")


# ---------- 2. ответы учителя ----------
def label(system: str, tools, phrases_done: set):
    """Учитель отрабатывает каждую фразу с настоящими инструментами."""
    src = load_jsonl(OUT / "phrases.jsonl")
    path = OUT / "labeled.jsonl"
    done = {row["text"] for row in load_jsonl(path)} | phrases_done
    todo = [row for row in src if row["text"] not in done]
    print(f"разметить: {len(todo)} фраз")
    for i, row in enumerate(todo, 1):
        resp = gemini({"contents": [{"role": "user", "parts": [{"text": row["text"]}]}],
                       "systemInstruction": {"parts": [{"text": system}]},
                       "tools": [{"function_declarations": tools}],
                       "generationConfig": {"temperature": 0, "maxOutputTokens": 300}})
        calls = [{"name": c.get("name"), "args": c.get("args") or {}} for c in calls_of(resp)]
        append(path, {**row, "calls": calls, "answer": text_of(resp).strip()})
        if i % 50 == 0:
            print(f"  размечено {i}/{len(todo)}")
        time.sleep(0.5)


BATCH_PROMPT = """{system}

Тебе доступны инструменты (имя, назначение, параметры):
{tools}

Ниже реплики хозяина, каждая — отдельный разговор. Для КАЖДОЙ реши, что ты сделаешь:
вызовешь инструмент (имя и аргументы строго по его параметрам) или ответишь словами.
Реплики:
{numbered}

Ответ — JSON-массив той же длины, по порядку:
[{{"i": 1, "tool": "имя_инструмента или null", "args": {{...}}, "answer": "если без инструмента — что скажешь вслух, иначе пусто"}}]"""


def label_batch(system: str, tools, size: int = 25):
    """Разметка пачками: на бесплатном ключе по одной фразе выходит часами.

    Пачка из 25 реплик — один запрос вместо двадцати пяти. Учитель видит тот же
    характер и те же инструменты; спорные ответы потом отсеивает фильтр
    согласия с намерением, как и при поштучной разметке.
    """
    src = load_jsonl(OUT / "phrases.jsonl")
    path = OUT / "labeled.jsonl"
    done = {row["text"] for row in load_jsonl(path)}
    todo = [row for row in src if row["text"] not in done]
    brief = "\n".join(f"- {t['name']}: {t.get('description', '')[:160]} | параметры: "
                      f"{', '.join(t.get('parameters', {}).get('properties', {}))}" for t in tools)
    names = {t["name"] for t in tools}
    print(f"разметить пачками: {len(todo)} фраз")
    for start in range(0, len(todo), size):
        chunk = todo[start:start + size]
        numbered = "\n".join(f"{i}. {row['text']}" for i, row in enumerate(chunk, 1))
        try:
            resp = gemini({"contents": [{"role": "user", "parts": [{"text": BATCH_PROMPT.format(
                system=system, tools=brief, numbered=numbered)}]}],
                "generationConfig": {"temperature": 0, "maxOutputTokens": 6000,
                                     "responseMimeType": "application/json"}})
            answers = json.loads(text_of(resp))
        except (RuntimeError, json.JSONDecodeError) as e:
            print(f"  пачка {start // size + 1}: {str(e)[:80]} — пропускаю")
            continue
        by_i = {a.get("i"): a for a in answers if isinstance(a, dict)}
        for i, row in enumerate(chunk, 1):
            a = by_i.get(i)
            if not a:
                continue
            tool = a.get("tool")
            calls = ([{"name": tool, "args": a.get("args") or {}}]
                     if tool and tool in names else [])
            append(path, {**row, "calls": calls, "answer": (a.get("answer") or "").strip(),
                          "how": "пачка"})
        print(f"  размечено {min(start + size, len(todo))}/{len(todo)}")


# ---------- 3. честный ответ на результат инструмента ----------
FAKE_OK = {
    "open_app": "Открываю {x}.", "close_app": "Закрыл {x}.", "youtube_play": "Включаю: {x}.",
    "video": "Поставил на паузу.", "volume": "Громкость 30 процентов.", "weather": "В городе +12, облачно.",
    "add_task": "Записал: {x}. Напомню 12.10 в 15:30.", "note": "Записал в заметки.",
}
FAKE_FAIL = [
    "Не нашёл программу «{x}» среди установленных.",
    "Нажал — но звук идёт дальше. Похоже, на странице нет плеера.",
    "Браузер не запущен — видео в нём я не вижу.",
    "ошибка инструмента: нет доступа к сети",
    "Не смог открыть: файл не найден.",
]


HONESTY_PROMPT = """{system}

Ниже разговоры. В каждом хозяин о чём-то попросил, ты вызвал инструмент, и инструмент
вернул результат. Скажи хозяину вслух, что вышло: одной-двумя короткими фразами, живой
речью, без списков и разметки. Если результат — отказ или ошибка, честно скажи, что
не получилось и почему. Никогда не говори «готово», если инструмент этого не подтвердил.

{numbered}

Ответ — JSON-массив той же длины: [{{"i": 1, "answer": "что скажешь вслух"}}]"""


def honesty(system: str, tools, size: int = 25):
    """Как отвечать вслух на результат инструмента — особенно на неудачный.

    Первая версия подставляла вызов инструмента в историю разговора, и Gemini
    отказал: новым моделям нужна подпись к каждому такому вызову, а подделать
    её нельзя. Поэтому разговор описывается учителю словами, пачкой.
    """
    rows = [r for r in load_jsonl(OUT / "labeled.jsonl") if r["calls"]]
    path = OUT / "honesty.jsonl"
    done = {r["text"] for r in load_jsonl(path)}
    random.seed(7)
    pick = [r for r in random.sample(rows, min(300, len(rows))) if r["text"] not in done]
    print(f"примеров с результатом инструмента: {len(pick)}")
    for start in range(0, len(pick), size):
        chunk = []
        for r in pick[start:start + size]:
            call = r["calls"][0]
            x = next(iter(call["args"].values()), "") if call["args"] else ""
            failed = random.random() < 0.35
            result = (random.choice(FAKE_FAIL) if failed else
                      FAKE_OK.get(call["name"], "Готово.")).format(x=x)
            chunk.append((r, call, result, failed))
        numbered = "\n\n".join(
            f"{i}. Хозяин: «{r['text']}»\n   Ты вызвал: {call['name']} "
            f"{json.dumps(call['args'], ensure_ascii=False)}\n   Инструмент вернул: «{result}»"
            for i, (r, call, result, _) in enumerate(chunk, 1))
        try:
            resp = gemini({"contents": [{"role": "user", "parts": [{"text": HONESTY_PROMPT.format(
                system=system, numbered=numbered)}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 6000,
                                     "responseMimeType": "application/json"}})
            answers = {a.get("i"): (a.get("answer") or "").strip()
                       for a in json.loads(text_of(resp)) if isinstance(a, dict)}
        except (RuntimeError, json.JSONDecodeError) as e:
            print(f"  пачка {start // size + 1}: {str(e)[:80]} — пропускаю")
            continue
        for i, (r, call, result, failed) in enumerate(chunk, 1):
            if answers.get(i):
                append(path, {"text": r["text"], "call": call, "result": result,
                              "failed": failed, "answer": answers[i]})
        print(f"  ответов {min(start + size, len(pick))}/{len(pick)}")


# ---------- 4. сборка учебника ----------
def build():
    """Отбор и раскладка на учебную и проверочную части в формате чата."""
    from tests.probe_tool_choice import CASES
    held_out = {p.lower() for p, _ in CASES}
    rows = load_jsonl(OUT / "labeled.jsonl")
    random.seed(13)
    train, test, dropped = [], [], 0
    for r in rows:
        if r["text"].lower() in held_out:
            continue
        intent = r["intent"]
        names = [c["name"] for c in r["calls"]]
        if intent == "chat" and names:            # болтовня с вызовом — спорно
            dropped += 1
            continue
        if intent == "impossible" and names:
            dropped += 1
            continue
        if intent not in ("chat", "impossible") and intent not in names:
            dropped += 1                          # учитель выбрал другое — фраза двусмысленна
            continue
        if not names and not r["answer"]:
            dropped += 1
            continue
        if names:
            msgs = [{"role": "user", "content": r["text"]},
                    {"role": "assistant", "content": "", "tool_calls": [
                        {"type": "function", "function": {"name": c["name"], "arguments": c["args"]}}
                        for c in r["calls"]]}]
        else:
            msgs = [{"role": "user", "content": r["text"]},
                    {"role": "assistant", "content": r["answer"]}]
        item = {"messages": msgs, "intent": intent}
        (test if random.random() < 0.1 else train).append(item)

    for h in load_jsonl(OUT / "honesty.jsonl"):
        if h["text"].lower() in held_out:
            continue
        train.append({"intent": "honesty", "messages": [
            {"role": "user", "content": h["text"]},
            {"role": "assistant", "content": "", "tool_calls": [
                {"type": "function", "function": {"name": h["call"]["name"],
                                                  "arguments": h["call"]["args"]}}]},
            {"role": "tool", "content": h["result"]},
            {"role": "assistant", "content": h["answer"]}]})

    random.shuffle(train)
    for name, items in (("train", train), ("test", test)):
        (OUT / f"{name}.jsonl").write_text(
            "\n".join(json.dumps(i, ensure_ascii=False) for i in items) + "\n", encoding="utf-8")
    kinds = {}
    for i in train:
        kinds[i["intent"]] = kinds.get(i["intent"], 0) + 1
    print(f"учебных примеров: {len(train)} · проверочных: {len(test)} · отброшено спорных: {dropped}")
    print(f"из них болтовни {kinds.get('chat', 0)}, невыполнимого {kinds.get('impossible', 0)}, "
          f"честных ответов на результат {kinds.get('honesty', 0)}")


def main():
    config.setup_console()
    OUT.mkdir(parents=True, exist_ok=True)
    from core.brain import TOOLS, PERSONA
    from core.local_brain import LOCAL_HINTS
    system = PERSONA + LOCAL_HINTS
    (OUT / "system.txt").write_text(system, encoding="utf-8")
    (OUT / "tools.json").write_text(json.dumps(TOOLS, ensure_ascii=False, indent=1), encoding="utf-8")

    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    if step in ("phrases", "all"):
        print("== 1. фразы")
        make_phrases(TOOLS)
    if step in ("label", "all"):
        print("== 2. ответы учителя")
        label_batch(system, TOOLS)
    if step in ("honesty", "all"):
        print("== 3. честные ответы на результат")
        honesty(system, TOOLS)
    if step in ("build", "all"):
        print("== 4. сборка")
        build()


if __name__ == "__main__":
    main()
