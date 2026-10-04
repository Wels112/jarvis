# -*- coding: utf-8 -*-
"""Уроки: ученики, расписание, журнал, деньги.

Сделано под живую работу репетитора, а не «вообще календарь». Отсюда решения:

  • Расписание регулярное. Ученик занимается по вторникам в 16:00 — это
    записывается один раз, а не двадцать отдельных занятий на семестр.
  • Отдельно «план» и «факт». Урок может не состояться, и в деньгах он тогда
    не считается. Заработок берётся только из проведённых.
  • Журнал по ученику. «Петя плывёт в дробях» — то, что перед следующим
    занятием нужно вспомнить за две секунды, а не листать тетрадь.

Всё лежит обычным JSON в data/brain — открывается глазами и правится руками.
"""
import json
import re
import sys
from datetime import datetime, timedelta, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BRAIN = Path(__file__).resolve().parent.parent / "data" / "brain"
STUDENTS = BRAIN / "students.json"
LESSONS = BRAIN / "lessons.json"
ACTIVE = BRAIN / "active_lesson.json"      # какой урок идёт прямо сейчас
BRAIN.mkdir(parents=True, exist_ok=True)

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
WD_STEMS = ["понедельник", "вторник", "сред", "четверг", "пятниц", "суббот", "воскресень"]
SUBJECTS = ["информатика", "математика", "русский", "литература", "программирование",
            "английский", "физика", "подготовка к школе", "чтение", "окружающий мир"]


def _load(p: Path, default):
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def _save(p: Path, data):
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _plural(n, one, few, many):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _find_student(name: str):
    """Ищет по основе имени — голосом падежи гуляют («с Петей», «Петю», «Пети»)."""
    name = name.strip().lower()
    students = _load(STUDENTS, [])
    for s in students:
        if s["name"].lower() == name:
            return s
    # Три буквы — компромисс: «Петей» и «Петя» сходятся, «Петя» и «Соня» нет
    stem = name[:3]
    for s in students:
        other = s["name"].lower()
        if len(stem) >= 3 and (other.startswith(stem) or name.startswith(other[:3])):
            return s
    return None


_morph = None


def normal_name(word: str) -> str:
    """Имя в именительном падеже: «Пете» → «Петя», «Машу» → «Маша».

    Распознаватель пишет имя так, как оно прозвучало во фразе, а ученика надо
    завести под нормальным именем. pymorphy3 знает словарные имена; если его нет
    или имя незнакомое — оставляем как услышали, это лучше, чем исказить.
    """
    global _morph
    w = word.strip()
    if not w:
        return w
    try:
        if _morph is None:
            import pymorphy3
            _morph = pymorphy3.MorphAnalyzer()
        for p in _morph.parse(w):
            if "Name" in p.tag:
                return p.normal_form.capitalize()
    except Exception:
        pass
    return w.capitalize()


def decline(name: str, case: str) -> str:
    """Имя в нужном падеже: «с Петей», «про Петю», а не «с Петя».

    Приближение по окончанию — покрывает подавляющее большинство русских имён.
    Точное склонение потребовало бы словаря на десятки тысяч форм, а ассистенту
    достаточно не резать слух.
    """
    n = name.strip()
    if not n:
        return n
    low = n.lower()

    if low.endswith(("жа", "ча", "ша", "ща", "ка", "га", "ха")):   # Маша, Даша, Женька
        base = n[:-1]
        return {"вин": base + "у", "тв": base + "ей", "род": base + "и"}.get(case, n)
    if low.endswith("а"):                                          # Анна, Лиза, Никита
        base = n[:-1]
        return {"вин": base + "у", "тв": base + "ой", "род": base + "ы"}.get(case, n)
    if low.endswith("я"):                                          # Петя, Ваня, Соня
        base = n[:-1]
        return {"вин": base + "ю", "тв": base + "ей", "род": base + "и"}.get(case, n)
    if low.endswith("й"):                                          # Андрей, Сергей
        base = n[:-1]
        return {"вин": base + "я", "тв": base + "ем", "род": base + "я"}.get(case, n)
    if low.endswith(("ь",)):                                       # Игорь, Любовь
        base = n[:-1]
        return {"вин": base + "я", "тв": base + "ем", "род": base + "я"}.get(case, n)
    if low.endswith(("о", "е", "и", "у", "ы", "э", "ю")):          # Отто, Мари — не склоняем
        return n
    return {"вин": n + "а", "тв": n + "ом", "род": n + "а"}.get(case, n)   # Иван, Максим


