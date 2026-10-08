# -*- coding: utf-8 -*-
"""Обычные просьбы — делом, а не «не могу»: что открыть, куда, каким способом.

Хозяин 08.10.2026: «попросил включить YouTube — включает; открыть Telegram и
написать — делает; так со всеми приложениями». Прогон tests/probe_capabilities.py
в ту ночь нашёл здесь ошибки — каждая закреплена ниже. Действия в песочнице:
проверяется, какое умение и с каким аргументом вызвано, а не открывается.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import config, memory, router

# фраза → [(умение, аргумент или None — не проверять)]
CASES = [
    ("открой ютуб", [("system.open_site", "ютуб")]),
    ("открой вконтакте", [("system.open_site", "вконтакте")]),
    ("открой госуслуги", [("system.open_site", "госуслуги")]),
    ("открой сайт хабра", [("system.open_site", "хабр")]),
    ("открой сайт мосэнерго", [("system.search_web", "мосэнерго официальный сайт")]),
    ("открой стим", [("system.open_app", "стим")]),
    ("запусти доту", [("system.open_app", "доту")]),
    ("открой блокнот и калькулятор", [("system.open_app", "блокнот"), ("system.open_app", "калькулятор")]),
    ("открой последний скачанный файл", [("files.latest_download", None)]),
    ("закрой хром", [("system.close_app", "хром")]),
    # было: вторая половина уходила в запрос YouTube
    ("включи на ютубе музыку для работы и сделай погромче",
     [("youtube.play_on_youtube", "музыку для работы"), ("system.change_volume", None)]),
    ("сверни все окна и включи музыку на ютубе",
     [("desktop.minimize_all", None), ("youtube.play_on_youtube", "музыку")]),
    ("включи видео just dance на ютубе", [("youtube.play_on_youtube", "just dance")]),
    ("включи видео на ютубе just dance", [("youtube.play_on_youtube", "just dance")]),
]

# фраза → (что ждём: «да», модель или ответ правила с такой подстрокой)
OUTCOMES = [
    ("выключи компьютер через час", "да", "через 60 минут"),           # было: close_app «компьютер через час»
    ("выключи комп через 30 минут", "да", "через 30 минут"),
    ("заверши работу", "да", "Выключить компьютер"),                    # было: close_app «работу»
    ("закрой окна кроме вот этих двух", "модель", ""),                  # было: close_app «окна кроме…»
    ("что ты обо мне помнишь", "ответ", ""),
    ("сколько заряда", "ответ", ""),
    ("погода завтра", "ответ", ""),
]


def main():
    config.setup_console()
    from tests import sandbox
    acted = sandbox.enable()
    from skills import weather as W, system as S
    W.weather = lambda city="", day=0: f"погода {city or 'дома'} на день {day}"
    S.battery = lambda: "Заряд 80 процентов."
    tmp = Path(tempfile.mkdtemp())
    memory.TASKS, memory.FACTS = tmp / "t.json", tmp / "f.json"
    memory.remember("мой любимый цвет синий")
    errors = 0

    for phrase, want in CASES:
        acted.clear()
        r = router.handle(router.normalize(phrase), config.CFG)
        got = [(name, args[0] if args else None) for name, args in acted]
        ok = len(got) == len(want) and all(g[0] == w[0] and (w[1] is None or g[1] == w[1])
                                           for g, w in zip(got, want))
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} «{phrase}» → {got if got else ('МОДЕЛИ' if r.to_llm else r.say[:60])}")

    for phrase, kind, part in OUTCOMES:
        acted.clear()
        r = router.handle(router.normalize(phrase), config.CFG)
        if kind == "да":
            ok = bool(r.pending) and part in r.say and not acted
        elif kind == "модель":
            ok = r.to_llm and not acted
        else:
            ok = not r.to_llm and bool(r.say) and part in r.say
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} «{phrase}» → {'МОДЕЛИ' if r.to_llm else r.say[:70]}")

    # «Какие новости» — настоящие заголовки, а не поиск, пересказанный наугад
    from skills import news
    news.headlines = lambda n=5, topic="": f"заголовки {topic}".strip()
    for phrase, want in (("Какие ещё новости", "заголовки"), ("новости про биткоин", "заголовки биткоин"),
                         ("что нового в мире", "заголовки")):
        r = router.handle(router.normalize(phrase), config.CFG)
        ok = r.say == want
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} «{phrase}» → {'МОДЕЛИ' if r.to_llm else r.say}")

    # «погода завтра в казани» — день и город
    r = router.handle(router.normalize("какая завтра погода в казани"), config.CFG)
    ok = r.say == "погода казани на день 1"
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} «какая завтра погода в казани» → {r.say}")

    # Несколько команд: часть не по силам правилам — остаток целиком модели
    acted.clear()
    r = router.handle(router.normalize("сверни все окна и расскажи анекдот"), config.CFG)
    ok = not r.to_llm and acted == [("desktop.minimize_all", ())]
    r2 = router.handle(router.normalize("сверни все окна и найди мне анекдот про программистов"), config.CFG)
    ok = ok or (r2.to_llm and "анекдот" in r2.meta.get("llm_text", ""))
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} несколько команд: правилам — своё, модели — остаток")

    # Разговорные формы (tests/probe_casual.py): «можешь открыть», «-ка», «пожалуйста»
    for phrase, want in (("можешь открыть ютуб", ("system.open_site", "ютуб")),
                         ("ты можешь открыть телеграм", ("system.open_app", "телеграм")),
                         ("а открой-ка стим", ("system.open_app", "стим")),
                         ("запусти мне хром пожалуйста", ("system.open_app", "хром")),
                         ("мне нужно открыть госуслуги", ("system.open_site", "госуслуги")),
                         ("хочу посмотреть ютуб", ("system.open_site", "ютуб")),
                         ("будь добр открой загрузки", ("system.open_app", "загрузки")),
                         ("зайди в телегу", ("system.open_app", "телегу")),
                         ("можешь сделать потише", ("system.change_volume", -10)),
                         ("убавь звук", ("system.change_volume", -10)),
                         ("поставь музыку", ("system.media_key", "play"))):
        acted.clear()
        router.handle(router.normalize(phrase), config.CFG)
        got = [(n, a[0] if a else None) for n, a in acted]
        ok = got == [want]
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} «{phrase}» → {got}")
    for phrase, part in (("можешь напомнить мне завтра в 10 позвонить маме", "Записал: позвонить маме"),
                         ("напомни пожалуйста через час выпить таблетку", "Записал: выпить таблетку"),
                         ("засеки 5 минут", "Таймер на 5 минут"),
                         ("сколько сейчас времени", "Сейчас"),
                         ("найди мне файл резюме", "")):
        r = router.handle(router.normalize(phrase), config.CFG)
        ok = not r.to_llm and part in r.say and not r.say.startswith("[песочница] system.search_web")
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} «{phrase}» → {'МОДЕЛИ' if r.to_llm else r.say[:60]}")

    # Папки, проекты и документы по имени — не программа «папку jarvis»
    from skills import files as F
    F.find_folders = lambda q, limit=5: [r"D:\jarvis"] if "jarvis" in q or "джарвис" in q else []
    F.find = lambda q, limit=5: [("резюме.pdf", r"C:\docs\резюме.pdf", 0.0)] if "резюме" in q else []
    opened = []
    real_popen = F.__dict__.get("subprocess")
    import subprocess as SP
    popen = SP.Popen
    SP.Popen = lambda args, *a, **k: opened.append(args)
    try:
        for phrase, want in (("открой папку jarvis", "Открываю папку D:\\jarvis."),
                             ("открой проект джарвис в vs code", "Открываю D:\\jarvis в VS Code."),
                             ("открой документ резюме", "[песочница] files.open_safely"),
                             ("открой папку несуществующую", "Папку «несуществующую» не нашёл.")):
            acted.clear()
            r = router.handle(router.normalize(phrase), config.CFG)
            ok = r.say.startswith(want) and not [a for a in acted if a[0] == "system.open_app"]
            errors += not ok
            print(f"{'ok ' if ok else 'НЕТ'} «{phrase}» → {r.say[:70]}")
    finally:
        SP.Popen = popen

    # «Закрой все окна кроме телеграма» — как крестиком и после «да», а не Stop-Process
    from skills import desktop as Dk
    posted = []
    real_lw, real_post = Dk.list_windows, Dk.win32gui.PostMessage
    Dk.list_windows = lambda limit=12: [(1, "Jarvis", "cmd.exe"), (2, "Хомяк Туп @ Wels", "Telegram.exe"),
                                        (3, "Habr — Яндекс Браузер", "browser.exe"), (4, "main.py - VS Code", "Code.exe")]
    Dk.win32gui.PostMessage = lambda hwnd, msg, a, b: posted.append(hwnd)
    try:
        r = router.handle(router.normalize("закрой все окна кроме телеграма"), config.CFG)
        asked = r.pending and "Закрыть 2 окна: VS Code, Яндекс Браузер; оставить Telegram" in r.say and not posted
        done = r.pending() if r.pending else ""
        ok = asked and posted == [3, 4] and done.startswith("Закрыл 2 окон")
    finally:
        Dk.list_windows, Dk.win32gui.PostMessage = real_lw, real_post
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} «закрой все окна кроме телеграма» → «{r.say}» → закрыты {posted}")

    # «Сделай скриншот и пришли на телефон» — снимок уходит через бота
    import core.phone as phone_module
    shot = tmp / "jarvis_test.png"
    S.screenshot = lambda: (shot.write_bytes(b"png"), str(shot))[1]

    class FakePhone:
        owner, sent = 1, []

        def send_file(self, path):
            self.sent.append(path)
            return f"Отправил {Path(path).name} тебе в Telegram."
    phone_module.CURRENT = fp = FakePhone()
    try:
        r = router.handle(router.normalize("сделай скриншот и пришли на телефон"), config.CFG)
    finally:
        phone_module.CURRENT = None
    ok = fp.sent == [str(shot)] and "Отправил jarvis_test.png" in r.say
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} «сделай скриншот и пришли на телефон» → «{r.say}»")

    # Живой разговор идёт мимо правил — те же умения через инструмент jarvis_command
    from core.live import run_jarvis_command, LIVE_TOOLS

    class FakeBrain:
        pending_confirm = None
    b = FakeBrain()
    acted.clear()
    said = run_jarvis_command(b, "Открой загрузки")
    ok1 = acted and acted[0][0] == "system.open_app" and "[песочница]" in said
    said2 = run_jarvis_command(b, "выключи компьютер через час")
    ok2 = said2.startswith("ТРЕБУЕТСЯ ПОДТВЕРЖДЕНИЕ") and b.pending_confirm and "через 60 минут" in said2
    said3 = run_jarvis_command(FakeBrain(), "кто такой илон маск")
    ok3 = said3.startswith("Правилами это не делается")
    ok = ok1 and ok2 and ok3 and {"jarvis_command", "news"} <= {t["name"] for t in LIVE_TOOLS}
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} живой разговор: команда правилами, опасное — через «да», "
          f"непосильное — обратно модели")

    sandbox.disable()
    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
