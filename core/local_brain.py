# -*- coding: utf-8 -*-
"""Свой мозг на своей видеокарте: работает без интернета и без ключей.

Зачем: Джарвис должен делать дело и тогда, когда облако недоступно — пропал
интернет, туннель VPN рвётся, бесплатный лимит Gemini кончился (ошибка 429).
Раньше в такие минуты он отвечал «мозг недоступен» и переставал выполнять всё,
что сложнее правил роутера.

Как устроено:

* Модель — открытая, скачивается один раз в D:\\jarvis\\llm\\models и дальше
  принадлежит нам: без токенов, без оплаты, без сети. Запускает её llama.cpp
  (llama-server.exe) — переносная папка, ничего не ставит в систему. Сборка под
  Vulkan, а не CUDA: работает на любой видеокарте, и у клиента тоже.

* Характер и инструменты — те же, что у облачного мозга: тот же текст PERSONA,
  те же 55 инструментов, вызываются той же функцией. Два мозга с разными
  умениями пришлось бы чинить дважды.

* Порядок: облако, пока оно отвечает, — оно умнее. Упало — этот же вопрос
  уходит своей модели, и на пять минут облако не дёргаем, чтобы каждая просьба
  не ждала таймаута. Режим можно закрепить в settings.json → brain.mode:
  auto (по умолчанию), local (только своя), cloud (только облако).

* Видеокарту зря не держим: модель грузится, когда понадобилась, и выгружается
  после 15 минут без дела. В Доте видеопамять нужнее.

Чего своя модель не умеет: смотреть на экран (у неё нет зрения — инструмент
look_at_screen офлайн честно откажет) и живой разговор с перебиванием — это
умеет только Gemini Live, офлайн Джарвис переходит на «вопрос — ответ».
"""
import json
import re
import subprocess
import threading
import time
from pathlib import Path

import requests

from core import config, log

LLM = config.ROOT / "llm"
DEFAULT_MODEL = "Qwen3.5-2B-Q4_K_M.gguf"
DEFAULT_URL = ("https://huggingface.co/bartowski/Qwen_Qwen3.5-2B-GGUF/resolve/main/"
               "Qwen_Qwen3.5-2B-Q4_K_M.gguf")
CLOUD_PAUSE = 300           # после сбоя облака пять минут работаем своим мозгом
IDLE_UNLOAD = 15 * 60       # без дела — освобождаем видеокарту

# Слова-отчёты о сделанном. Если они есть в ответе, а инструмент не вызван —
# модель докладывает о деле, которого не делала
CLAIMS = re.compile(r"\b(закры\w+|откры\w+|включ\w+|выключ\w+|запомн\w+|записа\w+|"
                    r"постав\w+|останов\w+|снижен\w*|увеличен\w*|убав\w+|прибав\w+|"
                    r"готово|сделано|погода|градус\w*|напомню|удал\w+|"
                    # Обещания тоже: «Посмотрю на экран» без вызова инструмента —
                    # то же враньё, только в будущем времени (замер 05.10.2026)
                    r"посмотр\w*|провер\w*|гляну|сделаю|нажм\w*|найду|переключ\w*)\b", re.I)

# Подсказки для маленькой модели. Большой они не нужны, а этой помогают не
# путаться в 55 инструментах. Текст неизменный — llama.cpp держит его в кэше
LOCAL_HINTS = """

Правила выбора инструмента:
- Любое действие с компьютером делай ТОЛЬКО через инструмент. Без вызова инструмента
  нельзя говорить, что что-то открыл, закрыл, включил, запомнил или поставил.
- Видео: включить — youtube_play; «не то», «следующее» — youtube_play с next=true;
  пауза, продолжить, весь экран — video. Вкладки — browser. Что играет — who_sounds.
- Нажать кнопку, меню или ссылку в программе или на странице — ui_click по названию.
  Не знаешь, что есть в окне, — ui_elements.
- Погода — только через weather, никогда не придумывай её.
- Громкость — volume. Заметки — note. Напоминания и задачи — add_task.
- Если инструмента для просьбы нет — так и скажи одной фразой."""


