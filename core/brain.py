# -*- coding: utf-8 -*-
"""Мозг: Gemini + инструменты.

Модель здесь не просто болтает — она вызывает функции. «Открой мне то, чем я
вчера занимался, и поставь напоминание» превращается в цепочку реальных вызовов
на этом компьютере. Список инструментов внизу файла (TOOLS) — это ровно то,
что Джарвис умеет делать руками.

Сеть: IPv4 форсирован принудительно. На этой машине IPv6 отвечает таймаутами,
и без этого каждый запрос ждал бы впустую по 20 секунд.
"""
import base64
import re
import socket
import sys
from pathlib import Path

import requests
import urllib3.util.connection as urllib3_conn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config, memory
from skills import system as S
from skills import desktop as D
from skills import youtube as YT
from skills import telegram as TG
from skills import weather as W
from skills import cleanup as CL
from skills import tools as TL
from skills import lessons as LS

# --- лечим мёртвый IPv6: заставляем всё ходить по IPv4 ---
urllib3_conn.allowed_gai_family = lambda: socket.AF_INET

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

PERSONA = """Ты — Джарвис, личный ассистент. Говоришь по-русски, на «ты», если хозяин сам не перешёл на «вы».

Как ты себя ведёшь:
- Отвечаешь коротко. Твои ответы читаются вслух, поэтому никаких списков, разметки,
  markdown, эмодзи и скобок. Только живая речь, 1-3 предложения.
- Не пересказываешь, что собираешься сделать — просто делаешь через инструменты и
  докладываешь результат одной фразой.
- Числа пишешь словами там, где иначе синтезатор прочитает криво.
- Если не знаешь — говоришь прямо, без выдумок.
- Ты спокойный, слегка ироничный, но без клоунады. Как хороший дворецкий.

Инструменты вызывай сам, не спрашивая разрешения, кроме по-настоящему опасного —
удаления файлов, отправки сообщений наружу, выключения компьютера. Для такого
сначала уточни у хозяина словами.

"""

HONESTY = """Про результат инструмента — закон:
- Что инструмент вернул, то и правда. Вернул отказ или ошибку — так и скажи, что не
  получилось и почему. Никогда не говори «готово», «нажал», «закрыл», «остановил»,
  если инструмент этого не подтвердил.
- Не пытайся щёлкать по экрану через powershell — SendKeys и Shell.Application там
  запрещены, и попытка просто вернёт отказ. Нажать кнопку, пункт меню или ссылку —
  ui_click по названию; что вообще можно нажать — ui_elements. Для вкладок и
  прокрутки — browser, для видео — video, для окон — focus_window.
- Хозяин говорит, что не сработало, — поверь ему, а не своему прошлому отчёту.
  Проверь: who_sounds слышит, идёт ли звук, look_at_screen показывает экран. Сначала
  посмотри, потом отвечай.
- Одно и то же средство дважды подряд не пробуй. Не вышло — либо другой инструмент,
  либо честно скажи, что этого не умеешь.

Твои руки — ты управляешь компьютером почти как человек, не говори, что не умеешь:
- «Нажми мышкой» — это ui_click по названию кнопки или ссылки.
- Напечатать в программу («напиши в Claude …», «вбей в поиск …») — сначала
  focus_window на её окно, потом type_text. «Claude», «Cloud Code» — программа на
  компьютере, а не сайт. Enter type_text не нажимает — отправить просят отдельно.
- Что написано в окне — ui_read; что там можно нажать — ui_elements.
"""

# Закон отдельной константой: тот же текст берёт и живой режим (core/live.py).
# Раньше он был только здесь, и в живом разговоре — основном режиме — Джарвис
# по-прежнему говорил «остановил», не проверив
PERSONA = PERSONA + HONESTY



# Выбрано замером 13.09.2026 на командах ассистента с полным набором инструментов:
# 3.5-flash-lite — 4 из 4 верных вызовов при 2.3 с; 3.5-flash — 1 из 4 при 9.4 с
# и перегрузке; 2.5-flash числится в списке моделей, но отвечает «больше недоступна».
# Запасные подхватывают, когда основная перегружена: 503 у Google — не редкость.
DEFAULT_MODEL = "gemini-3.5-flash-lite"
FALLBACK_MODELS = ["gemini-flash-lite-latest", "gemini-3.1-flash-lite", "gemini-flash-latest"]

# Коды, при которых есть смысл попробовать другую модель, а не сдаваться:
# перегрузка, исчерпанный лимит конкретной модели, модель выведена из обращения
RETRYABLE = {429, 500, 503, 404}
PENDING_TTL = 120     # вопрос «делать ли?» без ответа дольше двух минут считается брошенным


