# -*- coding: utf-8 -*-
"""Напоминание, проскочившее окно будильника, всё равно звенит.

Окно будильника — 42 секунды. Компьютер уснул до срока и проснулся после —
напоминание раньше молчало до следующего перезапуска Джарвиса, а срок,
опоздавший на 45–90 секунд, не подбирал вообще никто. Настоящий список дел
не трогаем: работаем во временном файле.
"""
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import config, memory


def main():
    config.setup_console()
    import jarvis as J
    errors = 0
    now = datetime.now()

    def task(text, ago_s, timer=False):
        return {"id": len(text), "text": text, "done": False, "timer": timer,
                "when": (now - timedelta(seconds=ago_s)).isoformat(timespec="seconds")}

    real = memory.TASKS
    with tempfile.TemporaryDirectory() as tmp:
        memory.TASKS = Path(tmp) / "tasks.json"
        try:
            memory._save(memory.TASKS, [
                task("в окне", 20), task("щель", 60), task("спал", 70 * 60),
                task("таймер свежий", 120, timer=True), task("таймер вчерашний", 20 * 3600, timer=True),
                task("неделю назад", 7 * 24 * 3600), task("ещё не пора", -600)])
            on_time = [t["text"] for t in memory.due_now(window_min=0.2)]
            late = memory.overdue()
            got = sorted(t["text"] for t in late)
            want = ["спал", "таймер свежий", "щель"]
            ok = on_time == ["в окне"] and got == want
            errors += not ok
            print(f"{'ok ' if ok else 'НЕТ'} вовремя {on_time}, опоздавшие {got}")

            again = memory.overdue() + memory.due_now(window_min=0.2)
            errors += bool(again)
            print(f"{'ok ' if not again else 'НЕТ'} второй раз не звенит: {[t['text'] for t in again]}")
        finally:
            memory.TASKS = real

    pairs = J.late_phrases(late, at_start=False, now=now)
    said = [text for text, _ in pairs]
    ok = (len(said) == 3 and "Время вышло." in said
          and any(s.startswith("Напоминаю: щель — ") for s in said)
          and said[-1].startswith("Опоздал: компьютер, похоже, спал") and "спал — " in said[-1]
          and pairs[-1][1]["text"] == "спал")              # одно проспанное — кнопки к нему
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} на ходу: {said}")

    pairs = J.late_phrases(late, at_start=True, now=now)
    ok = (len(pairs) == 1 and pairs[0][0].startswith("Пока меня не было")
          and pairs[0][0].count(" — ") == 3 and pairs[0][1] is None)   # сводка — без кнопок
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} при запуске: {[text for text, _ in pairs]}")

    ok = J.late_phrases([], at_start=True) == [] and J.late_phrases([], at_start=False) == []
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} нечего — молчит")

    # Голосом сразу после звонка. Раньше «напомни ещё раз через 10 минут» записывало
    # дело «еще раз», а «готово, отметь выполненным» отвечало «не нашёл такую задачу»
    from core import router
    with tempfile.TemporaryDirectory() as tmp:
        memory.TASKS = Path(tmp) / "tasks.json"
        try:
            def after_ring(phrase):
                memory._save(memory.TASKS, [task("ученик", 5)])
                memory.due_now(window_min=0.2)
                said = router.handle(router.normalize(phrase), config.CFG).say
                tasks = memory._load(memory.TASKS, [])
                return said, tasks

            def minutes_ahead(tasks):
                return round((datetime.fromisoformat(tasks[0]["when"]) - datetime.now()).total_seconds() / 60)

            for phrase, mins in (("напомни ещё раз через 10 минут", 10), ("отложи на 15 минут", 15),
                                 ("отложи на час", 60), ("напомни через полчаса ещё раз", 30),
                                 ("напомни ещё раз", 10), ("напомни про ученика через 20 минут", None)):
                said, tasks = after_ring(phrase)
                if mins is None:            # своё дело со своим текстом — новое, а не перенос
                    ok = len(tasks) == 2 and said.startswith("Записал")
                else:
                    ok = (len(tasks) == 1 and said.startswith("Отложил: ученик")
                          and abs(minutes_ahead(tasks) - mins) <= 1 and not tasks[0].get("fired"))
                errors += not ok
                print(f"{'ok ' if ok else 'НЕТ'} «{phrase}» → «{said}»")

            for phrase in ("готово", "сделал", "готово, отметь выполненным"):
                said, tasks = after_ring(phrase)
                ok = tasks[0]["done"] and said == "Отметил выполненным: ученик."
                errors += not ok
                print(f"{'ok ' if ok else 'НЕТ'} «{phrase}» → «{said}»")

            # Давно не звенело — «напомни ещё раз» не выдумывает, «отложи» уходит модели
            memory._save(memory.TASKS, [])
            said = router.handle(router.normalize("напомни ещё раз через 10 минут"), config.CFG).say
            to_llm = router.handle(router.normalize("отложи на 15 минут"), config.CFG).to_llm
            ok = said.startswith("Не помню") and not memory._load(memory.TASKS, []) and to_llm
            errors += not ok
            print(f"{'ok ' if ok else 'НЕТ'} без недавнего звонка: «{said}», «отложи» — модели: {to_llm}")
        finally:
            memory.TASKS = real

    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
