# -*- coding: utf-8 -*-
"""Планировщик недели: хранение, сервер окна, голос Джарвиса.

Данные — в тестовой папке (data/brain/test/planner.json), сервер — на своём
порту; окно не открывается (open_window подменён). Само окно (перетаскивание
мышью) проверялось в браузере 10.10.2026 — здесь всё, что под ним.
"""
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import config, memory, router

PORT = 8799


def req(method, url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"http://127.0.0.1:{PORT}{url}", data=data, method=method,
                               headers={"Content-Type": "application/json", **(headers or {})})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(r, timeout=5) as resp:
            return resp.status, json.loads(resp.read() or b"{}") if "json" in resp.headers.get("Content-Type", "") else resp.read()
    except urllib.error.HTTPError as e:
        return e.code, None


def main():
    config.setup_console()
    from skills import planner as P
    errors = 0

    def check(name, ok, detail=""):
        nonlocal errors
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} {name}{' — ' + str(detail)[:110] if detail else ''}")

    P.path().unlink(missing_ok=True)
    check("пустой план — пять категорий по умолчанию", len(P.load()["categories"]) == 5 and not P.load()["events"])

    ev = P.add({"day": 2, "start": "18:00", "end": "17:00", "title": "  Урок с Петей ", "cat": "tutor"})
    check("конец раньше начала — минимум 15 минут, название без пробелов",
          ev["end"] == "18:15" and ev["title"] == "Урок с Петей", ev)
    try:
        P.add({"day": 9, "start": "10:00", "end": "11:00"})
        check("день 9 не принимается", False)
    except ValueError:
        check("день 9 не принимается", True)
    moved = P.update(ev["id"], {"day": 4, "start": "16:00", "end": "17:30"})
    check("перенос: пятница 16:00–17:30", moved["day"] == 4 and moved["start"] == "16:00" and moved["end"] == "17:30")
    P.set_categories([{"id": "study", "name": "Учёба", "color": "#3f62c4"}, {"name": "Х", "color": "red"}])
    after = P.load()
    check("удалили категорию — событие без категории; кривой цвет заменён",
          after["events"][0]["cat"] == "" and after["categories"][1]["color"] == "#6e747a")

    # Голосом
    for text, want in (("в среду и пятницу с 18 до 19:30 английский с Петей", ([2, 4], "18:00", "19:30", "Английский с Петей")),
                       ("каждый день в 7 на полчаса зарядка", (list(range(7)), "07:00", "07:30", "Зарядка")),
                       ("по будням с 9:30 до 11 пары", ([0, 1, 2, 3, 4], "09:30", "11:00", "Пары")),
                       ("во вторник в 20 на два часа лаба по java", ([1], "20:00", "22:00", "Лаба по java")),
                       ("когда-нибудь почитать", None)):
        got = P.parse_slot(text)
        ok = got == want
        check(f"«{text}»", ok, got)

    P.path().unlink(missing_ok=True)
    said = router.handle(router.normalize("добавь в планировщик в среду и пятницу с 18 до 19:30 английский"),
                         config.CFG).say
    evs = P.load()["events"]
    check("голосом: «добавь в планировщик …» — два события", len(evs) == 2 and said.startswith("Добавил"), said)
    said = router.handle(router.normalize("что у меня по плану в среду"), config.CFG).say
    check("«что у меня по плану в среду»", "18:00–19:30 Английский" in said, said)

    wed = datetime(2026, 10, 7, 18, 20)                    # среда, идёт английский
    check("«что сейчас по плану» в среду 18:20", P.now_and_next(wed).startswith("Сейчас по плану Английский, до 19:30"),
          P.now_and_next(wed))
    check("в среду вечером — следующее в пятницу", "в пятницу в 18:00" in P.now_and_next(datetime(2026, 10, 7, 21, 0)),
          P.now_and_next(datetime(2026, 10, 7, 21, 0)))

    P.update(evs[0]["id"], {"remind": True})
    told = set()
    first = P.due_reminders(datetime(2026, 10, 7, 17, 52), told=told)
    again = P.due_reminders(datetime(2026, 10, 7, 17, 55), told=told)
    check("напоминание за 10 минут — один раз", len(first) == 1 and first[0][1] == 8 and not again)

    real_tasks = memory.TASKS
    memory.TASKS = memory.STORE / "tasks_planner_test.json"
    try:
        memory._save(memory.TASKS, [])
        from datetime import date
        friday = date(2026, 10, 9)
        items = P.day_items(friday)
        check("день из планировщика для «что у меня в планах»", items and items[0][1] == "Английский", items)
    finally:
        memory.TASKS.unlink(missing_ok=True)
        memory.TASKS = real_tasks

    # Сервер окна
    opened = []
    P.open_window = lambda port=P.PORT: opened.append(port) or "Открываю планировщик."
    httpd = P.serve(PORT)
    try:
        code, page = req("GET", "/")
        check("окно отдаётся", code == 200 and b"<title>" in page)
        code, plan = req("GET", "/api/plan")
        v0 = plan["version"]
        code, made = req("POST", "/api/events", {"day": 0, "start": "10:00", "end": "11:00", "title": "Тест"})
        new_id = made["result"]["id"]
        code2, patched = req("PATCH", f"/api/events/{new_id}", {"start": "12:00", "end": "13:00"})
        code3, _ = req("DELETE", f"/api/events/{new_id}")
        code4, _ = req("DELETE", f"/api/events/{new_id}")
        check("создать, перенести, удалить; повторное удаление — 404",
              code == 200 and patched["result"]["start"] == "12:00" and code3 == 200 and code4 == 404
              and req("GET", "/api/version")[1]["version"] > v0)
        code, _ = req("GET", "/api/plan", headers={"Host": "evil.example"})
        check("чужой Host (подмена DNS) — 403", code == 403)
        code, _ = req("POST", "/api/events", {"day": 0, "start": "10:00", "end": "11:00"},
                      headers={"Origin": "https://evil.example"})
        check("запись с чужой страницы (Origin) — 403", code == 403)
        check("сервер узнаётся как планировщик", P.running(PORT))
        cfg = dict(config.CFG, planner={"port": PORT})
        said = router.handle(router.normalize("открой планировщик"), cfg).say
        check("«открой планировщик» — окно на порту сервера", opened == [PORT] and said == "Открываю планировщик.")
    finally:
        httpd.shutdown()
        P.path().unlink(missing_ok=True)

    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