class LocalModel:
    """llama-server под рукой: поднимается по требованию, гаснет без дела."""

    def __init__(self, cfg: dict):
        b = cfg.get("brain", {})
        self.model_path = LLM / "models" / b.get("local_model", DEFAULT_MODEL)
        # Надстройка дообучения (LoRA) поверх модели — десятки мегабайт вместо
        # полутора гигабайт новой модели. Нет файла — работаем на исходной
        lora = b.get("local_lora", "")
        self.lora_path = (LLM / "models" / lora) if lora else None
        if self.lora_path and not self.lora_path.exists():
            log.write("error", f"[свой мозг] надстройки {lora} нет — работаю на исходной модели")
            self.lora_path = None
        self.exe = LLM / "bin" / "llama-server.exe"
        self.port = int(b.get("local_port", 8090))
        self.ctx = int(b.get("local_ctx", 12288))
        self.gpu_layers = int(b.get("local_gpu_layers", 99))
        self.url = f"http://127.0.0.1:{self.port}"
        self.session = requests.Session()
        self.session.trust_env = False      # сервер у нас же — мимо системного прокси
        self._proc = None
        self._prefix_ready = False
        self._lock = threading.Lock()
        self._last_used = 0.0
        threading.Thread(target=self._idle_watch, daemon=True).start()

    @property
    def available(self) -> bool:
        return self.exe.exists() and self.model_path.exists()

    def _healthy(self) -> bool:
        try:
            return self.session.get(f"{self.url}/health", timeout=2).status_code == 200
        except requests.RequestException:
            return False

    def ensure_running(self, wait: float = 120) -> bool:
        """Поднять сервер, если не поднят. True — можно спрашивать."""
        with self._lock:
            if self._proc and self._proc.poll() is None and self._healthy():
                return True
            if not self.available:
                return False
            if self._proc and self._proc.poll() is None:
                self._proc.kill()
            (LLM / "cache").mkdir(parents=True, exist_ok=True)
            self._prefix_ready = False
            args = [str(self.exe), "-m", str(self.model_path), "-c", str(self.ctx),
                    "-ngl", str(self.gpu_layers), "--jinja", "-np", "1",
                    "--slot-save-path", str(LLM / "cache"),
                    "--host", "127.0.0.1", "--port", str(self.port)]
            if self.lora_path:
                args += ["--lora", str(self.lora_path)]
            logf = open(LLM / "server.log", "w", encoding="utf-8")
            self._proc = subprocess.Popen(args, stdout=logf, stderr=subprocess.STDOUT,
                                          creationflags=subprocess.CREATE_NO_WINDOW)
            t0 = time.monotonic()
            while time.monotonic() - t0 < wait:
                if self._proc.poll() is not None:
                    log.write("error", "[свой мозг] сервер упал при запуске — см. llm/server.log")
                    return False
                if self._healthy():
                    log.write("info", f"[свой мозг] модель загружена за {time.monotonic() - t0:.1f} c")
                    self._last_used = time.monotonic()
                    return True
                time.sleep(0.5)
            log.write("error", "[свой мозг] сервер не поднялся вовремя")
            return False

    def prepare_prefix(self, system: str, tools) -> None:
        """Разобранное начало запроса — с диска, а не заново.

        Описания 55 инструментов — около пяти тысяч токенов, и на GTX 1060 их
        разбор занимает 10 секунд. Раньше их платил первый же вопрос после
        обрыва связи — ровно в ту минуту, когда хозяин и так раздражён. Теперь
        разобранное сохраняется в llm/cache один раз и при каждом запуске
        берётся оттуда. Имя файла — отпечаток модели, характера и инструментов:
        поменяется что-то из них — разберём заново, старый кэш не подсунем.
        """
        if self._prefix_ready:
            return
        import hashlib
        # Надстройка меняет веса — с ней разобранное начало уже другое
        lora = self.lora_path.name if self.lora_path else ""
        key = hashlib.sha1((self.model_path.name + lora + system +
                            json.dumps(tools, ensure_ascii=False)).encode()).hexdigest()[:16] + ".bin"
        t0 = time.monotonic()
        try:
            r = self.session.post(f"{self.url}/slots/0?action=restore",
                                  json={"filename": key}, timeout=60)
            if r.status_code == 200:
                self._prefix_ready = True
                log.write("info", f"[свой мозг] разбор инструментов взят с диска за "
                                  f"{time.monotonic() - t0:.1f} c")
                return
        except requests.RequestException:
            pass
        # Сохраняем ровно до места, где начинается вопрос хозяина, — не дальше.
        # У Qwen3.5 часть слоёв рекуррентная: такую модель нельзя откатить на
        # середину кэша, только продолжить его. Первая версия сохраняла кэш с
        # вопросом «привет» внутри, новый вопрос расходился с ним раньше, и
        # сервер честно разбирал все пять тысяч токенов заново (замер 05.10.2026:
        # восстановление за 0,1 с, а ответ всё равно через 13 с).
        marker = "§§§"
        rendered = self.session.post(f"{self.url}/apply-template", json={
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": marker}],
            "tools": tools, "chat_template_kwargs": {"enable_thinking": False}},
            timeout=30).json()["prompt"]
        prefix = rendered[:rendered.index(marker)]
        self.session.post(f"{self.url}/completion", json={
            "prompt": prefix, "n_predict": 0, "cache_prompt": True}, timeout=180)
        try:
            self.session.post(f"{self.url}/slots/0?action=save",
                              json={"filename": key}, timeout=120)
            log.write("info", f"[свой мозг] инструменты разобраны за {time.monotonic() - t0:.1f} c "
                              "и сохранены — дальше это мгновенно")
        except requests.RequestException:
            pass
        self._prefix_ready = True

    def chat(self, messages, tools=None, max_tokens: int = 400, require_tool: bool = False) -> dict:
        payload = {"messages": messages, "temperature": 0.3, "max_tokens": max_tokens,
                   # Рассуждения вслух выключены: на выбор инструмента они только тратят время
                   "chat_template_kwargs": {"enable_thinking": False}}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "required" if require_tool else "auto"
        r = self.session.post(f"{self.url}/v1/chat/completions", json=payload, timeout=120)
        r.raise_for_status()
        self._last_used = time.monotonic()
        return r.json()["choices"][0]["message"]

    def _idle_watch(self):
        while True:
            time.sleep(60)
            if (self._proc and self._proc.poll() is None
                    and time.monotonic() - self._last_used > IDLE_UNLOAD):
                self.stop()
                log.write("info", "[свой мозг] выгружен после простоя — видеокарта свободна")

    def stop(self):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(10)
                except Exception:
                    self._proc.kill()
            self._proc = None