class Brain:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        b = cfg.get("brain", {})
        self.model = b.get("model", DEFAULT_MODEL)
        self.fallbacks = [m for m in b.get("fallback_models", FALLBACK_MODELS) if m != self.model]
        self.max_history = b.get("max_history", 20)
        self.key = config.env("GEMINI_API_KEY")
        self.history = []
        self.pending_confirm = None      # (описание, функция)
        self.pending_at = 0.0            # когда задан вопрос; брошенный через PENDING_TTL не мешает
        self.last_model = None           # кто реально ответил — для журнала

    @property
    def ready(self) -> bool:
        return bool(self.key)

    # ---------- обращение к модели ----------
    def _post(self, payload: dict, timeout=45):
        """Основная модель, при перегрузке — запасные по очереди."""
        errors = []
        for model in [self.model] + self.fallbacks:
            try:
                r = requests.post(API.format(model=model), params={"key": self.key},
                                  json=payload, timeout=timeout)
            except requests.RequestException as e:
                errors.append(f"{model}: сеть ({e.__class__.__name__})")
                continue
            if r.status_code == 200:
                self.last_model = model
                return r.json()
            errors.append(f"{model}: {r.status_code}")
            # Опечатка в имени модели приходит как 400, а не 404 — это тоже про модель,
            # и запасная поможет. Прочие 400 и 403 — запрос или ключ: смена модели бесполезна.
            bad_model_name = r.status_code == 400 and "model" in r.text.lower()
            if r.status_code not in RETRYABLE and not bad_model_name:
                raise RuntimeError(f"{r.status_code}: {r.text[:300]}")
        raise RuntimeError("все модели недоступны — " + "; ".join(errors))

    def _system_block(self):
        ctx = memory.context_for_llm(dialog=True)     # с недавним разговором голосом и в Telegram
        text = PERSONA + (("\n\nПамять:\n" + ctx) if ctx else "")
        return {"parts": [{"text": text}]}

    def ask(self, user_text: str, image_path: str = None) -> str:
        """Спросить модель. Она может по дороге вызвать инструменты."""
        self.last_error = None               # по нему офлайн-мозг понимает, что пора ему
        if not self.ready:
            return ("Умный режим не подключён — нет ключа Gemini. "
                    "Простые команды я всё равно выполняю.")

        parts = [{"text": user_text}]
        if image_path and Path(image_path).exists():
            data = base64.b64encode(Path(image_path).read_bytes()).decode()
            parts.append({"inline_data": {"mime_type": "image/png", "data": data}})

        self.history.append({"role": "user", "parts": parts})
        self._trim()
        turn_start = len(self.history) - 1       # откуда начался этот разговорный ход

        from core.honesty import failed, false_claim, unbacked_claim
        failures, nudged = [], False         # отказы инструментов в этом ходе — для сторожа честности
        tools_called = 0                     # «нажимаю» без единого вызова — тоже неправда
        # До 10 витков: «посчитай кнопками 9 × 6» — это уже пять нажатий подряд, и
        # при прежних пяти витках на ответ хозяину места не оставалось (05.10.2026)
        for _ in range(10):
            payload = {
                "contents": self.history,
                "systemInstruction": self._system_block(),
                "tools": [{"function_declarations": TOOLS}],
                "generationConfig": {"temperature": 0.7, "maxOutputTokens": 400},
            }
            try:
                data = self._post(payload)
            except Exception as e:
                self.last_error = e
                # Недоделанный ход убираем целиком — вместе с вызовами инструментов,
                # если сбой случился на втором витке. Иначе в истории останется
                # вызов без ответа, и следующий запрос облако отвергнет как бессмыслицу
                del self.history[turn_start:]
                return f"Мозг недоступен: {e}"

            cand = (data.get("candidates") or [{}])[0]
            content = cand.get("content", {})
            parts_out = content.get("parts", [])
            if not parts_out:                    # пустой ход сломал бы историю
                return "Не понял, повтори?"
            self.history.append({"role": "model", "parts": parts_out})

            calls = [p["functionCall"] for p in parts_out if "functionCall" in p]
            if not calls:
                text = " ".join(p["text"] for p in parts_out if "text" in p).strip()
                correction = false_claim(text, failures) or unbacked_claim(text, tools_called)
                if correction and not nudged:
                    # «Сделал» вопреки отказу инструмента — один раз просим ответить честно
                    nudged = True
                    self.history.append({"role": "user", "parts": [{"text": correction}]})
                    continue
                if not text:
                    return f"Не получилось: {failures[-1][1]}" if failures else "Готово."
                return text

            responses = []
            tools_called += len(calls)
            for call in calls:
                result = self._run_tool(call.get("name", ""), call.get("args", {}) or {})
                if failed(result):
                    failures.append((call.get("name", ""), result[:160]))
                responses.append({"functionResponse": {
                    "name": call.get("name", ""),
                    "response": {"result": result},
                }})
            self.history.append({"role": "user", "parts": responses})

        return "Слишком много шагов, остановился."

    # ---------- исполнение инструментов ----------
    def _run_tool(self, name: str, args: dict) -> str:
        # В журнал — и вызов, и ответ. Живой режим и своя модель это писали, а
        # обычный мозг нет: разбирать, почему он «не смог открыть калькулятор»,
        # приходилось вслепую (05.10.2026)
        from core import log
        import time
        before = self.pending_confirm
        try:
            fn = TOOL_IMPL.get(name)
            result = f"нет такого инструмента: {name}" if not fn else str(fn(self, **args))
        except Exception as e:
            result = f"ошибка инструмента {name}: {type(e).__name__}: {e}"
        # Одно опасное действие за раз. 07.10.2026 на «почисти диск и удали Far Cry»
        # второй запрос подтверждения затёр первый: на «да» выполнилось одно
        # удаление, очистка пропала молча, а модель сказала «диск почистил»
        if self.pending_confirm is not before and self.pending_confirm is not None:
            if before is not None and time.time() - self.pending_at < PENDING_TTL:
                self.pending_confirm = before
                result = (f"НЕ ПРИНЯТО: хозяин ещё не ответил про «{before[0]}». Сначала спроси об "
                          "этом и дождись ответа; это действие предложи после.")
            else:
                self.pending_at = time.time()
        log.write("tool", f"{name} {args} → {result[:100]}")
        return result

    def _trim(self):
        """Укоротить историю, не разрывая обмен с инструментами.

        Показ 02.10.2026: мозг отвалился с «function call turn comes immediately
        after a user turn» посреди разговора. Обрезка по последним N ходам резала
        где попало, и история начиналась с ответа инструмента без вопроса —
        для API это бессмыслица. Теперь лишнее отрезается только до обычного
        вопроса хозяина: пара «вызов инструмента — его ответ» остаётся целой.
        """
        def plain_user(turn):
            return turn.get("role") == "user" and not any(
                "functionResponse" in part for part in turn.get("parts", []))

        while len(self.history) > self.max_history:
            del self.history[0]
            while self.history and not plain_user(self.history[0]):
                del self.history[0]

    def reset(self):
        self.history = []


