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
import os
import re
import sys
import time
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
from skills import diskspace as DS
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


# Неопределённая форма → повелительная: «можешь открыть ютуб» → «открой ютуб»
IMPERATIVE = {
    "открыть": "открой", "включить": "включи", "выключить": "выключи", "запустить": "запусти",
    "закрыть": "закрой", "сделать": "сделай", "поставить": "поставь", "найти": "найди",
    "показать": "покажи", "написать": "напиши", "отправить": "отправь", "напомнить": "напомни",
    "прочитать": "прочитай", "перезагрузить": "перезагрузи", "убавить": "убавь",
    "прибавить": "прибавь", "переключить": "переключи", "свернуть": "сверни", "засечь": "засеки",
    "запомнить": "запомни", "записать": "запиши", "посчитать": "посчитай", "перевести": "переведи",
    "скинуть": "скинь", "прислать": "пришли", "остановить": "останови", "заблокировать": "заблокируй",
    "удалить": "удали", "почистить": "почисти", "сказать": "скажи", "рассказать": "расскажи",
    "посмотреть": "включи", "послушать": "включи", "зайти": "зайди", "перейти": "перейди",
    "подключить": "подключи", "установить": "установи", "проверить": "проверь", "обновить": "обнови",
    "отложить": "отложи", "отметить": "отметь", "запланировать": "запланируй",
}
POLITE_LEAD = re.compile(
    r"^(?:(?:а|ну|так|слушай|эй|короче)\s+)*"
    r"(?:(?:ты\s+)?(?:можешь|сможешь|не\s+можешь|не\s+мог\s+бы|мог\s+бы|могла\s+бы|можно)(?:\s+ли)?"
    r"|(?:мне\s+)?(?:нужно|надо)|(?:я\s+)?(?:хочу|хотел\s+бы|хотела\s+бы)|давай)\s+(?:мне\s+)?")


