# -*- coding: utf-8 -*-
"""Второй мозг: всё, что Джарвис помнит между запусками.

Три слоя, намеренно разделённые:
  • факты   — короткие утверждения о тебе и мире («мой канал — ytfactory»)
  • заметки — свободный текст с датой, растёт как дневник
  • дела    — задачи и события с временем, из них строится график

Хранение — обычные JSON и Markdown на диске. Никаких баз данных: файлы можно
открыть глазами, отредактировать руками и положить в облако.
"""
import json
import re
from datetime import datetime, timedelta, date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRAIN = ROOT / "data" / "brain"
FACTS = BRAIN / "facts.json"
TASKS = BRAIN / "tasks.json"
NOTES_DIR = BRAIN / "notes"
DIALOG = BRAIN / "dialog_history.json"

BRAIN.mkdir(parents=True, exist_ok=True)
NOTES_DIR.mkdir(parents=True, exist_ok=True)

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря"]


def _load(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def _save(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------- факты ----------------
def remember(text: str, tag: str = "общее") -> str:
    facts = _load(FACTS, [])
    facts.append({"text": text.strip(), "tag": tag,
                  "when": datetime.now().isoformat(timespec="seconds")})
    _save(FACTS, facts)
    return "Запомнил."


def recall(query: str = "", limit: int = 5) -> str:
    facts = _load(FACTS, [])
    if not facts:
        return "Пока ничего не запомнил."
    if query:
        words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2]
        scored = []
        for f in facts:
            low = f["text"].lower()
            score = sum(1 for w in words if w in low)
            if score:
                scored.append((score, f))
        scored.sort(key=lambda x: -x[0])
        hits = [f for _, f in scored[:limit]]
        if not hits:
            return f"Про «{query}» ничего не помню."
    else:
        hits = facts[-limit:]
    return " ".join(h["text"].rstrip(".") + "." for h in hits)


def forget(query: str) -> str:
    facts = _load(FACTS, [])
    before = len(facts)
    facts = [f for f in facts if query.lower() not in f["text"].lower()]
    _save(FACTS, facts)
    n = before - len(facts)
    if not n:
        return "Такого не помню."
    if n % 10 == 1 and n % 100 != 11:
        return f"Забыл {n} запись."
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"Забыл {n} записи."
    return f"Забыл {n} записей."


# ---------------- заметки ----------------
def add_note(text: str) -> str:
    day = NOTES_DIR / f"{date.today():%Y-%m-%d}.md"
    stamp = datetime.now().strftime("%H:%M")
    with day.open("a", encoding="utf-8") as f:
        f.write(f"- **{stamp}** {text.strip()}\n")
    return "Записал в заметки."


def last_notes(limit: int = 3) -> str:
    """Последние заметки — ответ на «что у меня в заметках» без уточнения."""
    lines = []
    for md in sorted(NOTES_DIR.glob("*.md"), reverse=True):
        for line in reversed(md.read_text(encoding="utf-8").splitlines()):
            text = line.lstrip("- ").replace("**", "")
            if text.strip():
                lines.append(f"{md.stem[-5:]} {text}")
            if len(lines) >= limit:
                break
        if len(lines) >= limit:
            break
    return "; ".join(lines) if lines else "Заметок пока нет."


def search_notes(query: str, limit: int = 5) -> str:
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2]
    hits = []
    for md in sorted(NOTES_DIR.glob("*.md"), reverse=True):
        for line in md.read_text(encoding="utf-8").splitlines():
            low = line.lower()
            if all(w in low for w in words) if words else False:
                # Без разметки: звёздочки из Markdown ассистент прочитал бы вслух
                day = "-".join(reversed(md.stem.split("-")[1:]))
                hits.append(f"{day} {line.lstrip('- ').replace('**', '')}")
                if len(hits) >= limit:
                    break
        if len(hits) >= limit:
            break
    return "; ".join(hits) if hits else f"В заметках про «{query}» ничего нет."


# ---------------- дела и график ----------------
# Сколько, если сказано словом: «через пару дней», «через полторы недели»
QTY = {"": 1, "один": 1, "одну": 1, "одного": 1, "полтора": 1.5, "полторы": 1.5,
       "пару": 2, "пары": 2, "два": 2, "две": 2, "двух": 2, "три": 3, "трёх": 3, "трех": 3,
       "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
       "несколько": 3}

# Единицы времени по основе слова: «через неделю», «через 2 недели», «через недельку»
UNITS = [("минут", "minutes"), ("мин", "minutes"), ("час", "hours"),
         ("сутк", "days"), ("дн", "days"), ("день", "days"),
         ("недел", "weeks"), ("месяц", "months"), ("год", "years"), ("лет", "years")]

