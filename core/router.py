# -*- coding: utf-8 -*-
"""Роутер команд — то, что отличает ассистента от чат-бота.

Порядок разбора намеренно такой:
  1) жёсткие правила  — «громкость 30», «открой стим». Ноль задержки, ноль трафика,
     работает без интернета. Сюда попадает 90% бытовых команд.
  2) модель (Gemini)  — всё остальное: свободный разговор, сложные просьбы,
     вопросы. Медленнее, требует сети, поэтому вторым эшелоном.

Опасные действия не выполняются сразу: роутер возвращает их как «отложенные»
вместе с вопросом, и главный цикл переспрашивает голосом.
"""
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skills import system as S
from skills import desktop as D
from skills import youtube as YT
from skills import telegram as TG
from skills import weather as W
from skills import cleanup as CL
from skills import tools as TL
from skills import lessons as LS
from core import corrections
from core import memory


@dataclass
class Reply:
    say: str = ""
    pending: Optional[Callable] = None     # действие, ждущее подтверждения
    pending_desc: str = ""
    quit: bool = False
    stop_speech: bool = False
    to_llm: bool = False                   # правила не справились — отдать модели
    meta: dict = field(default_factory=dict)


NUM_WORDS = {
    "ноль": 0, "нуль": 0, "десять": 10, "пятнадцать": 15, "двадцать": 20,
    "тридцать": 30, "сорок": 40, "пятьдесят": 50, "шестьдесят": 60,
    "семьдесят": 70, "восемьдесят": 80, "девяносто": 90, "сто": 100,
    "половину": 50, "максимум": 100, "минимум": 10,
}


def _num(text: str, default=None):
    m = re.search(r"\d+", text)
    if m:
        return int(m.group())
    for w, v in NUM_WORDS.items():
        if w in text:
            return v
    return default