# ================= реализация инструментов =================
DANGEROUS_PS = ("remove-item", "del ", "rm ", "format", "shutdown", "stop-computer",
                "restart-computer", "set-executionpolicy", "reg delete", "diskpart",
                "clear-content", "uninstall", "invoke-webrequest", "curl ", "wget ")


def _t_open_app(b, name: str):
    return S.open_app(name)


def _t_close_app(b, name: str):
    return S.close_app(name)


def _t_open_site(b, site: str):
    return S.open_site(site)


def _t_web_search(b, query: str):
    # 08.10.2026 после поиска «какие новости» модель сказала «в мире всё спокойно»:
    # страницу поиска она не видит, это была выдумка. Говорим ей об этом прямо
    return (S.search_web(query) + ". Поиск открыт в браузере хозяина; результатов ты не видишь — "
            "не пересказывай и не придумывай их, просто скажи, что открыл.")


def _t_volume(b, level: int = None, change: int = None, mute: bool = None,
              percent: int = None, action: str = None):
    """Громкость. Точный уровень всегда важнее направления.

    Живой тест 15.09.2026: на «громкость 30» модель передала сразу percent=30 и
    action="up", старый код увидел «up» и прибавил 15 — вышло 65. Поэтому
    параметры разведены по смыслу: level — поставить ровно столько, change —
    изменить на столько. Старые percent/action понимаются так же.
    """
    if mute is not None:
        return S.mute(bool(mute))
    if action in ("mute", "unmute"):
        return S.mute(action == "mute")
    if level is None and percent is not None:
        level = percent
    if level is not None:
        return S.set_volume(int(level))
    if change is not None:
        return S.change_volume(int(change))
    if action in ("up", "down"):
        return S.change_volume(10 if action == "up" else -10)
    return S.get_volume()


def _t_media(b, action: str):
    return S.media_key(action)


def _t_system_status(b):
    return S.system_info() + " " + S.top_processes(3)


def _t_remember(b, text: str):
    return memory.remember(text)


def _t_recall(b, query: str = ""):
    return memory.recall(query)


def _t_add_task(b, text: str, when: str = ""):
    return memory.add_task(text, when or text)


def _t_list_tasks(b, period: str = "today"):
    return memory.list_tasks(period)


def _t_complete_task(b, text: str):
    return memory.complete_task(text)


def _t_note(b, text: str):
    return memory.add_note(text)


def _t_search_notes(b, query: str):
    return memory.search_notes(query)