# Сборка llama.cpp закреплена: проверено на ней, а свежие сборки выходят по
# нескольку раз в день и иногда ломают формат запросов
LLAMA_URL = ("https://github.com/ggml-org/llama.cpp/releases/download/b11398/"
             "llama-b11398-bin-win-vulkan-x64.zip")


def install(progress=print) -> bool:
    """Поставить свой мозг: движок llama.cpp (33 МБ) и модель (1,4 ГБ).

    Всё ложится в папку llm рядом с Джарвисом — в систему ничего не ставится,
    удаляется вместе с папкой. Обрыв связи не страшен: загрузка докачивается.
    """
    import io
    import zipfile
    from core.download import fetch

    bin_dir = LLM / "bin"
    if not (bin_dir / "llama-server.exe").exists():
        progress("Скачиваю движок llama.cpp (33 МБ)...")
        zpath = fetch(LLAMA_URL, LLM / "llama.zip", progress=progress)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(bin_dir)
        zpath.unlink(missing_ok=True)
    model = LLM / "models" / DEFAULT_MODEL
    if not model.exists():
        progress("Скачиваю модель Qwen3.5-2B (1,4 ГБ) — один раз, дальше работает без интернета...")
        fetch(DEFAULT_URL, model, progress=progress)
    progress("Проверяю, что модель запускается...")
    lm = LocalModel(config.CFG)
    ok = lm.ensure_running(wait=300)
    lm.stop()
    progress("Свой мозг готов." if ok else "Модель не запустилась — смотри llm/server.log")
    return ok


def _openai_tools(tools):
    return [{"type": "function", "function": {
        "name": t["name"], "description": t.get("description", ""),
        "parameters": t.get("parameters") or {"type": "object", "properties": {}}}}
        for t in tools]