DAYTIME = {"утра": (5, 11), "дня": (12, 17), "вечера": (17, 23), "ночи": (0, 4)}


def _add_months(d: datetime, n: int) -> datetime:
    import calendar
    year, month = divmod(d.month - 1 + n, 12)
    year, month = d.year + year, month + 1
    return d.replace(year=year, month=month, day=min(d.day, calendar.monthrange(year, month)[1]))


def _relative(t: str, now: datetime):
    """«через 20 минут», «через неделю», «через полтора часа», «через месяц»."""
    if re.search(r"через\s+полчаса", t):
        return now + timedelta(minutes=30)
    qty = "|".join(sorted(QTY, key=len, reverse=True))
    units = "|".join(u for u, _ in UNITS)
    m = re.search(rf"через\s+(?:(\d+)|({qty}))?\s*({units})\w*", t)
    if not m:
        return None
    n = float(m.group(1)) if m.group(1) else QTY.get(m.group(2) or "", 1)
    unit = next(kind for stem, kind in UNITS if m.group(3).startswith(stem))
    if unit == "months":
        return _add_months(now, int(n)) + timedelta(days=round((n % 1) * 30))
    if unit == "years":
        return _add_months(now, int(n * 12))
    return now + timedelta(**{unit: n})


def _parse_when(text: str):
    """Когда именно: «завтра в 15», «через неделю в 15-30», «в среду», «5 октября в 9:30».

    Разбор дня и времени разделён намеренно. Раньше код возвращал ответ сразу,
    как только видел «через N», и время в той же фразе терялось: напоминание
    «через неделю в 15:30» на показе 02.10.2026 встало на тот же день на 15:30.
    """
    t = text.lower().strip()
    now = datetime.now()

    base = _relative(t, now)
    relative_short = bool(base) and re.search(r"через\s+\S*\s*(минут|мин|час|полчаса)", t)
    if base is None:
        base = now
        if "послезавтра" in t:
            base = now + timedelta(days=2)
        elif "завтра" in t:
            base = now + timedelta(days=1)
        elif "сегодня" in t:
            base = now
        else:
            for i, wd in enumerate(WEEKDAYS):
                if wd[:4] in t:                      # «в среду» — по основе, не по слову
                    shift = (i - now.weekday()) % 7
                    if "следующ" in t:
                        shift = shift or 7
                        shift += 7 if shift < 7 else 0
                    base = now + timedelta(days=shift or 7)
                    break
            else:
                if "следующ" in t and re.search(r"недел", t):
                    base = now + timedelta(days=7 - now.weekday())

    m = re.search(r"(\d{1,2})\s*(" + "|".join(MONTHS) + r")", t)
    if m:
        month = MONTHS.index(m.group(2)) + 1
        day = int(m.group(1))
        year = base.year + (1 if (month, day) < (now.month, now.day) else 0)
        try:
            base = base.replace(year=year, month=month, day=day)
        except ValueError:                           # 31 февраля и прочие опечатки
            pass

    if "в полдень" in t or "в полночь" in t:
        noon = "в полдень" in t
        when = base.replace(hour=12 if noon else 0, minute=0, second=0, microsecond=0)
        if not noon:
            when += timedelta(days=1)
        if when <= now:
            when += timedelta(days=1)      # полдень уже прошёл — значит завтрашний
        return when

    m = re.search(r"(?:в|к|на)\s*(\d{1,2})(?:\s*[:.\-]\s*(\d{2}))?(?!\d)", t)
    if m and not relative_short:
        hh, mm = int(m.group(1)), int(m.group(2) or 0)
        for word, (lo, hi) in DAYTIME.items():
            if word in t and not lo <= hh <= hi:     # «в 7 вечера» → 19
                hh = (hh + 12) % 24
                break
        else:
            # «напомни в 9» вечером — значит утром следующего дня, а не в прошлом
            if hh < 12 and base.date() == now.date() and now.hour >= 12:
                hh += 12 if hh + 12 > now.hour else 0
        if hh > 23 or mm > 59:
            return None
        when = base.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if when <= now and base.date() == now.date():
            when += timedelta(days=1)                # названное время уже прошло
        return when

    if relative_short or base.date() != now.date():
        # день назван, а час нет: утро следующего дня — разумная догадка
        return base if relative_short else base.replace(hour=9, minute=0, second=0, microsecond=0)
    return None