def _t_look_at_screen(b, question: str = "Что на экране?"):
    """Зрение: делает скриншот и сам же его рассматривает отдельным запросом."""
    path = S.screenshot()
    if not b.ready:
        return "нет ключа для зрения"
    # Полный PNG экрана весит мегабайты и уходил секундами (на живом тесте «что на
    # мониторе» заняло 9 с). Текст на экране читается и в 1600 px JPEG.
    import io
    from PIL import Image
    img = Image.open(path).convert("RGB")
    img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    data = base64.b64encode(buf.getvalue()).decode()
    payload = {
        "contents": [{"role": "user", "parts": [
            {"text": "Опиши кратко и по делу, одним-двумя предложениями: " + question},
            {"inline_data": {"mime_type": "image/jpeg", "data": data}},
        ]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 200},
    }
    try:
        d = b._post(payload)
        return " ".join(p.get("text", "") for p in
                        d["candidates"][0]["content"]["parts"]).strip()
    except Exception as e:
        return f"не смог рассмотреть экран: {e}"


def _t_find_file(b, pattern: str, where: str = None):
    from skills import files as F
    return F.report(pattern)


def _t_open_file(b, number: int = 1):
    from skills import files as F
    return F.open_found(int(number or 1))


def _t_send_file(b, number: int = 1):
    """Найденный файл — в Telegram хозяину. Работает, только если подключён телефон."""
    from skills import files as F
    path = F.last(int(number or 1))
    if not path:
        return "Сначала найдём файл — скажи, какой."
    phone = getattr(b, "phone", None)
    if phone is None:
        return "Телефон не подключён: нужен токен бота от @BotFather в config/.env."
    return phone.send_file(path)


def _t_clipboard(b, action: str = "get", text: str = ""):
    return S.clipboard_get() if action == "get" else S.clipboard_set(text)


# PowerShell без подтверждения — только чтение, по белому списку.
#
# Раньше было наоборот: чёрный список опасных слов (remove-item, shutdown…).
# Живой тест 14.09.2026 показал, чего он стоит: модель не смогла отправить
# сообщение инструментом с подтверждением и обошла его сама — нажимала клавиши
# в окне Telegram через WScript.Shell.SendKeys. Два сообщения ушли без спроса.
# Чёрный список всегда проигрывает изобретательности, поэтому теперь свободно
# выполняются только простые конвейеры из читающих команд, а всё прочее —
# нажатия клавиш, COM-объекты, вызовы методов, запись в файлы, псевдонимы —
# только после «да» голосом.
SAFE_PS = {
    "test-path", "measure-object", "select-object", "where-object", "sort-object",
    "group-object", "format-table", "format-list", "format-wide", "out-string",
    "convertto-json", "convertto-csv", "resolve-path", "split-path", "join-path",
    "select-string", "write-output",
}
SAFE_PS_VERBS = ("get-",)                       # Get-Process, Get-ChildItem, Get-Volume…
# Опасное внутри в остальном безобидной строки: вызов метода объекта
# (.Kill(), .Delete()), статический вызов [Type]::, подвыражение $( ), вызов
# команды по имени &, перенаправление в файл >, COM и .NET объекты
PS_RISKY = re.compile(r"\.\s*\w+\s*\(|::|\$\(|&|>|<|\bnew-object\b|-comobject|"
                      r"\binvoke-|\biex\b|\bstart-process\b|`", re.I)


def ps_is_read_only(command: str) -> bool:
    if PS_RISKY.search(command):
        return False
    # Каждый сегмент конвейера и каждая команда после «;» должны начинаться
    # с читающего командлета — полное имя, не псевдоним вроде rm или kill
    for segment in re.split(r"[|;\n]", command):
        seg = segment.strip().lstrip("({ ").strip()
        if not seg:
            continue
        first = seg.split()[0].lower()
        if first.startswith("$_") or first in ("}", ")"):
            continue                              # продолжение фильтра Where-Object { $_… }
        if not (first in SAFE_PS or first.startswith(SAFE_PS_VERBS)):
            return False
    return True


def _t_powershell(b, command: str, reason: str = ""):
    """Полный доступ к системе. Всё, кроме чтения, — только после «да» голосом."""
    import subprocess

    def run():
        p = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                           capture_output=True, text=True, timeout=60)
        out = (p.stdout or p.stderr or "").strip()
        return out[:1500] if out else "выполнено, вывода нет"

    confirm = b.cfg.get("safety", {}).get("confirm_destructive", True)
    if confirm and not ps_is_read_only(command):
        what = reason.strip() or command[:90]
        b.pending_confirm = (f"выполнить на компьютере: {what}", run)
        return (f"ТРЕБУЕТСЯ ПОДТВЕРЖДЕНИЕ. Это не просто чтение, а действие: {what}. "
                "Объясни хозяину простыми словами, что сделаешь, без кода, и спроси «делать?».")
    try:
        return run()
    except Exception as e:
        return f"ошибка: {e}"


def _t_time(b):
    return S.what_time()


TOOL_IMPL = {
    "open_app": _t_open_app, "close_app": _t_close_app, "open_site": _t_open_site,
    "web_search": _t_web_search, "volume": _t_volume, "media": _t_media,
    "system_status": _t_system_status, "remember": _t_remember, "recall": _t_recall,
    "add_task": _t_add_task, "list_tasks": _t_list_tasks, "complete_task": _t_complete_task,
    "note": _t_note, "search_notes": _t_search_notes, "look_at_screen": _t_look_at_screen,
    "find_file": _t_find_file, "clipboard": _t_clipboard, "powershell": _t_powershell,
    "open_file": _t_open_file, "send_file": _t_send_file,
    "current_time": _t_time,
}


def _p(**props):
    return {"type": "object", "properties": props}