def _polite(t: str) -> str:
    """Разговорную просьбу — в команду, которую понимают правила.

    Проверка 08.10.2026: «можешь открыть ютуб», «а открой-ка стим», «мне нужно
    открыть госуслуги» уходили модели (без сети — к отказу), «пожалуйста»
    попадало в название программы («хром пожалуйста»), а в дело — в текст
    («пожалуйста выпить таблетку»).
    """
    t = re.sub(r"\b(?:пожалуйста|плиз|будь\s+добр[аы]?|будь\s+другом|если\s+не\s+сложно)\b", " ", t)
    t = re.sub(r"\b(\w+)-ка\b", r"\1", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^(?:(?:а|ну|так|слушай|эй|короче|джарвис)\s+)+(?=\S)", "", t)   # «а открой стим»
    m = POLITE_LEAD.match(t)
    if m and t[m.end():]:
        nxt = t[m.end():].split(" ", 1)[0]
        # «давай доту» — это «запусти»; снимаем «давай», только когда за ним глагол
        if not (m.group(0).rstrip().endswith("давай") and nxt not in IMPERATIVE
                and nxt not in IMPERATIVE.values()):
            t = t[m.end():]                     # «можно погромче» → «погромче»
    verb, _, rest = t.partition(" ")
    if verb in IMPERATIVE:
        new = IMPERATIVE[verb]
        if verb in ("посмотреть", "послушать") and not re.search(
                r"ютуб|youtube|видео|ролик|клип|музык|песн|трек|фильм|сериал|мультик", rest):
            new = "покажи"                      # «хочу посмотреть погоду» — не «включи погоду»
        t = f"{new} {rest}".strip()
    return t


def _snooze_minutes(t: str, default: int = 10) -> int:
    """«на 15 минут» → 15, «на час» → 60, «на полчаса» → 30, без срока — 10."""
    if "полчаса" in t:
        return 30
    m = re.search(r"(\d+)\s*(мин|час)", t)
    if m:
        return int(m.group(1)) * (60 if m.group(2) == "час" else 1)
    return 60 if re.search(r"\bчас", t) else default


# Глаголы отложенной команды → как её сказать в срок: «включить» → «включи»
DO_VERBS = {"включи": "включи", "включить": "включи", "открой": "открой", "открыть": "открой",
            "запусти": "запусти", "запустить": "запусти", "поставь": "поставь", "поставить": "поставь",
            "выключи": "выключи", "выключить": "выключи", "закрой": "закрой", "закрыть": "закрой"}
DO_WHEN = (r"через\s+(?:полчаса|(?:\d+(?:[.,]\d+)?|полтора|полторы|пару|один|одну|два|две|три|"
           r"четыре|пять|десять|двадцать|тридцать|сорок|несколько)?\s*(?:минут\w*|мин|час\w*))"
           r"|(?:сегодня |завтра )?в\s+\d{1,2}[:.]\d{2}")
DO_FILLER = {"ты", "а", "ну", "можешь", "сможешь", "мог", "могла", "бы", "можно", "пожалуйста",
             "где-то", "гдето", "примерно", "около", "ли", "мне", "нам", "давай", "и"}


VERBS = (r"сделай|включи|открой|закрой|поставь|выключи|найди|запусти|прибавь|убавь|убери|сверни|"
         r"разверни|переключи|переключись|напомни|покажи|запиши|запомни|заблокируй|громче|тише|"
         r"останови|продолжи|отправь|напиши|пришли|скинь")
SPLIT = re.compile(rf"\s+(?:и|а потом|потом|затем|и потом|и ещё|и еще)\s+(?=(?:{VERBS})\b)")


def _site_key(target: str) -> str:
    """«хабра» → «хабр», «госуслугах» → «госуслуги»: сайт называют в падеже."""
    if target in S.SITES:
        return target
    for cut in (1, 2):
        stem = target[:-cut]
        for key in S.SITES:
            if len(stem) >= 3 and key.startswith(stem) and len(key) - len(stem) <= 2:
                return key
    return ""


def _open_target(target: str, site: bool = False) -> str:
    key = _site_key(target)
    if key or target.startswith("http") or ".com" in target or ".ru" in target:
        return S.open_site(key or target)
    if site:                                  # «открой сайт X», которого нет в списке, — найти его
        return S.search_web(f"{target} официальный сайт")
    return S.open_app(target)


def _split_commands(t: str):
    """«Включи музыку на ютубе и сделай погромче» → две команды.

    Проверка 08.10.2026: вторая половина целиком уходила в запрос YouTube, а
    «открой сайт хабра и найди статьи» искало программу с таким названием.
    «Открой телеграм и напиши …» — одна команда, у неё своё правило.
    """
    if re.match(r"^(?:открой|зайди в)\s+(?:телеграм\w*|телег\w*|тг)\s+и\s+(?:напиши|отправь)", t):
        return None
    parts = [p.strip() for p in SPLIT.split(t) if p.strip()]
    return parts if len(parts) > 1 else None


def _run_parts(parts, cfg) -> Reply:
    """Выполнить по очереди. Часть не по силам правилам — остаток целиком модели;
    часть просит «да» — спрашиваем, остальное не делаем вслепую."""
    said = []
    for i, part in enumerate(parts):
        r = handle(part, cfg)
        if r.to_llm:
            return Reply(say=" ".join(said), to_llm=True, meta={"llm_text": " и ".join(parts[i:])})
        if r.pending:
            rest = parts[i + 1:]
            tail = f" Потом скажи ещё раз: «{' и '.join(rest)}»." if rest else ""
            return Reply(say=" ".join(said + [r.say]) + tail, pending=r.pending,
                         pending_desc=r.pending_desc)
        if r.say:
            said.append(r.say)
    return Reply(say=" ".join(said) or "Сделано.")


def _deferred(t: str):
    """«Ты можешь через 1,5 часа включить видео на ютубе» — выполнить в срок.

    07.10.2026 хозяин попросил это с телефона, а Джарвис ответил «не получилось»:
    такого правила не было, а напоминание «Включить Just Dance» — не то, о чём
    просили. Сама команда в срок идёт обычным путём (jarvis._run_planned).
    Выключение и таймеры не трогаем: у них своё «через N минут».
    """
    m = re.search(DO_WHEN, t)
    if not m:
        return None
    words = (t[:m.start()] + " " + t[m.end():]).split()
    while words and words[0] in DO_FILLER:
        words.pop(0)
    while words and words[-1] in DO_FILLER:
        words.pop()
    if len(words) < 2 or words[0] not in DO_VERBS:
        return None
    command = " ".join([DO_VERBS[words[0]]] + words[1:])
    if re.search(r"компьютер|комп\b|пк\b|таймер|будильник|напомина", command):
        return None
    when = memory._parse_when(m.group(0))
    if not when:
        return None
    return Reply(say=memory.add_command(command, when))


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
ORDINALS = {"первое": 1, "первый": 1, "второе": 2, "второй": 2, "третье": 3, "третий": 3,
            "четвертое": 4, "четвёртое": 4, "пятое": 5, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5}
VIDEO = r"(?:видео|видос\w*|ролик\w*|клип\w*)"


def _video_and_tabs(t: str):
    """Видео на YouTube, плеер в браузере и вкладки. None — это не про них."""
    # «это не то», «следующее видео», «давай другое»
    if (re.search(rf"\bне то\b|^(?:давай |включи )?(?:следующ\w+|другое)(?:\s+{VIDEO})?$", t)
            or re.search(rf"следующ\w+\s+{VIDEO}", t)):
        if YT._last["items"] or re.search(VIDEO, t):
            return Reply(say=YT.play_next())

    # «включи первое видео», «включи самое второе», «номер три»
    m = re.search(r"(?:включи|поставь|давай|открой)\s+(?:самое\s+|самый\s+|номер\s+)?"
                  r"(первое|первый|второе|второй|третье|третий|четв[её]ртое|пятое|[1-5])\b", t)
    # «Открой второй» после поиска файлов — про файлы: видео берём, только если
    # про видео сказано прямо или видео искали позже файлов
    from skills import files as _F
    video_fresher = YT._last.get("at", 0) >= _F.last_at
    if m and (re.search(VIDEO, t) or (YT._last["items"] and video_fresher)):
        if not YT._last["items"]:
            return Reply(say="Списка ещё нет — скажи, что найти, и включу.")
        return Reply(say=YT.play_number(ORDINALS[m.group(1)]))

    # Плеер в браузере. «Поставь видео на паузу» — это пауза, а не поиск видео
    controls = [
        (rf"(останов\w*|стоп|пауз\w*|приостанов\w*)\s*(?:это\s+)?{VIDEO}|{VIDEO}\s+на\s+паузу|"
         rf"^(?:поставь\s+)?на\s+паузу$|^пауза$", "pause"),
        (rf"(продолж\w*|сними с паузы|сними\s+{VIDEO}\s+с\s+паузы)|^дальше$", "play"),
        (r"(разверн\w*|на весь экран|полный экран|во весь экран)", "fullscreen"),
        (rf"(заглуши|выключи звук (?:у |в )?){VIDEO}", "mute"),
        (r"перемот\w*\s+(?:на\s+\w+\s+)?вперед|вперёд на|промотай", "forward"),
        (r"перемот\w*\s+(?:на\s+\w+\s+)?назад|отмотай|назад на \d+", "back"),
        (r"субтитр", "captions"),
    ]
    # «Видео не остановилось», «до сих пор играет» — хозяин говорит, что не вышло.
    # Не спорим и не верим прошлому отчёту: пробуем снова, и video сам проверит по звуку
    if re.search(rf"(?:{VIDEO}|звук|музыка)\b.*(?:не останов\w*|не выключ\w*|"
                 r"(?:до сих пор|все еще|всё ещё|опять)\s+(?:идет|идёт|играет|звучит))", t):
        return Reply(say=D.video("pause"))
    for pattern, action in controls:
        if re.search(pattern, t):
            return Reply(say=D.video(action))

    # «открой видео Глеб Отис», «включи ролик про ракеты», «найди видео ...»
    m = re.search(rf"^(?:открой|включи|поставь|найди|покажи|запусти)\s+(?:мне\s+)?{VIDEO}\s+(.+)$", t)
    if m:
        # «на ютубе» — где искать, а не что: в запросе оно уводило поиск в сторону
        query = re.sub(r"\s*\b(?:на|в|с|из)\s+(?:ютубе?|youtube)\b\s*", " ", m.group(1)).strip()
        return Reply(say=YT.play_on_youtube(query or m.group(1)))

    # Вкладки браузера
    if re.search(r"(закрой|убери)\s+(эту\s+|текущую\s+)?вкладку", t):
        return Reply(say=D.browser("close_tab"))
    if re.search(r"(открой\s+)?нов\w+\s+вкладк\w*", t):
        return Reply(say=D.browser("new_tab"))
    if re.search(r"(следующ\w+|другая)\s+вкладк\w*|переключи вкладку", t):
        return Reply(say=D.browser("next_tab"))
    if re.search(r"верни\s+(закрыт\w+\s+)?вкладку", t):
        return Reply(say=D.browser("reopen_tab"))

    # «что сейчас играет» — по звуку, а не догадкой
    if re.search(r"что\s+(сейчас\s+)?(играет|звучит|за звук)|откуда звук", t):
        return Reply(say=S.who_sounds())
    return _ui_rules(t)


def _file_rules(t: str):
    """«Открой второй», «пришли его на телефон» — после поиска файлов.

    Если перед этим искали видео, «открой второй» — про видео (это ловит
    правило выше). Здесь — только когда файлы искали позже видео.
    """
    from skills import files as F
    if not F._last or F.last_at < YT._last.get("at", 0):
        return None
    n = None
    m = re.search(r"(первый|первое|второй|второе|третий|третье|четв[её]ртый|пятый|[1-5])\b", t)
    if m:
        n = ORDINALS.get(m.group(1).replace("ый", "ое").replace("ий", "ье").replace("ой", "ое"),
                         ORDINALS.get(m.group(1)))
    elif re.search(r"\b(его|её|ее|этот|этот файл|найденн\w+)\b", t):
        n = 1
    elif (re.fullmatch(r"(?:пришли|скинь|отправь|перешли)\s+(?:мне\s+)?(?:на телефон|в телеграм\w*|мне)", t)
          and time.time() - F.last_at < 180):
        n = 1                            # «сделай скриншот и пришли на телефон» — только что сделанное
    if n is None:
        return None
    if re.search(r"^(?:открой|запусти|покажи)\b", t):
        return Reply(say=F.open_found(n))
    if re.search(r"^(?:пришли|скинь|отправь|перешли)\b.*(?:телефон|телеграм|мне)", t):
        from core import phone
        p = phone.CURRENT
        if p and p.owner and F.last(n):
            return Reply(say=p.send_file(F.last(n)))
        return Reply(to_llm=True)        # телефона нет — пусть мозг честно скажет почему
    return None


def _ui_rules(t: str):
    """«Нажми …» и «что тут можно нажать» — руками по названию (skills/ui.py)."""
    reply = _file_rules(t)
    if reply:
        return reply
    # «Открой последний скачанный файл» раньше искало программу с таким названием
    if re.search(r"^(?:открой|покажи|запусти)\b.*\bпоследн\w*\b.*\b(?:скачан|загружен|закачан|загрузк)", t):
        from skills import files as F
        return Reply(say=F.latest_download())
    if re.search(r"\b(?:заряд\w*|батаре\w*|аккумулятор\w*)\b", t) and not re.search(r"\b(?:купи|закажи)\b", t):
        return Reply(say=S.battery())
    from skills import ui as UI
    if re.search(r"^что\s+(?:тут\s+|здесь\s+|в этом окне\s+)?можно\s+нажать|"
                 r"^какие\s+(?:тут\s+|здесь\s+|есть\s+)?кнопки|^что\s+(?:есть\s+)?в этом окне", t):
        return Reply(say=UI.elements_report())
    m = re.search(r"^(?:нажми|кликни|щелкни|щёлкни|ткни|жми)\s+(?:на\s+)?"
                  r"(?:кнопку\s+|пункт\s+|ссылку\s+|вкладку\s+|меню\s+)?(.+)$", t)
    if not m:
        return None
    target = m.group(1).strip()
    # Клавиши — не кнопки на экране
    if re.fullmatch(r"(?:на\s+)?паузу|пробел", target):
        return Reply(say=D.video("pause") if "пауз" in target else (D.press("space") and "Нажал пробел."))
    if re.fullmatch(r"эскейп|escape|esc|отмену", target):
        D.press("esc")
        return Reply(say="Нажал Escape.")
    if re.fullmatch(r"энтер|enter|ввод", target):
        # Enter в чате отправляет сообщение — отменить нельзя, поэтому через «да»
        return Reply(say="Нажать Enter? Если открыт чат, это отправит сообщение. Скажи «да».",
                     pending=lambda: (D.press("enter"), "Нажал Enter.")[1],
                     pending_desc="нажать Enter")
    el, found, extra, title = UI.find(target)
    if el is not None and UI.is_dangerous(found):
        return Reply(say=f"Нажать «{found}» в окне «{title[:40]}»? Это не отменить. Скажи «да».",
                     pending=lambda: UI.click(found), pending_desc=f"нажать «{found}»")
    return Reply(say=UI.click(target))


def handle(text: str, cfg: dict) -> Reply:
    t = _polite(normalize(text))
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
    if re.search(r"(который (сейчас )?час|сколько (сейчас )?времени|какое (сегодня )?число|"
                 r"какой сегодня день)", t):
        return Reply(say=S.what_time())

    # --- почему не работает умный режим: VPN выключен или сервер не тот (skills/netcheck.py) ---
    if re.search(r"^проверь\s+(?:связь|интернет|vpn|впн|умный режим|соединение)$|"
                 r"^(?:работает ли|что с)\s+(?:умн\w+ режим\w*|интернет\w*|vpn|впн)$|"
                 r"почему\s+(?:ты\s+)?(?:не работает умный режим|тупишь|глупый|отвечаешь попроще)", t):
        from skills import netcheck
        from core.brain import Brain
        return Reply(say=netcheck.check(Brain(cfg)))

    # --- отложенная команда: «через полтора часа включи видео» ---
    # Выше видео: иначе правило видео включило бы его сразу, а не через полтора часа
    reply = _deferred(t)
    if reply:
        return reply

    # --- несколько команд: «включи музыку на ютубе и сделай погромче» ---
    parts = _split_commands(t)
    if parts:
        return _run_parts(parts, cfg)

    # --- видео и вкладки ---
    # Стоит выше громкости и общих «открой X» / «закрой X». Замер 05.10.2026:
    # «включи самое первое видео» уходило искать ПРОГРАММУ с таким названием,
    # «закрой эту вкладку» — закрывать программу «эту вкладку», а «открой видео
    # Глеб Отис» — запускать приложение. Те же команды своя офлайн-модель
    # путала чаще всего, так что правило здесь надёжнее любого мозга.
    reply = _video_and_tabs(t)
    if reply:
        return reply

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
    # «сделай музыку потише», «звук погромче» — слово между «сделай» и «тише» раньше
    # ломало правило, и просьба уходила модели, которая отчитывалась без дела
    if re.search(r"^(?:сделай\s+)?(?:музыку|звук|видео|громкость)?\s*(?:по)?громче\b", t):
        return Reply(say=S.change_volume(+10))
    if re.search(r"^(?:сделай\s+)?(?:музыку|звук|видео|громкость)?\s*(?:по)?тише\b", t):
        return Reply(say=S.change_volume(-10))
    # «убавь звук», «прибавь громкость» — без числа: на 10
    if re.fullmatch(r"(?:убавь|уменьши|приглуши|снизь|понизь)\s+(?:звук|громкость|музыку)", t):
        return Reply(say=S.change_volume(-10))
    if re.fullmatch(r"(?:прибавь|увеличь|подними|повысь|добавь)\s+(?:звук|громкость|музыку)", t):
        return Reply(say=S.change_volume(+10))
    if re.search(r"(выключи|отключи|убери) звук|заглуши", t):
        return Reply(say=S.mute(True))
    if re.search(r"(включи|верни) звук", t):
        return Reply(say=S.mute(False))
    if re.search(r"какая громкость", t):
        return Reply(say=S.get_volume())

    # --- плеер ---
    if re.search(r"^(поставь на )?паузу$|^пауза$|^останови музыку", t):
        return Reply(say=S.media_key("pause"))
    if re.search(r"^(включи|продолжи|поставь|запусти) музыку$|^играй$", t):
        return Reply(say=S.media_key("play"))
    # «Спокойная музыка», «музыку для работы», «включи весёлую музыку» — найти на YouTube.
    # 09.10.2026 на «спокойная музыка» своя модель выключила звук
    m = re.fullmatch(r"(?:(?:включи|поставь|запусти|найди)\s+)?(?:мне\s+)?((?:какую-?нибудь\s+|что-?нибудь\s+)?"
                     r"(?:[а-яё]+(?:ая|ую|ой|ые|ую)\s+)?(?:музык[аиу]|песн[июя]|плейлист)"
                     r"(?:\s+(?:для|под|на|в)\s+.+)?)", t)
    if m and m.group(1) not in ("музыку", "музыка", "песню", "песни"):
        query = re.sub(r"^(?:какую-?нибудь|что-?нибудь)\s+", "", m.group(1))
        query = re.sub(r"\s+(?:на|в|с)\s+(?:ютубе?|youtube)$", "", query)
        return Reply(say=YT.play_on_youtube(query))
    # «Выключи музыку» — пауза плеера, а не закрыть программу «музыку»
    if re.fullmatch(r"(?:выключи|останови|убери|стоп)\s+(?:музыку|песню|трек|плеер)", t):
        return Reply(say=S.media_key("pause"))
    if re.fullmatch(r"(?:выключи|убери)\s+(?:видео|видос|ролик|клип)", t):
        return Reply(say=D.video("pause"))
    if re.search(r"следующ(ий|ая) (трек|песня|песню)|переключи (трек|песню)|дальше", t):
        return Reply(say=S.media_key("next"))
    if re.search(r"предыдущ(ий|ая) (трек|песня|песню)|назад трек", t):
        return Reply(say=S.media_key("prev"))

    # --- удалить программу или игру: только со словом «программу/игру» ---
    m = re.search(r"^(?:удали|удалить|снеси|деинсталлируй)\s+(?:программу|игру|приложение)\s+(.+)$", t)
    if m:
        from skills import programs as PR
        desc, action = PR.prepare(m.group(1))
        if desc is None:
            return Reply(say=action)
        return Reply(say=f"{desc[0].upper()}{desc[1:]}? Откроется окно удаления — там подтвердишь "
                         "ещё раз. Скажи «да».", pending=action, pending_desc=desc)

    # --- телефон: код привязки, если прослушал его при запуске ---
    if re.search(r"(подключ|привяз)\w*\s+(\w+\s+)?(телефон|бот)\w*|код\s+(для\s+|привязки\s+)?(телефон|бот)\w*", t):
        from core.phone import Phone
        return Reply(say=Phone.status_phrase())

    # --- место на диске и очистка ---
    # «Что занимает» — раньше общего «сколько места»: спрашивают не сколько, а куда ушло
    if re.search(r"(что|чем|кто)\s+(\w+\s+){0,2}(занима\w*|забит\w*|съел\w*|жр[её]т)\s*(\w+\s+){0,2}(мест\w*|диск\w*)"
                 r"|(что|чем)\s+(\w+\s+){0,2}мест\w*\s+(занима|съел|сожр)\w*"
                 r"|куда (делось|ушло|пропало) место|(чем|что) (забит|заполнен)\w* диск", t):
        return Reply(say=DS.report())
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
    # «посчитай в калькуляторе кнопками» — просьба нажимать, а не ответ: отдаём мозгу
    if m and not re.search(r"калькулятор|кнопк", t):
        return Reply(say=TL.calculate(m.group(1)))
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*процентов?\s+от\s+(\d+(?:[.,]\d+)?)", t)
    if m:
        return Reply(say=TL.calculate(t))

    m = re.search(r"курс\s+(\w+)", t)
    if m:
        return Reply(say=TL.exchange_rate(m.group(1)))
    m = re.search(r"сколько стоит\s+(доллар\w*|евро|юан\w*|биткоин\w*|биткойн\w*|фунт\w*|тенге|гривн\w*|"
                  r"эфир\w*|тон|солан\w*|догикоин\w*|bitcoin|btc|eth|ton|usdt)\b", t)
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
    # --- новости: настоящие заголовки, а не пересказ, которого модель не видела ---
    m = re.search(r"^(?:а\s+)?(?:какие|что за|расскажи|прочитай|скажи|давай|есть)?\s*(?:ещ[её]\s+)?"
                  r"(?:мне\s+)?(?:последние\s+|свежие\s+|главные\s+)?новост\w*"
                  r"(?:\s+(?:про|о|об|по)\s+(.+?))?(?:\s+(?:сегодня|дня|есть))?$", t)
    if m or re.fullmatch(r"что (?:нового|случилось)(?: в мире| в стране| сегодня)?|что в новостях", t):
        from skills import news
        return Reply(say=news.headlines(5, (m.group(1) or "") if m else ""))

    # «погода завтра», «какая завтра погода в казани», «погода на послезавтра в питере».
    # Раньше «погода завтра» не совпадало с правилом и уходило модели
    if re.search(r"\bпогод", t) and not re.search(r"\b(выходн|недел)", t):
        day = 2 if "послезавтра" in t else 1 if "завтра" in t else 0
        rest = re.sub(r"\b(?:на\s+)?(?:послезавтра|завтра|сегодня|сейчас)\b|\bна улице\b|\bбудет\b", " ", t)
        m = (re.search(r"\bв(?:о)?\s+(?:городе\s+)?([а-яёa-z-]+(?:\s+[а-яёa-z-]+)?)\s*$", rest.strip())
             or re.search(r"^в(?:о)?\s+(?:городе\s+)?([а-яёa-z-]+)\s+(?:какая|как|что)\b", rest.strip()))
        city = m.group(1).strip() if m else ""
        city = re.sub(r"\s*\bпогод\w*$", "", city)
        return Reply(say=W.weather(city, day))

    # --- таймер ---
    if re.search(r"(сколько (осталось|там|на таймере)|что с таймером|таймеры)", t):
        return Reply(say=memory.active_timers())

    m = (re.search(r"таймер\w*\s*(?:на\s*)?(\d+)\s*(секунд\w*|сек|минут\w*|мин|час\w*)?", t)
         or re.search(r"^засеки\s+(\d+)\s*(секунд\w*|сек|минут\w*|мин|час\w*)?$", t))
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
    m = re.search(r"^что ты (?:обо мне |про меня )?(?:помнишь|знаешь)\s*(?:про|о|об|обо)?\s*(.*)$", t)
    if m:
        about = m.group(1).strip()
        return Reply(say=memory.recall("" if about in ("мне", "меня", "обо мне") else about))
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

    # --- Telegram: выше общего «открой X», иначе «открой чат с Сашей» искал программу ---
    # «Открой телеграм и напиши Саше привет», «напиши в телеге Хомяк Туп что буду поздно».
    # Без входа в личный Telegram — через приложение на компьютере (skills/tg_desktop)
    m = re.search(r"^(?:(?:открой|зайди в)\s+(?:телеграм\w*|телег\w*|тг)\s+и\s+)?"
                  r"(?:напиши|отправь)\s+(.+)$", t)
    if m:
        rest = re.sub(r"\b(?:в|через)\s+(?:телеграм\w*|телег\w*|тг)\b|\bсообщение\b", " ", m.group(1))
        rest = re.sub(r"\s+", " ", rest).strip()
        if rest and not re.match(r"(?:мне|себе|на телефон|в блокнот|текст|письмо)\b", rest):
            from skills import tg_desktop as TGD
            who, msg = TGD.split_recipient(rest)
            if not who and TG.ready():
                who, _, msg = rest.partition(" ")
            if who and msg:
                desc, action = TG.prepare_send(who.strip(), msg.strip())
                if desc is None:
                    return Reply(say=action)
                return Reply(say=f"Точно {desc}? Скажи «да».", pending=action, pending_desc=desc)
    m = re.search(r"^(?:открой|зайди в|перейди в)\s+(?:чат|переписку)\s+(?:с\s+)?(.+)$", t) or \
        re.search(r"^(?:открой|зайди)\s+(?:в\s+)?(?:телеграм\w*|телег\w*|тг)\s+(?:чат\s+)?(?:с\s+)?(?!и\s)(.+)$", t)
    if m:
        return Reply(say=TG.open_chat(m.group(1).strip()))

    # --- папки, проекты и документы по имени (skills/files.py) ---
    # Раньше «открой папку jarvis» и «открой документ резюме» искали программу с таким названием
    m = re.search(r"^(?:открой|запусти)\s+(?:проект|папку)\s+(.+?)\s+в\s+(?:vs\s*code|вс\s*код\w*|vscode|"
                  r"визуал\s+студио(?:\s+код)?|код\w*)$", t)
    if m:
        from skills import files as F
        return Reply(say=F.open_in_code(m.group(1)))
    m = re.search(r"^(?:открой|покажи|зайди в)\s+(?:папку|проект)\s+(.+)$", t)
    if m and not (f"папку {m.group(1)}" in S.PLACES or m.group(1) in S.PLACES):
        from skills import files as F
        return Reply(say=F.open_folder(m.group(1)))
    m = re.search(r"^(?:открой|покажи)\s+((?:файл|документ|презентацию|таблицу|pdf|пдф)\s+.+)$", t)
    if m:
        from skills import files as F
        return Reply(say=F.open_document(re.sub(r"^файл\s+", "", m.group(1))))

    # --- программы и сайты ---
    m = re.search(r"^(?:открой|запусти|включи|врубай|давай|зайди\s+(?:в|на)|перейди\s+(?:в|на))\s+(.+)$", t)
    if m:
        target = m.group(1).strip()
        site = bool(re.match(r"(?:мне\s+)?сайт\s", target))
        target = re.sub(r"^(мне|пожалуйста|программу|приложение|сайт)\s+", "", target)
        # «включи первое» после поиска на YouTube — видео по номеру, а не программа «первое»
        if target in ORDINALS and YT._last.get("items"):
            return Reply(say=YT.play_number(ORDINALS[target]))
        # «открой блокнот и калькулятор» — две программы, а не одна с таким названием
        pieces = [p for p in re.split(r"\s+и\s+|\s*,\s*", target) if p]
        if len(pieces) > 1 and all(len(p.split()) <= 3 for p in pieces):
            return Reply(say=" ".join(_open_target(p, site) for p in pieces))
        return Reply(say=_open_target(target, site))

    m = re.search(r"^(?:закрой|выключи|убей|заверши)\s+(.+)$", t)
    if m:
        target = m.group(1).strip()
        # «Закрой все окна кроме телеграма» — как крестиком, после «да». Модель на
        # такое собирала PowerShell Stop-Process, а он убивает несохранённое
        mc = re.fullmatch(r"(?:все|всё)(?:\s+(?:окна|программы|приложения))?(?:\s+кроме\s+(.+))?", target)
        if mc:
            keep = [k for k in re.split(r"\s+и\s+|\s*,\s*", mc.group(1) or "") if k]
            desc, act = D.close_all_windows(keep)
            if desc is None:
                return Reply(say=act)
            return Reply(say=f"{desc[:1].upper() + desc[1:]}? Скажи «да».", pending=act, pending_desc=desc)
        if re.search(r"\b(?:кроме|все|всё)\b", target):
            return Reply(to_llm=True)
        # Компьютер и «заверши работу» — ниже, как выключение с «да». Раньше
        # «выключи компьютер через час» уходило сюда и искало программу
        # «компьютер через час», а «заверши работу» — программу «работу»
        if not re.match(r"(?:компьютер|комп|пк|ноутбук|ноут|систему|работу)\b", target):
            return Reply(say=S.close_app(target))

    if re.search(r"обнови (список )?программ", t):
        n = len(S.build_app_index(force=True))
        return Reply(say=f"Список обновлён, вижу {n} программ.")

    # --- обученная в Colab надстройка своей модели (skills/training.py) ---
    if re.search(r"^(?:подключи|установи|поставь|проверь)\s+(?:обученн\w+\s+модель|надстройку|"
                 r"дообученн\w+\s+модель|результат обучения)$", t):
        from skills import training
        return Reply(say=training.start_install())

    # --- обновление самого Джарвиса с GitHub (skills/update.py) ---
    if re.fullmatch(r"(?:проверь|есть ли|есть|какие)\s+(?:ли\s+)?обновлени\w*(?:\s+джарвиса)?", t):
        from skills import update as U
        return Reply(say=U.check())
    if re.fullmatch(r"обновись|обнови себя|обнови джарвиса|обновить джарвиса|установи обновлени\w*", t):
        from skills import update as U
        return Reply(say="Обновить Джарвиса до последней версии с GitHub? Ключи, память и настройки "
                         "останутся. Скажи «да».",
                     pending=lambda: U.apply(restart_after=6), pending_desc="обновление Джарвиса")

    # --- где искать: Яндекс или Google ---
    # Насовсем: «ищи через яндекс», «переключи поиск на гугл», «надо яндекс
    # активировать» (так хозяин и сказал 07.10.2026, а Джарвис в ответ лишь
    # открыл ya.ru и переспросил, что искать). Последний запрос повторяется там
    eng = r"(яндекс\w*|гугл\w*|google|yandex)"
    m = (re.search(rf"^(?:ищи|искать)\s+(?:всегда\s+)?(?:в|через)\s+{eng}$", t)
         or re.search(rf"(?:переключи\w*|смени\w*|поменяй|поставь)\s+(?:поиск\w*|поисковик\w*)\s+(?:на\s+)?{eng}", t)
         or re.search(rf"(?:активируй|активировать)\s+{eng}|{eng}\s+(?:активируй|активировать)", t)
         or re.search(rf"(?:через|в)\s+{eng}\s+(?:ищи|ищем|давай искать)", t))
    if m:
        return Reply(say=S.set_search_engine(S.engine_of(next(g for g in m.groups() if g))))
    # Разово: «найди в яндексе …», «найди … в гугле»; «найди это в яндексе» — прошлый запрос
    m = re.search(rf"^(?:найди|поищи|ищи|посмотри|загугли)\s+(?:в|через)\s+{eng}\s+(.+)$", t)
    if m:
        engine, q = S.engine_of(m.group(1)), m.group(2).strip()
    else:
        m = re.search(rf"^(?:найди|поищи|посмотри)\s+(.+?)\s+(?:в|через)\s+{eng}$", t)
        engine, q = (S.engine_of(m.group(2)), m.group(1).strip()) if m else ("", "")
    if m:
        if q in ("это", "то же", "то же самое", "его", "ее", "её") and S._last_search["query"]:
            q = S._last_search["query"]
        return Reply(say=S.search_web(q, engine))

    # --- поиск ---
    m = re.search(r"^(?:найди|поищи|загугли|погугли)\s+(?:в интернете\s+|в гугле\s+)?(.+)$", t)
    if m:
        q = m.group(1).strip()
        # «найди у меня файл с отчётом» — это диск, а не интернет: раньше «у меня»
        # перед словом «файл» ломало правило, и поиск уходил в Google
        mf = re.match(r"(?:у меня\s+|мне\s+|на компе\s+|на компьютере\s+)?(?:файл\w*|документ\w*|папк\w+)"
                      r"\s+(?:с\s+|про\s+|где\s+|под названием\s+)?(.+)", q)
        if mf:
            return Reply(say=S.find_file(mf.group(1)))
        return Reply(say=S.search_web(q))

    # --- система ---
    if re.search(r"(как дела с (компьютером|системой)|статус системы|загрузка|нагрузка|"
                 r"сколько (свободной )?(памяти|места|оперативк\w*|озу)|оперативк\w* свободн|"
                 r"свободн\w* (оперативк|памят))", t):
        return Reply(say=S.system_info())
    if re.search(r"(что жрет|что ест|тяжелые процессы|какие процессы)", t):
        return Reply(say=S.top_processes())
    if re.search(r"(сделай )?скриншот|сфотографируй экран|снимок экрана", t):
        path = S.screenshot()
        # Последний «найденный» файл — чтобы «пришли его на телефон» знало, что слать
        from skills import files as F
        if path and os.path.exists(str(path)):
            F._last, F.last_at = [(os.path.basename(path), str(path), time.time())], time.time()
        return Reply(say="Скриншот готов.", meta={"screenshot": path})
    if re.search(r"заблокируй (экран|компьютер)|блокировка", t):
        return Reply(say=S.lock_screen())

    # --- опасное: требует подтверждения ---
    if re.search(r"(выключи|отключи) (компьютер|комп|пк|ноутбук|ноут|систему)|заверши работу", t):
        # «через час» — 60 минут, а не «прямо сейчас»: цифр в нём нет, и раньше
        # выключение предлагалось немедленно
        mins = 0
        if "через" in t:
            from datetime import datetime
            now = datetime.now().replace(microsecond=0)
            at = memory._relative(t, now)
            mins = round((at - now).total_seconds() / 60) if at else _num(t, 0)
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
    # Сразу после звонка: «отложи на 15 минут», «готово» — про то, что прозвенело.
    # Нет недавнего напоминания — не наше, пусть разбирается модель
    if re.fullmatch(r"отложи(?: напоминание| это| его)?(?: (?:на|через) .+)?", t) and memory.last_rung():
        return Reply(say=memory.snooze(memory.last_rung()["id"], _snooze_minutes(t)))
    if (re.fullmatch(r"(?:я )?(?:сделал|сделала|сделано|готово|выполнено|выполнил|выполнила)(?: (?:это|уже))?", t)
            and memory.last_rung()):
        return Reply(say=memory.finish(memory.last_rung()["id"]))
    m = re.search(r"^(?:напомни|напомнить|поставь задачу|добавь задачу|запланируй)\s+(?:мне\s+)?(.+)$", t)
    if m:
        return Reply(say=memory.add_task(m.group(1), m.group(1)))
    # Вопрос о планах — любыми словами. 07.10.2026 «что у меня в планах» ушло
    # модели, а она в ту минуту была без сети: правило его просто не знало
    if (re.search(r"(какие|что) (у меня )?(задачи|планы|дела)|план на (день|сегодня)|что сегодня|"
                  r"мой график|расписание", t)
            or re.search(r"^(?:а |ну |так )?(?:что|какие|какой|есть ли|есть|покажи|расскажи|скажи|мои|"
                         r"у меня)\b.*\b(?:план\w*|дела|делам|задач\w*|запланирован\w*)\b", t)
            or re.fullmatch(r"(?:а |ну )?что (?:у меня )?(?:на |в )?(?:сегодня|завтра|неделе|неделю)"
                            r"(?: у меня)?(?: по планам| по делам)?", t)
            or re.fullmatch(r"(?:мои )?(?:планы|дела)(?: на .+)?", t)):
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
    # «прочитай чат с …» раньше не совпадало (пробел после «с» требовался дважды)
    m = re.search(r"^(?:что пишет|что написал[аи]?|прочитай\s+(?:чат|переписку|сообщения)(?:\s+(?:с|со|от))?|"
                  r"открой переписку с)\s+(.+)$", t)
    if m:
        return Reply(say=TG.read_chat(m.group(1).strip()))
    if re.search(r"^прочитай\b.*\b(?:странице|странички|экране|окне|сайте)\b|^что (?:там )?написано\b", t):
        from skills import ui as UI
        return Reply(say=UI.read_text(""))

    # --- вежливость ---
    if re.fullmatch(r"(привет|здравствуй|здорово|хай|доброе утро|добрый день|добрый вечер)", t):
        return Reply(say="Здравствуй. Чем помочь?")
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