def normalize(text: str) -> str:
    t = text.lower().strip()
    t = t.replace("ё", "е")
    # Двоеточие и точку между цифрами не трогаем: иначе «в 18:30» станет
    # «в 18 30», и время в расписании потеряет минуты
    t = re.sub(r"(?<!\d)[.,!?;:\"'«»]+|[.,!?;:\"'«»]+(?!\d)", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    # Чиним частые ослышки и приводим числительные к цифрам, чтобы
    # «громкость тридцать» и «громкость 30» шли по одному правилу
    return corrections.apply(t)


# Узнавание имени — в core/wake.py: сравнение по звучанию, а не по шаблону.
# Старый регэксп был подогнан под синтетический голос и на живом тесте
# 13.09.2026 не узнал ни одного из пяти обращений хозяина.
from core import wake


def strip_wake(text: str, wake_words=None) -> str:
    """Убирает обращение: «Джарвис, открой браузер» → «открой браузер»."""
    found, rest = wake.find(text)
    return rest if found else text.strip(" ,.")


def has_wake(text: str, wake_words=None) -> bool:
    return wake.find(normalize(text))[0]


# ---------------- правила ----------------
def handle(text: str, cfg: dict) -> Reply:
    t = normalize(text)
    if not t:
        return Reply()

    safe = cfg.get("safety", {})
    confirm_needed = safe.get("confirm_destructive", True)

    # --- прервать речь / выход ---
    if re.fullmatch(r"(стоп|хватит|замолчи|тихо|отмена|молчи)", t):
        return Reply(say="", stop_speech=True)
    if re.search(r"^(выход|закройся|выключись|отбой|спасибо пока|до свидания)$", t):
        return Reply(say="До связи. Буду рядом.", quit=True)
    if re.search(r"отмени (выключение|выключение компьютера)", t):
        return Reply(say=S.cancel_shutdown())

    # --- время и дата ---
    if re.search(r"(который час|сколько времени|какое (сегодня )?число|какой сегодня день)", t):
        return Reply(say=S.what_time())

    # --- громкость ---
    # «тише на 20» — изменить на 20; «убавь до 30», «громкость 30» — поставить ровно 30
    m = re.search(r"(тише|убав\w*|уменьш\w*|снизь|понизь)\s+на\s+(\d+)", t)
    if m:
        return Reply(say=S.change_volume(-int(m.group(2))))
    m = re.search(r"(громче|прибав\w*|увелич\w*|добав\w*|подними|повысь)\s+на\s+(\d+)", t)
    if m:
        return Reply(say=S.change_volume(int(m.group(2))))
    m = re.search(r"(?:тише|громче|убав\w*|прибав\w*|уменьш\w*|увелич\w*|сделай|поставь)"
                  r"\s+(?:громкость\s+)?до\s+(\d+)", t)
    if m:
        return Reply(say=S.set_volume(int(m.group(1))))
    if re.search(r"(громкость|звук)\s*(на)?\s*(\d+|ноль|половину|максимум|минимум)", t):
        return Reply(say=S.set_volume(_num(t, 50)))
    if re.search(r"^(сделай )?(по)?громче", t):
        return Reply(say=S.change_volume(+10))
    if re.search(r"^(сделай )?(по)?тише", t):
        return Reply(say=S.change_volume(-10))
    if re.search(r"(выключи|отключи|убери) звук|заглуши", t):
        return Reply(say=S.mute(True))
    if re.search(r"(включи|верни) звук", t):
        return Reply(say=S.mute(False))
    if re.search(r"какая громкость", t):
        return Reply(say=S.get_volume())

    # --- плеер ---
    if re.search(r"^(поставь на )?паузу$|^пауза$|^останови музыку", t):
        return Reply(say=S.media_key("pause"))
    if re.search(r"^(включи|продолжи) музыку$|^играй$", t):
        return Reply(say=S.media_key("play"))
    if re.search(r"следующ(ий|ая) (трек|песня|песню)|переключи (трек|песню)|дальше", t):
        return Reply(say=S.media_key("next"))
    if re.search(r"предыдущ(ий|ая) (трек|песня|песню)|назад трек", t):
        return Reply(say=S.media_key("prev"))

    # --- место на диске и очистка ---
    if re.search(r"(сколько (свободного )?места|что с диск\w+|заполнен\w* диск)", t):
        return Reply(say=CL.disk_report())
    if re.search(r"(что можно (почистить|удалить)|сколько мусора|проверь диск)", t):
        return Reply(say=CL.clean(dry_run=True))
    if re.search(r"(почисти|очисти|освободи)\s*(диск|место|мусор)?", t):
        preview = CL.clean(dry_run=True)
        return Reply(say=preview + " Чистить? Скажи «да».",
                     pending=CL.clean, pending_desc="очистка диска")

    # --- уроки и ученики ---
    m = re.search(r"добав\w*\s+ученик\w*\s+(\w+)(?:\s+(\w+))?(?:\s+(\d+))?", t)
    if m:
        subj = m.group(2) or ""
        if subj and subj.isdigit():
            subj = ""
        # Распознаватель ставит имя в падеж: «добавь ученика Пете» — приводим к «Петя»
        return Reply(say=LS.add_student(LS.normal_name(m.group(1)), subj,
                                        int(m.group(3) or 0)))
    if re.search(r"(список|какие|сколько) учеников|мои ученики", t):
        return Reply(say=LS.list_students())

    m = re.search(r"(?:поставь|запиши|занеси)\s+(\w+)\s+на\s+"
                  r"(понедельник\w*|вторник\w*|сред\w+|четверг\w*|пятниц\w+|суббот\w+|воскресень\w+)"
                  r"\s*(?:в|на)?\s*(\d{1,2}(?:[:.]\d{2})?)", t)
    if m:
        return Reply(say=LS.set_schedule(m.group(1), m.group(2), m.group(3)))

    if re.search(r"(какие|что за|сколько)\s+(уроки|занятия|уроков|занятий)|расписание урок", t):
        if "завтра" in t:
            return Reply(say=LS.schedule_for("tomorrow"))
        if "недел" in t:
            return Reply(say=LS.schedule_for("week"))
        return Reply(say=LS.schedule_for("today"))
    if re.search(r"(кто следующий|когда следующий|следующий урок|следующее занятие)", t):
        return Reply(say=LS.next_lesson())

    m = re.search(r"(?:начали|начинаем|начал|стартуем)\s*(?:урок|занятие)?\s*(?:с\s+(\w+))?", t)
    if m and re.search(r"(начали|начинаем|начал|стартуем)", t):
        return Reply(say=LS.start_lesson(m.group(1) or ""))
    m = re.search(r"(?:урок|занятие)\s+(?:законч\w+|всё|все)|закончили\s*(?:с\s+(\w+))?|"
                  r"(?:отметь|запиши)\s+урок\s+с\s+(\w+)", t)
    if m:
        who = (m.group(1) or m.group(2) or "") if m.lastindex else ""
        return Reply(say=LS.finish_lesson(who))
    m = re.search(r"отмени\s+(?:урок|занятие)\s+с\s+(\w+)", t)
    if m:
        return Reply(say=LS.cancel_lesson(m.group(1)))

    m = re.search(r"(?:запиши|заметь)\s+про\s+(\w+)\s+(?:что\s+)?(.+)$", t)
    if m:
        return Reply(say=LS.add_note(m.group(1), m.group(2)))
    m = re.search(r"(?:что\s+(?:там\s+)?с|расскажи про|как дела у)\s+(\w+)$", t)
    if m:
        return Reply(say=LS.about_student(m.group(1)))

    if re.search(r"сколько (я )?заработал|мой доход|сколько денег|заработок", t):
        if "месяц" in t:
            return Reply(say=LS.earnings("month"))
        if "сегодня" in t:
            return Reply(say=LS.earnings("today"))
        return Reply(say=LS.earnings("week"))

    if re.search(r"открой (доску|миро|meero|miro)|открой борд", t):
        return Reply(say=LS.open_board())
    if re.search(r"(тьюторлаб|тюторлаб|tutorlab|генератор уроков|сделай урок)", t):
        return Reply(say=LS.open_tutorlab())

    # --- счёт, деньги, единицы ---
    m = re.search(r"^(?:сколько будет|посчитай|вычисли|подсчитай)\s+(.+)$", t)
    if m:
        return Reply(say=TL.calculate(m.group(1)))
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*процентов?\s+от\s+(\d+(?:[.,]\d+)?)", t)
    if m:
        return Reply(say=TL.calculate(t))

    m = re.search(r"курс\s+(\w+)", t)
    if m:
        return Reply(say=TL.exchange_rate(m.group(1)))
    m = re.search(r"сколько стоит\s+(доллар\w*|евро|юан\w*|биткоин\w*|фунт\w*|тенге|гривн\w*)", t)
    if m:
        return Reply(say=TL.exchange_rate(m.group(1)))
    m = re.search(r"(?:переведи|конвертируй|сколько будет)\s+(\d+(?:[.,]\d+)?)\s+"
                  r"(доллар\w*|евро|рубл\w*|юан\w*|фунт\w*|тенге|гривн\w*|биткоин\w*)\s+"
                  r"(?:в|на)\s+(доллар\w*|евро|рубл\w*|юан\w*|фунт\w*|тенге|гривн\w*)", t)
    if m:
        return Reply(say=TL.convert_currency(float(m.group(1).replace(",", ".")),
                                             m.group(2), m.group(3)))

    m = re.search(r"(?:переведи|сколько будет)\s+(\d+(?:[.,]\d+)?)\s*"
                  r"(км|м|см|мм|кг|г|т|час\w*|минут\w*|гб|мб|кб|миль)\s+(?:в|на)\s+"
                  r"(км|м|см|мм|кг|г|т|час\w*|минут\w*|секунд\w*|гб|мб|кб|миль|фунтов)", t)
    if m:
        return Reply(say=TL.convert_unit(float(m.group(1).replace(",", ".")),
                                         m.group(2), m.group(3)))

    # --- будильник ---
    m = re.search(r"(?:разбуди|будильник|подъем)\s*(?:меня\s*)?(?:на|в)?\s*(\d{1,2}(?:[:.\s]\d{2})?\s*(?:утра|вечера|ночи)?)", t)
    if m:
        return Reply(say=TL.set_alarm(m.group(1)))

    # --- перевод на другой язык ---
    m = re.search(r"(?:переведи|как будет)\s+(?:на\s+)?(английск\w+|немецк\w+|французск\w+|"
                  r"испанск\w+|китайск\w+|японск\w+|турецк\w+|итальянск\w+)\s+(.+)$", t)
    if m:
        codes = {"англ": "en", "немец": "de", "француз": "fr", "испан": "es",
                 "китай": "zh", "япон": "ja", "турец": "tr", "италь": "it"}
        code = next((v for k, v in codes.items() if m.group(1).startswith(k)), "en")
        return Reply(say=TL.translate(m.group(2), code))
    m = re.search(r"(?:переведи|как будет)\s+(.+?)\s+на\s+(английск\w+|немецк\w+|"
                  r"французск\w+|испанск\w+|китайск\w+|японск\w+)$", t)
    if m:
        codes = {"англ": "en", "немец": "de", "француз": "fr", "испан": "es",
                 "китай": "zh", "япон": "ja"}
        code = next((v for k, v in codes.items() if m.group(2).startswith(k)), "en")
        return Reply(say=TL.translate(m.group(1), code))

    # --- запомнить ослышку ---
    m = re.search(r"^(?:запомни что )?я говорю\s+(.+?)\s+(?:а не|это)\s+(.+)$", t)
    if m:
        return Reply(say=corrections.add(m.group(1), m.group(2)))

    # --- погода ---
    m = re.search(r"погод\w*(?:\s+(?:в|на)\s+(.+))?$", t)
    if m:
        city = (m.group(1) or "").strip()
        city = re.sub(r"^(городе|город)\s+", "", city)
        if city in ("сегодня", "улице", "завтра", "сейчас", ""):
            city = ""
        return Reply(say=W.weather(city))

    # --- таймер ---
    if re.search(r"(сколько (осталось|там|на таймере)|что с таймером|таймеры)", t):
        return Reply(say=memory.active_timers())

    m = re.search(r"таймер\w*\s*(?:на\s*)?(\d+)\s*(секунд\w*|сек|минут\w*|мин|час\w*)?", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2) or "минут"
        if unit.startswith("сек"):
            mins = n / 60
        elif unit.startswith("час"):
            mins = n * 60
        else:
            mins = n
        return Reply(say=memory.add_timer(mins))

    # --- память ---
    # Заметки проверяются до фактов: «запиши в заметки…» подходит под оба правила,
    # и раньше такая просьба уходила в факты — заметка не появлялась
    m = re.search(r"^(?:заметка|в заметки|(?:запиши|занеси|добавь)\s+в\s+заметки)[:,\s]\s*(.+)$", t)
    if m:
        return Reply(say=memory.add_note(m.group(1)))
    m = re.search(r"^(?:что|найди|поищи|посмотри)?\s*(?:у меня\s+)?в заметках\s*"
                  r"(?:про|о|об|по)?\s*(.*)$", t)
    if m:
        return Reply(say=memory.search_notes(m.group(1)) if m.group(1).strip()
                     else memory.last_notes())
    m = re.search(r"^(?:запомни|заметь|запиши)(?:\s+что)?\s+(.+)$", t)
    if m:
        return Reply(say=memory.remember(m.group(1)))
    m = re.search(r"^(?:что ты (?:помнишь|знаешь))\s*(?:про|о|об)?\s*(.*)$", t)
    if m:
        return Reply(say=memory.recall(m.group(1)))
    m = re.search(r"^забудь\s+(?:про\s+|о\s+)?(.+)$", t)
    if m:
        return Reply(say=memory.forget(m.group(1)))

    # --- youtube ---
    m = re.search(r"(?:включи|поставь|найди)\s+(?:на\s+)?(?:ютубе?|youtube)\s+(.+)$", t)
    if m:
        return Reply(say=YT.play_on_youtube(m.group(1)))
    m = re.search(r"(?:включи|поставь)\s+(.+?)\s+на\s+(?:ютубе?|youtube)$", t)
    if m:
        return Reply(say=YT.play_on_youtube(m.group(1)))
    if re.search(r"(сколько (у меня )?подписчиков|статистика канала|"
                 r"как дела (с каналом|у канала)|^(что с )?мо(й|им) канал\w*\??$)", t):
        return Reply(say=YT.channel_stats())
    if re.search(r"(последние|свежие) (ролики|видео)|как зашл[оа]", t):
        return Reply(say=YT.latest_videos())

    # --- программы и сайты ---
    m = re.search(r"^(?:открой|запусти|включи|врубай|давай)\s+(.+)$", t)
    if m:
        target = m.group(1).strip()
        target = re.sub(r"^(мне|пожалуйста|программу|приложение|сайт)\s+", "", target)
        if target in S.SITES or target.startswith("http") or ".com" in target or ".ru" in target:
            return Reply(say=S.open_site(target))
        return Reply(say=S.open_app(target))

    m = re.search(r"^(?:закрой|выключи|убей|заверши)\s+(.+)$", t)
    if m:
        target = m.group(1).strip()
        if target in ("компьютер", "комп", "пк"):
            pass          # обрабатывается ниже как выключение системы
        else:
            return Reply(say=S.close_app(target))

    if re.search(r"обнови (список )?программ", t):
        n = len(S.build_app_index(force=True))
        return Reply(say=f"Список обновлён, вижу {n} программ.")

    # --- поиск ---
    m = re.search(r"^(?:найди|поищи|загугли|погугли)\s+(?:в интернете\s+|в гугле\s+)?(.+)$", t)
    if m:
        q = m.group(1).strip()
        mf = re.match(r"файл\s+(.+)", q)
        if mf:
            return Reply(say=S.find_file(mf.group(1)))
        return Reply(say=S.search_web(q))

    # --- система ---
    if re.search(r"(как дела с (компьютером|системой)|статус системы|загрузка|нагрузка|сколько (памяти|места))", t):
        return Reply(say=S.system_info())
    if re.search(r"(что жрет|что ест|тяжелые процессы|какие процессы)", t):
        return Reply(say=S.top_processes())
    if re.search(r"(сделай )?скриншот|сфотографируй экран|снимок экрана", t):
        path = S.screenshot()
        return Reply(say="Скриншот готов.", meta={"screenshot": path})
    if re.search(r"заблокируй (экран|компьютер)|блокировка", t):
        return Reply(say=S.lock_screen())

    # --- опасное: требует подтверждения ---
    if re.search(r"(выключи|отключи) (компьютер|комп|пк)|заверши работу", t):
        mins = _num(t, 0) if "через" in t else 0
        act = lambda: S.shutdown(mins)
        if confirm_needed:
            when = f" через {mins} минут" if mins else " прямо сейчас"
            return Reply(say=f"Выключить компьютер{when}? Скажи «да» для подтверждения.",
                         pending=act, pending_desc="выключение компьютера")
        return Reply(say=act())
    if re.search(r"перезагрузи (компьютер|комп|пк|систему)|ребут", t):
        if confirm_needed:
            return Reply(say="Перезагрузить компьютер? Скажи «да».",
                         pending=S.reboot, pending_desc="перезагрузка")
        return Reply(say=S.reboot())
    if re.search(r"(спящий режим|усни|уйди в сон|засыпай)", t):
        return Reply(say=S.sleep_pc())

    # --- задачи и график ---
    m = re.search(r"^(?:напомни|напомнить|поставь задачу|добавь задачу|запланируй)\s+(?:мне\s+)?(.+)$", t)
    if m:
        return Reply(say=memory.add_task(m.group(1), m.group(1)))
    if re.search(r"(какие|что) (у меня )?(задачи|планы|дела)|план на (день|сегодня)|что сегодня|мой график|расписание", t):
        if "завтра" in t:
            return Reply(say=memory.list_tasks("tomorrow"))
        if "недел" in t:
            return Reply(say=memory.list_tasks("week"))
        return Reply(say=memory.list_tasks("today"))
    m = re.search(r"^(?:выполнено|сделал|готово|отметь)\s+(.+)$", t)
    if m:
        return Reply(say=memory.complete_task(m.group(1)))

    # --- окна и рабочий стол ---
    if re.search(r"(какие|что за) окна|что (у меня )?открыто|список окон", t):
        return Reply(say=D.windows_report())
    m = re.search(r"^(?:переключись|перейди|переключи)\s+(?:на|в)\s+(.+)$", t)
    if m:
        return Reply(say=D.focus_window(m.group(1)))
    if re.search(r"сверни (все|всё)|покажи рабочий стол", t):
        return Reply(say=D.minimize_all())
    if re.search(r"^закрой окно$", t):
        return Reply(say=D.close_window())

    # --- браузер ---
    if re.search(r"нов(ая|ую) вкладк", t):
        return Reply(say=D.browser("new_tab"))
    if re.search(r"закрой вкладку", t):
        return Reply(say=D.browser("close_tab"))
    if re.search(r"(следующая|переключи) вкладк", t):
        return Reply(say=D.browser("next_tab"))
    if re.search(r"верни вкладку|восстанови вкладку", t):
        return Reply(say=D.browser("reopen_tab"))
    if re.search(r"^(листай|прокрути|мотай) вниз$|^ниже$", t):
        return Reply(say=D.browser("scroll_down"))
    if re.search(r"^(листай|прокрути|мотай) вверх$|^выше$", t):
        return Reply(say=D.browser("scroll_up"))
    if re.search(r"^(назад|вернись назад)$|страницу назад", t):
        return Reply(say=D.browser("back"))
    if re.search(r"^вперед$|страницу вперед", t):
        return Reply(say=D.browser("forward"))
    if re.search(r"обнови страницу|перезагрузи страницу", t):
        return Reply(say=D.browser("reload"))
    m = re.search(r"найди на странице\s+(.+)$", t)
    if m:
        return Reply(say=D.browser("find", m.group(1)))

    # --- telegram ---
    if re.search(r"(что в (телеграме|телеге)|непрочитанн|кто (мне )?писал|новые сообщения)", t):
        return Reply(say=TG.unread())
    m = re.search(r"^(?:что пишет|прочитай (?:чат )?(?:с )?|открой переписку с)\s+(.+)$", t)
    if m:
        return Reply(say=TG.read_chat(m.group(1).strip()))
    m = re.search(r"^(?:напиши|отправь)\s+(.+?)\s+(?:сообщение\s+)?(?:что\s+)?(.+)$", t)
    if m and TG.ready():
        who, msg = m.group(1).strip(), m.group(2).strip()
        desc, action = TG.prepare_send(who, msg)
        if desc is None:
            return Reply(say=action)
        return Reply(say=f"Точно {desc}? Скажи «да».", pending=action, pending_desc=desc)
    m = re.search(r"^(?:открой|зайди в|перейди в)\s+(?:чат|переписку)\s+(?:с\s+)?(.+)$", t)
    if m and TG.ready():
        return Reply(say=TG.open_chat(m.group(1).strip()))

    # --- вежливость ---
    if re.fullmatch(r"(привет|здравствуй|здорово|хай|доброе утро|добрый день|добрый вечер)", t):
        return Reply(say=f"Здравствуй. Чем помочь?")
    if re.fullmatch(r"(спасибо|благодарю|отлично|молодец)", t):
        return Reply(say="Рад стараться.")
    if re.fullmatch(r"(как дела|как ты|ты тут|ты здесь)", t):
        return Reply(say="Все системы в норме. Слушаю.")

    # правила не справились — пусть думает модель
    return Reply(to_llm=True)


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core import config
    config.setup_console()
    tests = [
        "Джарвис, который час",
        "открой ютуб", "запусти яндекс музыка", "громкость 30", "сделай потише",
        "поставь на паузу", "какие у меня задачи", "напомни мне позвонить маме завтра в 12",
        "запомни что я люблю чёрный кофе", "что ты помнишь про кофе",
        "статус системы", "выключи компьютер", "найди в интернете погода в москве",
        "расскажи анекдот про программистов",
    ]
    for q in tests:
        clean = strip_wake(normalize(q), config.CFG["wake_words"])
        r = handle(clean, config.CFG)
        mark = "→LLM" if r.to_llm else ("⚠ждёт да" if r.pending else "✓")
        print(f"{mark:8} «{q}»  ⇒  {r.say[:70]}")