TOOLS = [
    {"name": "open_app", "description": "Запустить установленную программу по названию",
     "parameters": _p(name={"type": "string", "description": "название программы"})},
    {"name": "close_app", "description": "Закрыть запущенную программу",
     "parameters": _p(name={"type": "string"})},
    {"name": "open_site", "description": "Открыть сайт в браузере",
     "parameters": _p(site={"type": "string", "description": "адрес или название: ютуб, гитхаб"})},
    {"name": "web_search",
     "description": ("Открыть поиск в браузере хозяина — в Яндексе или Google, как он выбрал. "
                     "Только когда он прямо просит поискать или открыть в браузере. На вопросы, "
                     "ответ на которые знаешь, отвечай сам, ничего не открывая."),
     "parameters": _p(query={"type": "string"})},
    {"name": "volume",
     "description": ("Громкость системы. «Громкость 30», «сделай 30», «убавь до 30» — level=30. "
                     "«Тише на 20» — change=-20, «громче на 10» — change=10. Просто «потише» или "
                     "«погромче» без числа — change=-10 или 10. «Выключи звук» — mute=true. "
                     "Узнать текущую — без параметров. Level и change вместе не передавай."),
     "parameters": _p(level={"type": "integer", "description": "поставить ровно этот уровень, 0-100"},
                      change={"type": "integer", "description": "изменить на столько: -30 тише, 20 громче"},
                      mute={"type": "boolean", "description": "true — выключить звук, false — включить"})},
    {"name": "media",
     "description": ("Глобальные мультимедийные клавиши — для Spotify и прочих плееров. "
                     "Для видео в браузере НЕ годится, там инструмент video"),
     "parameters": _p(action={"type": "string", "description": "play, pause, next, prev, stop"})},
    {"name": "system_status", "description": "Загрузка процессора, памяти, места на дисках", "parameters": _p()},
    {"name": "current_time", "description": "Текущие дата и время", "parameters": _p()},
    {"name": "remember", "description": "Запомнить факт о хозяине навсегда",
     "parameters": _p(text={"type": "string"})},
    {"name": "recall", "description": "Вспомнить, что известно по теме",
     "parameters": _p(query={"type": "string"})},
    {"name": "add_task", "description": "Добавить задачу или напоминание в график",
     "parameters": _p(text={"type": "string"},
                      when={"type": "string", "description": "завтра в 15, через 20 минут"})},
    {"name": "list_tasks", "description": "Показать задачи",
     "parameters": _p(period={"type": "string", "description": "today, tomorrow, week, all"})},
    {"name": "complete_task", "description": "Отметить задачу выполненной",
     "parameters": _p(text={"type": "string"})},
    {"name": "note", "description": "Записать мысль в дневник заметок",
     "parameters": _p(text={"type": "string"})},
    {"name": "search_notes", "description": "Поиск по заметкам",
     "parameters": _p(query={"type": "string"})},
    {"name": "look_at_screen",
     "description": ("Посмотреть на экран хозяина и ответить, что там. Работает несколько "
                     "секунд — вызывай, только когда вопрос про то, что сейчас на экране."),
     "parameters": _p(question={"type": "string"})},
    {"name": "find_file",
     "description": ("Найти файл на всех дисках по словам из названия или папки: «отчёт за "
                     "сентябрь», «презентацию лцт», «readme джарвиса». Слова о типе («таблицу», "
                     "«фото», «презентацию») сужают поиск. Возвращает пронумерованный список"),
     "parameters": _p(pattern={"type": "string", "description": "слова, как сказал хозяин"},
                      where={"type": "string"})},
    {"name": "open_file",
     "description": "Открыть файл из последнего поиска по номеру: «открой второй» — number=2",
     "parameters": _p(number={"type": "integer"})},
    {"name": "send_file",
     "description": ("Прислать файл из последнего поиска хозяину в Telegram по номеру — «пришли "
                     "его на телефон», «скинь мне первый». Если телефон не подключён, инструмент "
                     "так и скажет"),
     "parameters": _p(number={"type": "integer"})},
    {"name": "clipboard", "description": "Прочитать или записать буфер обмена",
     "parameters": _p(action={"type": "string", "description": "get или set"},
                      text={"type": "string"})},
    {"name": "powershell",
     "description": ("Выполнить команду PowerShell на компьютере. Через это можно всё: "
                     "файлы, папки, процессы, сеть, настройки. Не спрашивай разрешения заранее: "
                     "всё, кроме чтения, инструмент сам вернёт на подтверждение. Никогда не "
                     "управляй программами нажатием клавиш (SendKeys): для окон, браузера и "
                     "Telegram есть свои инструменты. В reason коротко и по-человечески "
                     "напиши, что команда сделает."),
     "parameters": _p(command={"type": "string"},
                      reason={"type": "string", "description": "зачем это нужно"})},
]


def _t_windows(b):
    return D.windows_report()


def _t_focus_window(b, name: str):
    return D.focus_window(name)


def _t_browser(b, action: str, text: str = ""):
    return D.browser(action, text)


def _t_type_text(b, text: str):
    return D.type_text(text)


def _t_youtube_stats(b, channel: str = None):
    return YT.channel_stats(channel)


def _t_youtube_latest(b, channel: str = None):
    return YT.latest_videos(channel)


def _t_youtube_play(b, query: str = "", number: int = 0, next: bool = False):
    if next:
        return YT.play_next()
    if number:
        return YT.play_number(number)
    return YT.play_on_youtube(query)


def _t_youtube_search(b, query: str):
    return YT.search_titles(query)


def _t_video(b, action: str):
    return D.video(action)


def _t_who_sounds(b):
    return S.who_sounds()


def _t_ui_elements(b, window: str = ""):
    from skills import ui as UI
    return UI.elements_report(window)


def _t_ui_read(b, window: str = ""):
    from skills import ui as UI
    return UI.read_text(window)


def _t_ui_click(b, name: str, window: str = ""):
    """Нажать по названию. Кнопки «отправить», «удалить», «оплатить» — через «да»."""
    from skills import ui as UI
    el, found, extra, title = UI.find(name, window)
    if el is not None and UI.is_dangerous(found):
        b.pending_confirm = (f"нажать «{found}» в окне «{title[:40]}»",
                             lambda: UI.click(found, window))
        return (f"ТРЕБУЕТСЯ ПОДТВЕРЖДЕНИЕ: кнопка «{found}» в окне «{title[:40]}» — действие, "
                "которое не отменить. Спроси хозяина одной фразой, нажимать ли.")
    return UI.click(name, window)


def _t_tg_unread(b):
    return TG.unread()


def _t_tg_read(b, chat: str, n: int = 5):
    return TG.read_chat(chat, n)