# ---------------- ученики ----------------
def add_student(name: str, subject: str = "", rate: int = 0, duration: int = 60) -> str:
    name = name.strip().capitalize()
    if _find_student(name):
        return f"{name} уже есть в списке."
    students = _load(STUDENTS, [])
    students.append({
        "name": name,
        "subject": subject.strip().lower(),
        "rate": int(rate),
        "duration": int(duration),
        "schedule": [],
        "notes": [],
        "added": datetime.now().isoformat(timespec="seconds"),
    })
    _save(STUDENTS, students)
    tail = f", {subject}" if subject else ""
    tail += f", {rate} рублей за занятие" if rate else ""
    return f"Добавил ученика: {name}{tail}."


def list_students() -> str:
    students = _load(STUDENTS, [])
    if not students:
        return "Учеников пока нет. Скажи «добавь ученика Петя математика 1500»."
    parts = []
    for s in students:
        bit = s["name"]
        if s.get("subject"):
            bit += f" — {s['subject']}"
        parts.append(bit)
    n = len(students)
    return f"{n} {_plural(n, 'ученик', 'ученика', 'учеников')}: " + ", ".join(parts) + "."


def set_schedule(name: str, weekday: str, time_str: str) -> str:
    """«Петя по вторникам в 16» — регулярное занятие, а не одна дата."""
    s = _find_student(name)
    if not s:
        return f"Не нашёл ученика «{name}». Сначала добавь его."
    wd = None
    low = weekday.lower()
    for i, stem in enumerate(WD_STEMS):
        if low.startswith(stem[:5]):
            wd = i
            break
    if wd is None:
        return "Не понял день недели."
    m = re.search(r"(\d{1,2})(?:[:.\s](\d{2}))?", time_str)
    if not m:
        return "Не понял время."
    hh, mm = int(m.group(1)), int(m.group(2) or 0)

    students = _load(STUDENTS, [])
    for st in students:
        if st["name"] == s["name"]:
            slot = {"weekday": wd, "hour": hh, "minute": mm}
            if slot not in st["schedule"]:
                st["schedule"].append(slot)
            break
    _save(STUDENTS, students)
    return f"{s['name']} — {WEEKDAYS[wd]}, {hh:02d}:{mm:02d}. Записал в расписание."


# ---------------- расписание ----------------
def _planned_for(day: date):
    """Занятия на конкретный день: из регулярного расписания плюс разовые."""
    out = []
    for s in _load(STUDENTS, []):
        for slot in s.get("schedule", []):
            if slot["weekday"] == day.weekday():
                out.append({
                    "name": s["name"], "subject": s.get("subject", ""),
                    "at": datetime.combine(day, datetime.min.time()).replace(
                        hour=slot["hour"], minute=slot["minute"]),
                    "duration": s.get("duration", 60), "rate": s.get("rate", 0),
                })
    for l in _load(LESSONS, []):
        if l.get("status") == "planned" and l.get("when"):
            when = datetime.fromisoformat(l["when"])
            if when.date() == day:
                out.append({"name": l["student"], "subject": l.get("subject", ""),
                            "at": when, "duration": l.get("duration", 60),
                            "rate": l.get("rate", 0)})
    out.sort(key=lambda x: x["at"])
    return out


def schedule_for(when: str = "today") -> str:
    now = datetime.now()
    if when == "tomorrow":
        day, label = (now + timedelta(days=1)).date(), "Завтра"
    elif when == "week":
        parts = []
        total = 0
        for i in range(7):
            d = (now + timedelta(days=i)).date()
            items = _planned_for(d)
            total += len(items)
            if items:
                names = ", ".join(f"{it['name']} в {it['at']:%H:%M}" for it in items)
                parts.append(f"{WEEKDAYS[d.weekday()].capitalize()}: {names}")
        if not parts:
            return "На неделе занятий не запланировано."
        return (f"На неделе {total} {_plural(total, 'занятие', 'занятия', 'занятий')}. "
                + "; ".join(parts) + ".")
    else:
        day, label = now.date(), "Сегодня"

    items = _planned_for(day)
    if not items:
        return f"{label} занятий нет."
    lines = [f"{it['at']:%H:%M} {it['name']}" +
             (f" — {it['subject']}" if it["subject"] else "") for it in items]
    n = len(items)
    return (f"{label} {n} {_plural(n, 'занятие', 'занятия', 'занятий')}: "
            + "; ".join(lines) + ".")


