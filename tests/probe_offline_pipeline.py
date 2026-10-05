# -*- coding: utf-8 -*-
"""Офлайн целиком: правила роутера, потом своя модель — как будет без интернета.

Отдельный замер мозга (probe_local_brain.py) строже жизни: часть фраз до мозга
не доходит, их раньше ловят правила. Здесь путь настоящий — тот самый
HybridBrain из core/local_brain.py в режиме «только своя модель».

Ничего не выполняется по-настоящему: функции навыков и инструменты подменены
заглушками, которые только записывают вызов. Громкость, вкладки, задачи и
заметки хозяина не трогаются.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

CALLED = []


def stub_everything():
    """Заглушить всё, что меняет мир: навыки, память, инструменты."""
    import inspect
    from skills import system, desktop, youtube, weather, cleanup
    from core import memory

    for mod in (system, desktop, youtube, weather, cleanup):
        for name, fn in list(vars(mod).items()):
            if inspect.isfunction(fn) and not name.startswith("_") and fn.__module__ == mod.__name__:
                setattr(mod, name, (lambda n: lambda *a, **k: (CALLED.append(n), f"[сделано: {n}]")[1])(
                    f"{mod.__name__.split('.')[-1]}.{name}"))
    for name in ("add_task", "add_note", "remember", "add_timer", "forget"):
        setattr(memory, name, (lambda n: lambda *a, **k: (CALLED.append(n), f"[сделано: {n}]")[1])(
            f"memory.{name}"))


def main():
    config.setup_console()
    stub_everything()
    from core import router
    from core.brain import Brain
    from core.local_brain import HybridBrain
    from tests.probe_tool_choice import CASES

    cfg = dict(config.CFG)
    cfg["brain"] = dict(cfg.get("brain", {}), mode="local")
    cloud = Brain(cfg)
    tools_used = []
    cloud._run_tool = lambda name, args: (tools_used.append(name), f"[выполнено: {name}]")[1]
    brain = HybridBrain(cloud, cfg)

    t0 = time.monotonic()
    ok_start = brain.local.ensure_running()
    print(f"своя модель поднялась: {ok_start} за {time.monotonic() - t0:.1f} c "
          f"(в первый раз было 66 c — проверяем кэш шейдеров)")
    t0 = time.monotonic()
    brain.ask("который час")
    print(f"первый запрос (разбор инструментов): {time.monotonic() - t0:.1f} c\n")

    # Что считается верным, если фразу поймали правила: какая функция навыка
    # отвечает каждому инструменту. Правило, вызвавшее не то, — промах, а не успех
    # (первая версия замера засчитывала любое срабатывание, и «закрой вкладку»,
    # ушедшее закрывать программу, сошло за попадание)
    RULE_OK = {
        "youtube_play": {"youtube.play_on_youtube", "youtube.play_next", "youtube.play_number"},
        "youtube_search": {"youtube.search_titles"},
        "video": {"desktop.video"}, "who_sounds": {"system.who_sounds"},
        "browser": {"desktop.browser"}, "open_site": {"system.open_site"},
        "open_app": {"system.open_app"}, "add_task": {"memory.add_task"},
        "note": {"memory.add_note"}, "weather": {"weather.weather", "weather.forecast"},
        "volume": {"system.change_volume", "system.set_volume", "system.mute"},
        "look_at_screen": set(), "list_tasks": {"memory.list_tasks"},
        "system_status": {"system.system_info", "cleanup.disk_report"},
        "find_file": {"system.find_file"}, "focus_window": {"desktop.focus_window"},
    }
    # Фразы с хвоста: правилами не ловятся — тут своя модель и работает
    LONG_TAIL = [
        ("найди на ютубе что-нибудь про чёрные дыры", {"youtube_play", "youtube_search"}),
        ("переключись на окно телеграма", {"focus_window"}),
        ("найди у меня файл с отчётом за сентябрь", {"find_file"}),
        ("сколько свободного места на компе", {"system_status"}),
        ("поставь видео на паузу, я отойду", {"video"}),
        ("напомни завтра утром позвонить в банк", {"add_task"}),
    ]

    by_rules = by_model = asked_model = 0
    for phrase, want in list(CASES) + LONG_TAIL:
        CALLED.clear()
        tools_used.clear()
        reply = router.handle(router.normalize(phrase), cfg)
        if not reply.to_llm:
            good = set().union(*(RULE_OK.get(w, set()) for w in want))
            ok = bool(set(CALLED) & good)
            by_rules += ok
            print(f"{'ok ' if ok else 'мимо'} правила  «{phrase[:40]:40}» → {CALLED or reply.say[:40]}")
            continue
        asked_model += 1
        t0 = time.monotonic()
        answer = brain.ask(phrase)
        took = time.monotonic() - t0
        ok = bool(set(tools_used) & want)
        by_model += ok
        print(f"{'ok ' if ok else 'мимо'} {took:4.1f} c «{phrase[:40]:40}» → "
              f"{tools_used or 'словами'} · «{answer[:40]}»")

    total = len(CASES) + len(LONG_TAIL)
    print(f"\nвсего верно: {by_rules + by_model}/{total} "
          f"(правилами {by_rules} из {total - asked_model}, своей моделью {by_model} из {asked_model})")
    brain.local.stop()


if __name__ == "__main__":
    main()
