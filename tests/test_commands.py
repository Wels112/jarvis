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
    ("закрой все окна кроме телеграма", "модель", ""),                  # было: close_app «все окна кроме…»
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

    sandbox.disable()
    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