NOTIFIED = BRAIN / "lesson_notified.json"


def due_soon(minutes: int = 10):
    """Уроки, до которых осталось около N минут.

    Дёргается фоновым циклом каждые десять секунд, поэтому о каждом занятии
    предупреждаем ровно один раз — отметки складываем в файл, чтобы перезапуск
    ассистента не начал напоминать заново про то же самое.
    """
    now = datetime.now()
    seen = set(_load(NOTIFIED, []))
    out = []
    changed = False

    for i in (0, 1):                      # сегодня и, ближе к полуночи, завтра
        for it in _planned_for((now + timedelta(days=i)).date()):
            left = (it["at"] - now).total_seconds() / 60
            if 0 < left <= minutes:
                key = f"{it['name']}|{it['at']:%Y-%m-%d %H:%M}"
                if key in seen:
                    continue
                seen.add(key)
                changed = True
                out.append({**it, "left": int(round(left))})

    if changed:
        # Держим только свежие отметки, иначе файл растёт вечно
        fresh = [k for k in seen
                 if k.split("|")[1][:10] >= (now - timedelta(days=2)).strftime("%Y-%m-%d")]
        _save(NOTIFIED, fresh)
    return out


def next_lesson() -> str:
    now = datetime.now()
    for i in range(8):
        for it in _planned_for((now + timedelta(days=i)).date()):
            if it["at"] > now:
                delta = it["at"] - now
                hours = int(delta.total_seconds() // 3600)
                mins = int((delta.total_seconds() % 3600) // 60)
                when = f"через {hours} ч {mins} мин" if hours else f"через {mins} мин"
                if delta.days >= 1:
                    when = f"{WEEKDAYS[it['at'].weekday()]} в {it['at']:%H:%M}"
                return f"Следующий — {it['name']} {when}."
    return "Впереди занятий нет."


# ---------------- проведение ----------------
def start_lesson(name: str = "") -> str:
    """«начали урок» — ставит таймер на длительность и отмечает начало."""
    from core import memory
    if not name:
        now = datetime.now()
        items = _planned_for(now.date())
        near = [i for i in items if abs((i["at"] - now).total_seconds()) < 3600]
        if not near:
            return "Не понял, с кем урок. Скажи «начали урок с Петей»."
        student = near[0]["name"]
        duration = near[0]["duration"]
    else:
        s = _find_student(name)
        if not s:
            return f"Не нашёл ученика «{name}»."
        student, duration = s["name"], s.get("duration", 60)

    memory.add_timer(duration, f"урок с {decline(student, 'тв')}")
    if duration > 10:
        memory.add_timer(duration - 5, f"пять минут до конца урока с {decline(student, 'тв')}")

    # Запоминаем, чей урок идёт: «урок закончен» должен закрыть именно его,
    # а не первое попавшееся занятие из расписания на сегодня
    _save(ACTIVE, {"student": student,
                   "started": datetime.now().isoformat(timespec="minutes")})
    return (f"Урок с {decline(student, 'тв')} пошёл. "
            f"{duration} минут, предупрежу за пять до конца.")


def finish_lesson(name: str = "", paid: bool = True) -> str:
    s = _find_student(name) if name else None
    if not s:
        # Сначала тот урок, который реально шёл
        active = _load(ACTIVE, None)
        if active:
            s = _find_student(active["student"])
    if not s:
        # Иначе ближайшее по времени занятие из расписания, а не первое в списке
        now = datetime.now()
        items = _planned_for(now.date())
        if not items:
            return "Не понял, чей урок закрывать."
        items.sort(key=lambda it: abs((it["at"] - now).total_seconds()))
        s = _find_student(items[0]["name"])

    lessons = _load(LESSONS, [])
    lessons.append({
        "student": s["name"], "subject": s.get("subject", ""),
        "when": datetime.now().isoformat(timespec="minutes"),
        "duration": s.get("duration", 60), "rate": s.get("rate", 0),
        "status": "done", "paid": bool(paid),
    })
    _save(LESSONS, lessons)
    if ACTIVE.exists():
        ACTIVE.unlink()                # урок закрыт, активного больше нет
    money = f" Плюс {s.get('rate', 0)} рублей." if s.get("rate") else ""
    return f"Урок с {decline(s['name'], 'тв')} отмечен проведённым.{money}"


def cancel_lesson(name: str) -> str:
    s = _find_student(name)
    if not s:
        return f"Не нашёл ученика «{name}»."
    lessons = _load(LESSONS, [])
    lessons.append({
        "student": s["name"], "subject": s.get("subject", ""),
        "when": datetime.now().isoformat(timespec="minutes"),
        "duration": s.get("duration", 60), "rate": 0,
        "status": "cancelled", "paid": False,
    })
    _save(LESSONS, lessons)
    return f"Отметил: занятие с {decline(s['name'], 'тв')} не состоялось."


# ---------------- журнал ----------------
def add_note(name: str, text: str) -> str:
    s = _find_student(name)
    if not s:
        return f"Не нашёл ученика «{name}»."
    students = _load(STUDENTS, [])
    for st in students:
        if st["name"] == s["name"]:
            st.setdefault("notes", []).append({
                "text": text.strip(),
                "at": datetime.now().isoformat(timespec="minutes"),
            })
            break
    _save(STUDENTS, students)
    return f"Записал про {decline(s['name'], 'вин')}."


def about_student(name: str) -> str:
    s = _find_student(name)
    if not s:
        return f"Не нашёл ученика «{name}»."
    done = [l for l in _load(LESSONS, [])
            if l["student"] == s["name"] and l["status"] == "done"]
    parts = [s["name"]]
    if s.get("subject"):
        parts.append(s["subject"])
    if done:
        n = len(done)
        parts.append(f"проведено {n} {_plural(n, 'занятие', 'занятия', 'занятий')}")
    notes = s.get("notes", [])
    if notes:
        parts.append("последнее: " + notes[-1]["text"])
    return ", ".join(parts) + "."


# ---------------- деньги ----------------
def earnings(period: str = "week") -> str:
    now = datetime.now()
    if period == "today":
        start, label = now.replace(hour=0, minute=0), "Сегодня"
    elif period == "month":
        start, label = now.replace(day=1, hour=0, minute=0), "За месяц"
    else:
        start, label = now - timedelta(days=7), "За неделю"

    done = [l for l in _load(LESSONS, [])
            if l["status"] == "done" and datetime.fromisoformat(l["when"]) >= start]
    if not done:
        return f"{label} проведённых занятий нет."
    total = sum(l.get("rate", 0) for l in done)
    unpaid = sum(l.get("rate", 0) for l in done if not l.get("paid"))
    n = len(done)
    out = (f"{label}: {n} {_plural(n, 'занятие', 'занятия', 'занятий')}, "
           f"{total} {_plural(total, 'рубль', 'рубля', 'рублей')}")
    if unpaid:
        out += f", из них не оплачено {unpaid}"
    return out + "."


def open_board() -> str:
    """Доска Miro — рабочий инструмент, к ней тянутся по десять раз в день."""
    import webbrowser
    webbrowser.open("https://miro.com/app/dashboard/")
    return "Открываю Miro."


def open_tutorlab() -> str:
    """Соседний проект хозяина — генератор уроков с выкладкой на доску."""
    import os
    import webbrowser
    web = Path("D:/tutorlab/web.bat")
    if not web.exists():
        return "Не нашёл TutorLab на диске D."
    try:
        os.startfile(str(web))
        return "Запускаю TutorLab."
    except Exception as e:
        return f"Не смог запустить TutorLab: {e}"


if __name__ == "__main__":
    from core import config
    config.setup_console()
    print(add_student("Петя", "математика", 1500, 60))
    print(add_student("Соня", "информатика", 1800, 90))
    print(set_schedule("Петя", "вторник", "16:00"))
    print(set_schedule("Соня", "вторник", "18:30"))
    print(list_students())
    print(schedule_for("week"))
    print(next_lesson())
    print(add_note("Петя", "плывёт в дробях, дать ещё примеров"))
    print(about_student("Петей"))
    print(finish_lesson("Петя"))
    print(earnings("week"))