# Как модель называет самого хозяина получателем: «@me» — так на живом разговоре
# 07.10.2026, и этот вызов уходил в личный Telegram (не подключён) вместо бота
OWNER_CHATS = {"me", "мне", "себе", "я", "мой", "хозяин", "хозяину", "избранное",
               "saved messages", "телефон", "мой телефон", "на телефон", "бот", "джарвис", "jarvis"}


def _to_owner(b, chat: str) -> bool:
    c = (chat or "").strip().lower().lstrip("@")
    me = (getattr(getattr(b, "phone", None), "me", "") or "").lower()
    return c in OWNER_CHATS or bool(me and c == me)


def _t_tg_send(b, chat: str, text: str):
    """Отправка наружу — всегда через подтверждение хозяина, без исключений.

    Кроме самого хозяина: «напиши мне в телеграм» уходит через бота Джарвиса
    сразу — это его же телефон, подтверждать нечего.
    """
    if _to_owner(b, chat):
        phone = getattr(b, "phone", None)
        if not (phone and phone.available and phone.owner):
            return ("НЕ ОТПРАВЛЕНО: телефон не подключён — нет бота или он ещё не знает хозяина. "
                    "Скажи это честно; как подключить — спросят «как подключить телефон».")
        if phone.send(text):
            return f"Отправил хозяину в Telegram{' (бот @' + phone.me + ')' if phone.me else ''}: «{text[:120]}»."
        return "НЕ ОТПРАВЛЕНО: Telegram не принял сообщение (нет связи?). Скажи это честно."
    desc, action = TG.prepare_send(chat, text)
    if desc is None:
        return action                                   # не подключён или чат не найден
    b.pending_confirm = (desc, action)
    return (f"ТРЕБУЕТСЯ ПОДТВЕРЖДЕНИЕ: {desc}. Назови хозяину получателя именно так и текст, "
            "спроси «отправить?».")


def _t_tg_open(b, chat: str):
    return TG.open_chat(chat)


TOOL_IMPL.update({
    "windows": _t_windows, "focus_window": _t_focus_window, "browser": _t_browser,
    "video": _t_video, "who_sounds": _t_who_sounds,
    "ui_elements": _t_ui_elements, "ui_click": _t_ui_click, "ui_read": _t_ui_read,
    "type_text": _t_type_text, "youtube_stats": _t_youtube_stats,
    "youtube_latest": _t_youtube_latest, "youtube_play": _t_youtube_play,
    "youtube_search": _t_youtube_search, "telegram_unread": _t_tg_unread,
    "telegram_read": _t_tg_read, "telegram_send": _t_tg_send,
    "telegram_open_chat": _t_tg_open,
})

TOOLS += [
    {"name": "windows", "description": "Какие окна сейчас открыты", "parameters": _p()},
    {"name": "focus_window", "description": "Переключиться на окно программы",
     "parameters": _p(name={"type": "string"})},
    {"name": "browser",
     "description": ("Управлять уже открытым браузером хозяина (с его сессиями и логинами). "
                     "action: new_tab, close_tab, next_tab, back, forward, reload, "
                     "scroll_down, scroll_up, top, goto, find, type"),
     "parameters": _p(action={"type": "string"},
                      text={"type": "string", "description": "адрес для goto или текст для find/type"})},
    {"name": "type_text",
     "description": ("Напечатать текст в активное окно, без Enter. Не для мессенджеров: "
                     "сообщения в Telegram — только через telegram_send."),
     "parameters": _p(text={"type": "string"})},
    {"name": "youtube_stats", "description": "Статистика YouTube-канала",
     "parameters": _p(channel={"type": "string", "description": "@handle, пусто — свой канал"})},
    {"name": "youtube_latest", "description": "Последние ролики канала и их просмотры",
     "parameters": _p(channel={"type": "string"})},
    {"name": "youtube_play",
     "description": ("Включить видео на YouTube. ЕДИНСТВЕННЫЙ правильный способ: находит "
                     "видео и открывает прямо страницу просмотра, оно сразу играет. "
                     "Не открывай видео через open_site и не пытайся нажимать по "
                     "результатам поиска — так не работает. Если хозяин говорит «не то» "
                     "или «следующее» — вызови с next=true, поиск не повторяй. "
                     "«Включи второе» — number=2"),
     "parameters": _p(query={"type": "string", "description": "что искать"},
                      next={"type": "boolean", "description": "включить следующий вариант"},
                      number={"type": "integer", "description": "номер из показанного списка"})},
    {"name": "youtube_search",
     "description": ("Показать названия вариантов, чтобы хозяин выбрал сам. Годится, когда "
                     "описание расплывчатое. Потом youtube_play с number"),
     "parameters": _p(query={"type": "string"})},
    {"name": "video",
     "description": ("Управлять видео, которое играет в браузере: pause, play, stop, mute, "
                     "fullscreen, theater, forward, back, next, prev, captions. Используй "
                     "это, а не media: инструмент выводит браузер вперёд, нажимает клавишу "
                     "самого YouTube и ПРОВЕРЯЕТ по звуку, получилось ли. Что он вернул — "
                     "то и есть правда"),
     "parameters": _p(action={"type": "string"})},
    {"name": "who_sounds",
     "description": ("Что сейчас звучит на компьютере — по уровню звука приложений. "
                     "Так можно проверить, играет ли видео, вместо того чтобы догадываться"),
     "parameters": _p()},
    {"name": "ui_click",
     "description": ("Нажать кнопку, пункт меню, ссылку или вкладку по её названию в любой "
                     "программе или на странице в браузере — как это сделал бы человек мышью. "
                     "Это ЕДИНСТВЕННЫЙ способ что-то нажать: не пытайся щёлкать через powershell. "
                     "Работает и для ссылок ниже края экрана. Не знаешь точного названия — сначала "
                     "ui_elements. window — часть заголовка окна, если нужно не активное"),
     "parameters": _p(name={"type": "string", "description": "название кнопки или ссылки"},
                      window={"type": "string", "description": "часть заголовка окна, необязательно"})},
    {"name": "ui_elements",
     "description": ("Что можно нажать в окне: кнопки, меню, ссылки, вкладки, поля — по названиям. "
                     "Это «глаза» без камеры: работает без интернета и быстрее look_at_screen"),
     "parameters": _p(window={"type": "string", "description": "часть заголовка окна, необязательно"})},
    {"name": "ui_read",
     "description": ("Прочитать текст в окне: видимую часть страницы в браузере, текст в блокноте, "
                     "подписи в программе. Для «что тут написано», «прочитай», «о чём статья». "
                     "Без интернета и мгновенно; look_at_screen — только если важны картинки"),
     "parameters": _p(window={"type": "string", "description": "часть заголовка окна, необязательно"})},
    {"name": "telegram_unread", "description": "Непрочитанные сообщения в Telegram", "parameters": _p()},
    {"name": "telegram_read", "description": "Прочитать переписку с человеком",
     "parameters": _p(chat={"type": "string"}, n={"type": "integer"})},
    {"name": "telegram_open_chat",
     "description": ("Открыть чат в приложении Telegram на компьютере по его названию. "
                     "Ничего не отправляет. Единственный правильный способ переключить чат."),
     "parameters": _p(chat={"type": "string", "description": "название чата или имя человека"})},
    {"name": "telegram_send",
     "description": ("Отправить сообщение в Telegram. chat='me' — самому хозяину на телефон через "
                     "бота Джарвиса (напоминание, список, ссылка): уходит сразу. Другим людям — "
                     "вызывай сразу, не спрашивая заранее: инструмент сам вернёт запрос на "
                     "подтверждение с текстом и получателем."),
     "parameters": _p(chat={"type": "string"}, text={"type": "string"})},
]



