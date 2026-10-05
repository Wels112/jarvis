# -*- coding: utf-8 -*-
"""Найти файл, открыть найденное, прислать на телефон — и не перепутать с видео.

Список файлов настоящий (диски хозяина). Открытие файла и отправка в Telegram
подменены: ничего не открывается и не уходит в сеть, проверяется решение.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config


def main():
    config.setup_console()
    from core import router
    from skills import files as F
    from skills import youtube as YT
    import os

    F.build()
    errors = 0

    # 1. Поиск по словам из имени и папки
    for query, want in (("readme джарвиса", "README.md"), ("install.ps1", "install.ps1"),
                        ("requirements джарвиса", "requirements.txt"),
                        ("презентацию лцт", ".pptx")):
        hits = F.find(query, 3)
        ok = bool(hits) and want.lower() in hits[0][0].lower()
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} «{query}» → {hits[0][1] if hits else 'ничего'}")

    # 2. Голосом: найди → открой второй (открытие подменено)
    opened = []
    real_start = os.startfile
    os.startfile = lambda p: opened.append(p)
    try:
        r = router.handle(router.normalize("найди файл презентацию лцт"), config.CFG)
        print(f"     «найди файл презентацию лцт» → {r.say[:90]}…")
        r = router.handle(router.normalize("открой второй"), config.CFG)
        ok = bool(opened) and opened[-1] == F.last(2)
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} «открой второй» → {r.say} ({opened[-1] if opened else '—'})")

        # 3. Потом искали видео — «открой первое» уже про видео
        YT._last.update(items=[{"id": {"videoId": "x"}, "snippet": {"title": "т", "channelTitle": "к"}}],
                        played=0, at=time.time() + 1)
        import webbrowser
        real_open = webbrowser.open
        webbrowser.open = lambda url: opened.append(url)
        r = router.handle(router.normalize("включи первое"), config.CFG)
        webbrowser.open = real_open
        ok = "watch?v=x" in str(opened[-1])
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} после поиска видео «включи первое» — видео: {r.say[:50]}")
    finally:
        os.startfile = real_start

    # 4. «Пришли на телефон» без подключённого телефона — честный отказ
    from core.brain import Brain
    b = Brain(config.CFG)
    b.phone = None
    F.report("install.ps1")
    said = b._run_tool("send_file", {"number": 1})
    ok = "не подключён" in said
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} без телефона: {said}")

    # 5. С телефоном — уходит sendDocument с нужным файлом (сеть подменена)
    from core.phone import Phone

    class J:
        cfg = config.CFG
    phone = Phone(J())
    phone.token, phone.owner = "тест", 1
    sent = []
    phone._call = lambda method, _wait=20, _files=None, **p: (sent.append((method, list(_files or {}))) or {"ok": 1})
    b.phone = phone
    said = b._run_tool("send_file", {"number": 1})
    ok = sent and sent[-1][0] == "sendDocument" and "Отправил" in said
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} с телефоном: {said} · запрос {sent[-1] if sent else '—'}")

    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