def add_task(text: str, when_text: str = "") -> str:
    tasks = _load(TASKS, [])
    when = _parse_when(when_text or text)
    clean = re.sub(r"\b(напомни|напомнить|поставь|добавь|задачу|мне|что|чтобы)\b", "", text,
                   flags=re.I)
    # вырезаем саму формулировку времени, иначе задача звучит как
    # «позвонить маме завтра в 12» рядом с уже разобранным временем
    clean = re.sub(r"\b(послезавтра|завтра|сегодня|вечером|утром|днем|днём|ночью)\b", "", clean, flags=re.I)
    qty = "|".join(sorted(QTY, key=len, reverse=True))
    units = "|".join(u for u, _ in UNITS)
    clean = re.sub(rf"\bчерез\s+(?:полчаса|(?:\d+|{qty})?\s*(?:{units})\w*)",
                   "", clean, flags=re.I)
    clean = re.sub(r"\bв\s+(полдень|полночь)\b", "", clean, flags=re.I)
    clean = re.sub(r"\b(на|в)\s+следующ\w+\s+недел\w+", "", clean, flags=re.I)
    clean = re.sub(r"\bв\s*\d{1,2}([:.]\d{2})?\b", "", clean, flags=re.I)
    clean = re.sub(r"\b\d{1,2}\s+(" + "|".join(MONTHS) + r")\b", "", clean, flags=re.I)
    # по основе слова, иначе «в пятницу» не совпадёт с «пятница»
    clean = re.sub(r"\b(в|во)\s+(" + "|".join(w[:5] for w in WEEKDAYS) + r")\w*", "", clean, flags=re.I)
    clean = re.sub(r"\s+", " ", clean).strip(" ,.") or text
    tasks.append({
        "id": int(datetime.now().timestamp()),
        "text": clean,
        "when": when.isoformat(timespec="minutes") if when else None,
        "done": False,
        "created": datetime.now().isoformat(timespec="seconds"),
    })
    _save(TASKS, tasks)
    if when:
        return f"Записал: {clean}. Напомню {when:%d.%m в %H:%M}."
    return f"Записал: {clean}."


def add_timer(minutes: float, label: str = "") -> str:
    """Кухонный таймер. Живёт в том же списке задач — отдельный механизм не нужен."""
    tasks = _load(TASKS, [])
    when = datetime.now() + timedelta(minutes=float(minutes))
    text = f"таймер{' — ' + label if label else ''}"
    tasks.append({
        "id": int(datetime.now().timestamp()),
        "text": text,
        "when": when.isoformat(timespec="seconds"),
        "done": False,
        "timer": True,
        "created": datetime.now().isoformat(timespec="seconds"),
    })
    _save(TASKS, tasks)
    def _form(n, one, few, many):
        if n % 10 == 1 and n % 100 != 11:
            return one
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return few
        return many

    m = int(minutes)
    if minutes == m and m >= 60 and m % 60 == 0:      # «2 часа», а не «120 минут»
        h = m // 60
        return f"Таймер на {h} {_form(h, 'час', 'часа', 'часов')}. Скажу, когда время выйдет."
    if minutes == m and m >= 1:
        return (f"Таймер на {m} {_form(m, 'минуту', 'минуты', 'минут')}. "
                "Скажу, когда время выйдет.")
    sec = round(minutes * 60)
    return (f"Таймер на {sec} {_form(sec, 'секунду', 'секунды', 'секунд')}. "
            "Скажу, когда время выйдет.")