def _t_weather(b, city: str = ""):
    return W.weather(city)


def _t_timer(b, minutes: float, label: str = ""):
    return memory.add_timer(minutes, label)


def _t_timers_left(b):
    return memory.active_timers()


TOOL_IMPL.update({
    "weather": _t_weather, "timer": _t_timer, "timers_left": _t_timers_left,
})

TOOLS += [
    {"name": "weather", "description": "Погода сейчас и на сегодня",
     "parameters": _p(city={"type": "string", "description": "город; пусто — запомненный"})},
    {"name": "timer", "description": "Поставить таймер",
     "parameters": _p(minutes={"type": "number"},
                      label={"type": "string", "description": "на что таймер"})},
    {"name": "timers_left", "description": "Сколько осталось на таймерах", "parameters": _p()},
]



def _t_disk(b):
    # Сколько свободно — и сразу куда ушло: «сколько места» спрашивают, когда его мало
    from skills import diskspace as DS
    return CL.disk_report() + " " + DS.report(with_free=False)


def _t_clean_preview(b):
    return CL.clean(dry_run=True)


def _t_clean(b):
    """Очистка — удаление, поэтому только через подтверждение хозяина."""
    if b.cfg.get("safety", {}).get("confirm_destructive", True):
        b.pending_confirm = ("очистить диск от временных файлов", CL.clean)
        return ("ТРЕБУЕТСЯ ПОДТВЕРЖДЕНИЕ. Скажи хозяину, сколько освободится, "
                "и попроси подтвердить словом «да». Оценка: " + CL.clean(dry_run=True))
    return CL.clean()


def _t_uninstall(b, name: str):
    """Удаление программы — только через подтверждение, и деинсталлятор спросит ещё раз."""
    from skills import programs as PR
    desc, action = PR.prepare(name)
    if desc is None:
        return action
    b.pending_confirm = (desc, action)
    return (f"ТРЕБУЕТСЯ ПОДТВЕРЖДЕНИЕ: {desc}. Назови хозяину программу и сколько она занимает, "
            "спроси «удалить?». После «да» откроется окно удаления — там он подтвердит ещё раз.")


TOOL_IMPL.update({
    "disk_space": _t_disk, "clean_preview": _t_clean_preview, "clean_disk": _t_clean,
    "uninstall_app": _t_uninstall,
})

TOOLS += [
    {"name": "disk_space", "description": "Сколько свободного места на дисках", "parameters": _p()},
    {"name": "clean_preview",
     "description": ("Только посмотреть, сколько мусора можно удалить. Если просят именно "
                     "почистить — не используй, сразу вызывай clean_disk."),
     "parameters": _p()},
    {"name": "clean_disk",
     "description": ("Очистить диск от временных файлов и кэшей. Вызывай сразу, как только "
                     "попросили почистить, не спрашивая заранее: инструмент сам вернёт запрос "
                     "на подтверждение, и только тогда спроси хозяина."),
     "parameters": _p()},
    {"name": "uninstall_app",
     "description": ("Удалить установленную программу или игру — как через «Установку и удаление "
                     "программ» (игру Steam — через Steam). Вызывай сразу: инструмент найдёт её и "
                     "вернёт запрос на подтверждение с названием и размером. Не удаляй программы "
                     "через powershell."),
     "parameters": _p(name={"type": "string", "description": "название программы или игры"})},
]



