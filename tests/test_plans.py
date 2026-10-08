# -*- coding: utf-8 -*-
"""Переписка в Telegram 07.10.2026: что не сработало — то и проверяем.

* «Что у меня в планах» уходило модели (правило знало только «какие планы»),
  а модель в ту минуту была без сети — ответ «Не получилось ответить».
* «Ты можешь где-то через 1,5 часа включить видео на Ютубе Just Dance» —
  такого умения не было, а «1,5 часа» не разбиралось вовсе.
* Телефон получал «Не получилось ответить», не дождавшись мозга: ждали 2 секунды.
* Два дела, записанные в одну секунду, получали один номер.

Действия подменены песочницей, дела — во временном файле.
"""
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import config, memory, router


def main():
    config.setup_console()
    from tests import sandbox
    acted = sandbox.enable()
    errors = 0
    real = memory.TASKS
    tmp = Path(tempfile.mkdtemp())
    memory.TASKS = tmp / "tasks.json"
    try:
        today = datetime.now().replace(second=0, microsecond=0)
        later = today + timedelta(minutes=2) if today.hour < 23 else today
        memory._save(memory.TASKS, [{"id": 1, "text": "ученик", "when": later.isoformat(),
                                     "done": False, "created": ""}])

        # 1. Вопрос о планах — любыми словами, без модели
        for phrase in ("что у меня в планах", "что в планах", "какие планы", "что запланировано",
                       "что на сегодня", "что у меня сегодня", "что у меня по делам",
                       "есть дела на сегодня", "мои планы", "что у меня в планах на завтра",
                       "планы на завтра", "что у меня на неделе"):
            r = router.handle(router.normalize(phrase), config.CFG)
            ok = not r.to_llm and r.say.startswith(("На сегодня", "На завтра", "На неделю"))
            errors += not ok
            print(f"{'ok ' if ok else 'НЕТ'} «{phrase}» → «{'МОДЕЛИ' if r.to_llm else r.say[:50]}»")
        for phrase in ("как у меня дела", "запланируй созвон завтра в 15"):
            r = router.handle(router.normalize(phrase), config.CFG)
            ok = r.to_llm or not r.say.startswith(("На сегодня", "На завтра"))
            errors += not ok
            print(f"{'ok ' if ok else 'НЕТ'} не список дел: «{phrase}» → «{'МОДЕЛИ' if r.to_llm else r.say[:50]}»")
        memory._save(memory.TASKS, [])

        # 2. «1,5 часа» — с запятой, как пишут с телефона
        base = datetime(2026, 10, 7, 22, 52)
        for text, want in (("через 1,5 часа", base + timedelta(minutes=90)),
                           ("через 1.5 часа", base + timedelta(minutes=90)),
                           ("через полтора часа", base + timedelta(minutes=90))):
            got = memory._parse_when(router.normalize(text), base)
            ok = got == want
            errors += not ok
            print(f"{'ok ' if ok else 'НЕТ'} «{text}» → {got:%H:%M}" if got else f"НЕТ «{text}» → None")

        # 3. Отложенная команда: записать, а не выполнить сразу
        acted.clear()
        r = router.handle(router.normalize("Ты можешь где-то через 1,5 часа включить видео на Ютубе Just Dance"),
                          config.CFG)
        tasks = memory._load(memory.TASKS, [])
        due = datetime.fromisoformat(tasks[0]["when"]) if tasks else None
        ok = (not acted and r.say.startswith("Хорошо, ") and "включи видео на ютубе just dance" in r.say
              and len(tasks) == 1 and tasks[0].get("do") == "включи видео на ютубе just dance"
              and due and abs((due - datetime.now()).total_seconds() - 90 * 60) < 90)
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} отложено, не включено сразу: «{r.say}»")

        for phrase, want in (("через полчаса включи музыку", "включи музыку"),
                             ("открой стим через 10 минут", "открой стим"),
                             ("выключи компьютер через 30 минут", None),        # у выключения своё
                             ("включи видео через тернии к звёздам", None)):     # «через» — не время
            memory._save(memory.TASKS, [])
            acted.clear()
            r = router.handle(router.normalize(phrase), config.CFG)
            tasks = memory._load(memory.TASKS, [])
            got = tasks[0].get("do") if tasks else None
            ok = got == want
            errors += not ok
            print(f"{'ok ' if ok else 'НЕТ'} «{phrase}» → отложено: {got}")

        # 4. В срок команда выполняется, хозяину — что сделано
        import jarvis as J
        j = J.Jarvis(voice_mode=False)
        said = []
        j.notify = lambda text, task=None: said.append(text)
        memory._save(memory.TASKS, [])
        memory.add_command("включи видео just dance на ютубе", datetime.now() - timedelta(seconds=5))
        acted.clear()
        for t in memory.due_now(window_min=0.2):
            j._run_planned(t)
        left = [t for t in memory._load(memory.TASKS, []) if not t["done"]]
        ok = (acted and acted[0][0] in ("youtube.play_on_youtube", "desktop.video") and not left
              and said and said[0].startswith("По плану: включи видео just dance на ютубе."))
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} в срок выполнено: {acted[:1]} · «{said[0] if said else '—'}»")

        # Проспанная на часы команда не выполняется, а честно называется
        memory._save(memory.TASKS, [])
        memory.add_command("включи музыку", datetime.now() - timedelta(hours=3))
        said.clear()
        acted.clear()
        j._tell_overdue()
        ok = not acted and said and "«включи музыку»" in said[0] and "не выполнил" in said[0]
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} проспанное не включаю: «{said[0] if said else '—'}»")

        # 5. Телефон ждёт мозг, сколько бы тот ни думал
        j.notify = J.Jarvis.notify.__get__(j)
        j.brain.ask = lambda text, image_path=None: time.sleep(3) or "Илон Маск — предприниматель."
        answer = j.answer_text("кто такой илон маск")
        ok = answer == "Илон Маск — предприниматель."
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} телефон дождался мозга (3 с): «{answer}»")

        # 6. Номера дел не повторяются, факты не дублируются
        memory._save(memory.TASKS, [])
        memory.add_task("купить хлеб", "через час")
        memory.add_task("купить молоко", "через час")
        ids = [t["id"] for t in memory._load(memory.TASKS, [])]
        ok = len(set(ids)) == 2
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} два дела в одну секунду — разные номера: {ids}")

        real_facts = memory.FACTS
        memory.FACTS = tmp / "facts.json"
        try:
            first, second = memory.remember("я работаю по ночам"), memory.remember("Я работаю по ночам")
            ok = first == "Запомнил." and second == "Это я уже помню." and len(memory._load(memory.FACTS, [])) == 1
        finally:
            memory.FACTS = real_facts
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} факт второй раз не пишется: «{first}», «{second}»")
    finally:
        memory.TASKS = real
        sandbox.disable()

    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