def active_timers() -> str:
    """Сколько осталось на заведённых таймерах."""
    now = datetime.now()
    live = []
    for t in _load(TASKS, []):
        if t.get("timer") and not t["done"] and not t.get("fired") and t["when"]:
            left = (datetime.fromisoformat(t["when"]) - now).total_seconds()
            if left > 0:
                live.append(left)
    if not live:
        return "Таймеров нет."
    live.sort()
    parts = []
    for s in live[:3]:
        if s >= 3600:
            h, m = int(s // 3600), round((s % 3600) / 60)
            parts.append(f"{h} ч {m} мин" if m else f"{h} ч")
        elif s >= 60:
            parts.append(f"{round(s/60)} мин")
        else:
            parts.append(f"{round(s)} сек")
    return "Осталось: " + ", ".join(parts) + "."


def list_tasks(when: str = "today") -> str:
    # Таймеры живут в том же файле, но в планах на день им не место
    tasks = [t for t in _load(TASKS, []) if not t["done"] and not t.get("timer")]
    if not tasks:
        return "Задач нет, всё чисто."
    now = datetime.now()
    if when == "today":
        sel = [t for t in tasks if t["when"] and
               datetime.fromisoformat(t["when"]).date() == now.date()]
        label = "На сегодня"
    elif when == "tomorrow":
        tm = (now + timedelta(days=1)).date()
        sel = [t for t in tasks if t["when"] and
               datetime.fromisoformat(t["when"]).date() == tm]
        label = "На завтра"
    elif when == "week":
        end = now + timedelta(days=7)
        sel = [t for t in tasks if t["when"] and now <= datetime.fromisoformat(t["when"]) <= end]
        label = "На неделю"
    else:
        sel = tasks
        label = "Всего"
    if not sel:
        return f"{label} ничего не запланировано."
    sel.sort(key=lambda t: t["when"] or "9999")
    lines = []
    for t in sel[:10]:
        if not t["when"]:
            lines.append(f"без времени — {t['text']}")
            continue
        dt = datetime.fromisoformat(t["when"])
        # день называем только когда он не очевиден из самого вопроса
        if when in ("today", "tomorrow") or dt.date() == now.date():
            stamp = dt.strftime("%H:%M")
        elif dt.date() == (now + timedelta(days=1)).date():
            stamp = f"завтра в {dt:%H:%M}"
        else:
            stamp = f"{WEEKDAYS[dt.weekday()]} в {dt:%H:%M}"
        lines.append(f"{stamp} — {t['text']}")
    return f"{label} {len(sel)}: " + "; ".join(lines) + "."


def complete_task(query: str) -> str:
    tasks = _load(TASKS, [])
    for t in tasks:
        if not t["done"] and query.lower() in t["text"].lower():
            t["done"] = True
            _save(TASKS, tasks)
            return f"Отметил выполненным: {t['text']}."
    return "Не нашёл такую задачу."


def due_now(window_min: int = 1):
    """Задачи, которым пора прозвенеть. Дёргается фоновым будильником."""
    now = datetime.now()
    tasks = _load(TASKS, [])
    fired = []
    changed = False
    for t in tasks:
        if t["done"] or not t["when"] or t.get("fired"):
            continue
        when = datetime.fromisoformat(t["when"])
        if 0 <= (now - when).total_seconds() < window_min * 60 + 30:
            t["fired"] = True
            fired.append(t)
            changed = True
    if changed:
        _save(TASKS, tasks)
    return fired


def when_phrase(when: datetime) -> str:
    """«вчера в 15:30», «сегодня в 9:00», «2 октября в 15:30» — как сказал бы человек."""
    days = (when.date() - date.today()).days
    named = {-2: "позавчера", -1: "вчера", 0: "сегодня", 1: "завтра", 2: "послезавтра"}
    day = named.get(days) or f"{when.day} {MONTHS[when.month - 1]}"
    return f"{day} в {when:%H:%M}"


def overdue(max_age_h: int = 72):
    """Напоминания, которые прозвенели бы, пока Джарвис был выключен.

    Будильник смотрит узкое окно вокруг «сейчас». Если в ту минуту Джарвиса не
    запустили, напоминание пропадало совсем: срок прошёл, окно закрылось,
    отметки «прозвенело» нет — и больше о нём никто не вспоминал. Такое нужно
    отдать при запуске, честно сказав, что оно просрочено.

    Таймеры пропускаются: вчерашний кухонный таймер — уже не новость.
    """
    now = datetime.now()
    tasks = _load(TASKS, [])
    late, changed = [], False
    for t in tasks:
        if t["done"] or not t["when"] or t.get("fired") or t.get("timer"):
            continue
        age = (now - datetime.fromisoformat(t["when"])).total_seconds()
        if 90 <= age <= max_age_h * 3600:
            t["fired"] = True
            late.append(t)
            changed = True
    if changed:
        _save(TASKS, tasks)
    return late


# ---------------- история диалога ----------------
def log_dialog(role: str, text: str, keep: int = 200):
    hist = _load(DIALOG, [])
    hist.append({"role": role, "text": text,
                 "at": datetime.now().isoformat(timespec="seconds")})
    _save(DIALOG, hist[-keep:])


def recent_dialog(n: int = 10):
    return _load(DIALOG, [])[-n:]


def context_for_llm() -> str:
    """Слепок памяти, который уходит в модель как системный контекст."""
    facts = _load(FACTS, [])
    parts = []
    if facts:
        parts.append("Что я знаю о хозяине: " +
                     " ".join(f["text"].rstrip(".") + "." for f in facts[-15:]))
    today = list_tasks("today")
    if "ничего не запланировано" not in today and "Задач нет" not in today:
        parts.append("Задачи на сегодня: " + today)
    return "\n".join(parts)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT))
    from core import config
    config.setup_console()
    print(remember("Хозяин работает по ночам и не любит лишних вопросов"))
    print(remember("Бюджет на инструменты — строго ноль долларов", tag="проект"))
    print(recall("бюджет"))
    print(add_task("созвон с подрядчиком", "завтра в 15"))
    print(add_task("выложить ролик", "через 2 часа"))
    print(list_tasks("today"))
    print(list_tasks("week"))
    print(add_note("Джарвис собран и впервые заговорил"))