def _t_calc(b, expression: str):
    return TL.calculate(expression)


def _t_rate(b, currency: str = "USD"):
    return TL.exchange_rate(currency)


def _t_convert_currency(b, amount: float, frm: str, to: str = "RUB"):
    return TL.convert_currency(amount, frm, to)


def _t_convert_unit(b, amount: float, frm: str, to: str):
    return TL.convert_unit(amount, frm, to)


def _t_alarm(b, time: str):
    return TL.set_alarm(time)


def _t_translate(b, text: str, to: str = "en"):
    return TL.translate(text, to)


TOOL_IMPL.update({
    "calculate": _t_calc, "exchange_rate": _t_rate,
    "convert_currency": _t_convert_currency, "convert_unit": _t_convert_unit,
    "set_alarm": _t_alarm, "translate": _t_translate,
})

TOOLS += [
    {"name": "calculate", "description": "Посчитать арифметическое выражение",
     "parameters": _p(expression={"type": "string"})},
    {"name": "exchange_rate", "description": "Курс валюты к рублю",
     "parameters": _p(currency={"type": "string", "description": "доллар, евро, юань"})},
    {"name": "convert_currency", "description": "Перевести сумму из валюты в валюту",
     "parameters": _p(amount={"type": "number"}, frm={"type": "string"},
                      to={"type": "string"})},
    {"name": "convert_unit", "description": "Перевести единицы: км, м, кг, часы, гигабайты",
     "parameters": _p(amount={"type": "number"}, frm={"type": "string"},
                      to={"type": "string"})},
    {"name": "set_alarm", "description": "Поставить будильник на время",
     "parameters": _p(time={"type": "string", "description": "7 утра, 15:30"})},
    {"name": "translate", "description": "Перевести текст на другой язык",
     "parameters": _p(text={"type": "string"},
                      to={"type": "string", "description": "код языка: en, de, fr, zh"})},
]



def _t_add_student(b, name: str, subject: str = "", rate: int = 0, duration: int = 60):
    return LS.add_student(name, subject, rate, duration)


def _t_students(b):
    return LS.list_students()


def _t_set_schedule(b, name: str, weekday: str, time: str):
    return LS.set_schedule(name, weekday, time)


def _t_lessons(b, period: str = "today"):
    return LS.schedule_for(period)


def _t_next_lesson(b):
    return LS.next_lesson()


def _t_start_lesson(b, name: str = ""):
    return LS.start_lesson(name)


def _t_finish_lesson(b, name: str = ""):
    return LS.finish_lesson(name)


def _t_student_note(b, name: str, text: str):
    return LS.add_note(name, text)


def _t_about_student(b, name: str):
    return LS.about_student(name)


def _t_earnings(b, period: str = "week"):
    return LS.earnings(period)


TOOL_IMPL.update({
    "add_student": _t_add_student, "students": _t_students,
    "set_schedule": _t_set_schedule, "lessons": _t_lessons,
    "next_lesson": _t_next_lesson, "start_lesson": _t_start_lesson,
    "finish_lesson": _t_finish_lesson, "student_note": _t_student_note,
    "about_student": _t_about_student, "earnings": _t_earnings,
})

TOOLS += [
    {"name": "add_student", "description": "Завести ученика: имя, предмет, ставка за занятие",
     "parameters": _p(name={"type": "string"}, subject={"type": "string"},
                      rate={"type": "integer"}, duration={"type": "integer"})},
    {"name": "students", "description": "Список учеников", "parameters": _p()},
    {"name": "set_schedule", "description": "Регулярное занятие: ученик, день недели, время",
     "parameters": _p(name={"type": "string"}, weekday={"type": "string"},
                      time={"type": "string"})},
    {"name": "lessons", "description": "Расписание занятий",
     "parameters": _p(period={"type": "string", "description": "today, tomorrow, week"})},
    {"name": "next_lesson", "description": "Когда следующее занятие и с кем", "parameters": _p()},
    {"name": "start_lesson", "description": "Начать урок: ставит таймер на длительность",
     "parameters": _p(name={"type": "string"})},
    {"name": "finish_lesson", "description": "Отметить урок проведённым",
     "parameters": _p(name={"type": "string"})},
    {"name": "student_note", "description": "Записать наблюдение об ученике в журнал",
     "parameters": _p(name={"type": "string"}, text={"type": "string"})},
    {"name": "about_student", "description": "Что известно об ученике: предмет, занятия, заметки",
     "parameters": _p(name={"type": "string"})},
    {"name": "earnings", "description": "Заработок за период по проведённым занятиям",
     "parameters": _p(period={"type": "string", "description": "today, week, month"})},
]


if __name__ == "__main__":
    config.setup_console()
    b = Brain(config.CFG)
    print("ключ Gemini:", "есть" if b.ready else "НЕТ — умный режим выключен")
    print("инструментов подключено:", len(TOOLS))
    if b.ready:
        print(b.ask("Привет. Скажи одной фразой, что ты умеешь."))