class HybridBrain:
    """Мозг, который работает и в сети, и без неё. Снаружи — как обычный Brain."""

    def __init__(self, cloud, cfg: dict):
        self.cloud = cloud
        self.cfg = cfg
        self.local = LocalModel(cfg)
        self.mode = cfg.get("brain", {}).get("mode", "auto")
        self.cloud_off_until = 0.0
        self._net_checked = 0.0
        self._net_ok = True
        self.history = []                  # своя короткая история для локальной модели
        self.last_source = ""              # кто ответил: облако или своя модель

    # то, что инструменты и Джарвис берут у мозга, — от облачного
    @property
    def ready(self) -> bool:
        return self.cloud.ready or self.local.available

    @property
    def pending_confirm(self):
        return self.cloud.pending_confirm

    @pending_confirm.setter
    def pending_confirm(self, value):
        self.cloud.pending_confirm = value

    def reset(self):
        self.cloud.reset()
        self.history = []

    def _cloud_reachable(self) -> bool:
        """Есть ли дорога до облака — за пару секунд, а не за три минуты.

        Без этой проверки при «глухом» VPN, который теряет пакеты молча, облачный
        мозг ждал бы по 45 секунд на каждую из четырёх моделей. Проверяем тем же
        путём, что и настоящие запросы (requests сам берёт системный прокси):
        прямое соединение здесь не показатель — у хозяина часть адресов напрямую
        закрыта, и через прокси облако доступно, когда напрямую нет.
        """
        now = time.time()
        if now - self._net_checked < 30:
            return self._net_ok
        try:
            requests.head("https://generativelanguage.googleapis.com/", timeout=3)
            self._net_ok = True                      # любой ответ — значит дорога есть
        except requests.RequestException:
            self._net_ok = False
        self._net_checked = now
        return self._net_ok

    def ask(self, text: str, image_path: str = None) -> str:
        use_cloud = (self.mode != "local" and self.cloud.ready
                     and time.time() >= self.cloud_off_until)
        if use_cloud and self.local.available and not self._cloud_reachable():
            log.write("info", "[мозг] до облака нет дороги — сразу своя модель")
            use_cloud = False
        if use_cloud:
            answer = self.cloud.ask(text, image_path)
            if self.cloud.last_error is None:
                self.last_source = "облако"
                self._remember(text, answer)
                return answer
            if self.mode == "cloud" or not self.local.available:
                return answer
            log.write("info", f"[мозг] облако не ответило ({str(self.cloud.last_error)[:80]}) "
                              "— отвечаю своей моделью")
            self.cloud_off_until = time.time() + CLOUD_PAUSE
        if not self.local.available:
            return ("Облачный мозг недоступен, а своя модель не установлена. "
                    "Простые команды я всё равно выполняю.")
        return self._ask_local(text)

    def _remember(self, text: str, answer: str):
        """Короткая память разговора, общая для обоих мозгов."""
        self.history += [{"role": "user", "content": text},
                         {"role": "assistant", "content": answer}]
        self.history = self.history[-8:]

    def _ask_local(self, text: str) -> str:
        from core.brain import TOOLS, PERSONA
        from core import memory
        if not self.local.ensure_running():
            return "Своя модель не запустилась — смотри журнал."
        # Начало запроса — характер и инструменты — неизменное, его llama.cpp
        # держит в кэше и даже сохраняет на диск. Память о хозяине меняется,
        # поэтому она идёт не в системный текст, а перед самим вопросом: иначе
        # каждая новая заметка сбрасывала бы разбор пяти тысяч токенов.
        system = PERSONA + LOCAL_HINTS
        ctx = memory.context_for_llm()
        question = f"[Что ты помнишь: {ctx}]\n\n{text}" if ctx else text
        # Без истории разговора. Замер 05.10.2026: маленькая модель, увидев в
        # истории свой же ответ «у меня нет такого инструмента», дальше повторяла
        # его на всё подряд — из шести просьб выполнила одну. Без истории та же
        # модель попадала в 9 из 14.
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": question}]
        tools = _openai_tools(TOOLS)
        self.local.prepare_prefix(system, tools)
        try:
            for step in range(4):
                msg = self.local.chat(messages, tools)
                calls = msg.get("tool_calls") or []
                if not calls and step == 0 and CLAIMS.search(msg.get("content") or ""):
                    # Сказала «закрываю», «запомнил», «громкость снижена» — и ничего
                    # не вызвала. На замере так было в трёх промахах из пяти: модель
                    # рапортовала о деле, которого не делала. Переспрашиваем с
                    # обязательным вызовом инструмента.
                    log.write("info", f"[свой мозг] ответ без действия: «{(msg.get('content') or '')[:60]}» — переспрашиваю")
                    msg = self.local.chat(messages, tools, require_tool=True)
                    calls = msg.get("tool_calls") or []
                if not calls:
                    answer = re.sub(r"<think>.*?</think>", "", msg.get("content") or "",
                                    flags=re.S).strip() or "Готово."
                    self.last_source = "своя модель"
                    self._remember(text, answer)
                    return answer
                messages.append({"role": "assistant", "content": msg.get("content") or "",
                                 "tool_calls": calls})
                for call in calls:
                    name = call["function"]["name"]
                    try:
                        args = json.loads(call["function"].get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    print(f"   ⚙ {name} {args} (своя модель)")
                    log.write("tool", f"{name} {args} [своя модель]")
                    result = self.cloud._run_tool(name, args)
                    messages.append({"role": "tool", "tool_call_id": call.get("id", name),
                                     "content": str(result)})
            return "Слишком много шагов, остановился."
        except requests.RequestException as e:
            log.write("error", f"[свой мозг] {type(e).__name__}: {str(e)[:100]}")
            return "Своя модель не ответила."
