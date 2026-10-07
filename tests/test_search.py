# -*- coding: utf-8 -*-
"""Где искать: Яндекс по умолчанию, переключение насовсем и разовый поиск.

Повод — живой разговор 07.10.2026: хозяин попросил «Яндекс активировать», а
Джарвис лишь открыл ya.ru и переспросил, что искать, хотя запрос только что
прозвучал. Браузер и запуск программ подменены — ничего не открывается;
настройки пишутся во временный файл.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config


def main():
    config.setup_console()
    from core import router
    from skills import system as S
    import webbrowser

    opened = []
    real_open, real_file = webbrowser.open, config.CONFIG_FILE
    real_app, real_site = S.open_app, S.open_site
    webbrowser.open = lambda url, *a, **k: opened.append(url)
    S.open_app = lambda *a, **k: "(запуск программы)"
    S.open_site = lambda what: f"(сайт {what})"
    settings = Path("D:/pytmp/test_search_settings.json")
    settings.write_text(json.dumps({"owner": "тест"}), encoding="utf-8")
    config.CONFIG_FILE = settings
    real_engine = config.CFG.get("search_engine")
    config.CFG["search_engine"] = "yandex"
    errors = 0

    def ask(text):
        opened.clear()
        r = router.handle(router.normalize(text), config.CFG)
        return (r.say if r else ""), (opened[-1] if opened else "")

    def check(name, ok, detail=""):
        nonlocal errors
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} {name}{' — ' + detail if detail else ''}")

    try:
        say, url = ask("найди парикмахерскую чип чип в питере")
        check("по умолчанию — Яндекс", url.startswith("https://ya.ru/search/?text=") and "%D0" in url, url[:60])

        say, url = ask("найди в гугле рецепт борща")
        check("«найди в гугле …» — разово в Google", url.startswith("https://www.google.com/search?q="), say)
        check("разовый поиск не меняет выбор", config.CFG["search_engine"] == "yandex")

        say, url = ask("найди это в яндексе")
        check("«найди это в яндексе» — прошлый запрос", "ya.ru" in url and "%D0%B1%D0%BE%D1%80%D1%89" in url, say)

        say, url = ask("ищи через гугл")
        saved = json.loads(settings.read_text(encoding="utf-8"))
        check("«ищи через гугл» — насовсем и в файле", config.CFG["search_engine"] == "google"
              and saved == {"owner": "тест", "search_engine": "google"}, say)
        check("…и повторил запрос в Google", "google.com" in url and "Повторил" in say)

        ask("найди погоду в москве на выходные")
        say, url = ask("ты делаешь через гугл тебе надо яндекс активировать")
        check("«надо яндекс активировать» — Яндекс и повтор", config.CFG["search_engine"] == "yandex"
              and "ya.ru" in url and "Повторил" in say, say)

        say, url = ask("переключи поиск на гугл")
        check("«переключи поиск на гугл»", config.CFG["search_engine"] == "google", say)
        ask("поставь поисковик на яндекс")
        check("«поставь поисковик на яндекс»", config.CFG["search_engine"] == "yandex")

        say, url = ask("открой яндекс")
        check("«открой яндекс» — по-прежнему открыть, не выбор поиска", "Теперь ищу" not in say and "/search" not in url, say)
        say, url = ask("включи яндекс музыку")
        check("«включи яндекс музыку» — не трогает поиск", "Теперь ищу" not in say, say)

        S.search_web("концерт R&B #1")
        check("запрос кодируется для адреса", opened[-1].endswith("R%26B+%231"), opened[-1][-20:])
    finally:
        webbrowser.open, config.CONFIG_FILE = real_open, real_file
        S.open_app, S.open_site = real_app, real_site
        config.CFG["search_engine"] = real_engine
        settings.unlink(missing_ok=True)

    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
