# -*- coding: utf-8 -*-
"""Живой разговор: модель слушает голос и отвечает голосом напрямую.

Зачем. Живой тест 14.09.2026 показал, что конвейер «распознать → понять →
придумать → озвучить» на этом процессоре отвечает за 5–8 секунд, а голос
Microsoft звучит как диктор. Живая модель Gemini слышит звук сама, отвечает
через 1.5–2.5 секунды тёплым голосом, и её можно перебить на полуслове —
как человека.

Как устроено.
  • Разговор открывается только после обращения по имени или Ctrl+Alt+J.
    До этого звук никуда не уходит: имя ищется на этом компьютере.
  • Фраза с обращением уже записана, поэтому уходит разом — по замеру ответ
    приходит на 3–4 секунды раньше, чем при отправке в темпе речи.
  • Дальше микрофон стримится в модель. Конец фразы, паузы и перебивания
    определяет она сама.
  • Руки у модели те же, что у текстового мозга: погода, уроки, громкость.
    Без инструментов она выдумывает — на пробе назвала погоду, не проверяя.
  • Опасное (удаление, отправка сообщений, выключение) выполняется, только если
    в расшифровке голоса хозяина после вопроса действительно прозвучало «да».
    Модели на слово не верим.
  • Замолчали на 25 секунд, попрощались или нажали паузу — разговор закрыт,
    Джарвис снова ждёт обращения.

Если подключиться не вышло — run() возвращает «error: …», и главный цикл
отвечает по-старому, через правила и текстовый мозг.
"""
import asyncio
import queue
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config, log, memory, net

IN_RATE = 16000
OUT_RATE = 24000
DEFAULT_MODEL = "gemini-3.1-flash-live-preview"

# Английские слова — страховка: однажды расшифровка русской фразы пришла по-английски
# («Jarvis, explain what is a prime number»), и «да» тогда пришло бы как «yes»
YES = re.compile(r"\b(да|давай|подтверждаю|выполняй|конечно|ага|угу|делай|согласен|верно"
                 r"|yes|yeah|yep|sure|confirm|do it)\b", re.I)
NO = re.compile(r"\b(нет|не надо|не нужно|не делай|отмена|отмени|передумал"
                r"|no|nope|don't|cancel)\b", re.I)

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря"]

PERSONA = """Ты — Джарвис, голосовой помощник. Вы с хозяином разговариваете вслух, по-человечески.

Как говорить:
- По-русски, на «ты», тепло и живо — как толковый друг-помощник, а не диктор и не робот.
- Коротко: одна-две фразы. Подробно — только когда просят подробно.
- Без канцелярита, без «как искусственный интеллект», без шутки в каждой фразе.
- Не называй собеседника «хозяин» вслух.
- Перебили — не повторяй сказанное, сразу отвечай на новое.

Факты — только через инструменты, никогда не выдумывай:
- Время и дата, погода, курсы валют, задачи и напоминания, уроки, ученики, заработок,
  место на диске, открытые окна, громкость — всегда вызывай нужный инструмент.
- Просят что-то сделать на компьютере — делай инструментом, потом скажи итог в двух-трёх словах.

Опасные действия — удаление, отправка сообщений, выключение компьютера, очистка диска:
- Не спрашивай разрешения заранее. Сразу вызывай сам инструмент действия.
- Он ответит «ТРЕБУЕТСЯ ПОДТВЕРЖДЕНИЕ». Вот тогда один раз вслух назови, что именно сделаешь,
  и спроси, делать ли.
- Хозяин сказал «да» — вызови confirm_pending с confirmed=true. Сказал «нет» — confirmed=false.
- Сам инструмент действия второй раз не вызывай: запрос уже создан и ждёт ответа.

Разговор:
- Хозяин попрощался или сказал, что больше ничего не нужно, — коротко попрощайся и вызови end_conversation.
- Текст в скобках от системы напоминаний — это не хозяин. Передай суть своими словами, без «принято».

{honesty}
{about}
Сейчас {now}.
Что известно из памяти: {memory}"""

LIVE_TOOLS = [
    {"name": "end_conversation",
     "description": "Завершить разговор: хозяин попрощался или сказал, что больше ничего не нужно.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "confirm_pending",
     "description": ("Подтвердить или отменить опасное действие, которое ждёт подтверждения. "
                     "Вызывай только после явного ответа хозяина вслух."),
     "parameters": {"type": "object", "properties": {
         "confirmed": {"type": "boolean", "description": "true — хозяин сказал да, false — нет"}}}},
]


def _schema(types, p: dict):
    """Описание параметров в формате REST → схема библиотеки google-genai."""
    kind = (p.get("type") or "object").upper()
    kw = {"type": kind}
    if p.get("description"):
        kw["description"] = p["description"]
    if p.get("enum"):
        kw["enum"] = p["enum"]
    if kind == "OBJECT" and p.get("properties"):
        kw["properties"] = {k: _schema(types, v) for k, v in p["properties"].items()}
        if p.get("required"):
            kw["required"] = p["required"]
    if kind == "ARRAY" and p.get("items"):
        kw["items"] = _schema(types, p["items"])
    return types.Schema(**kw)


def trim_silence(audio: np.ndarray, threshold: float, keep_ms: int = 200) -> np.ndarray:
    """Срезать тишину по краям записанной фразы.

    В конце записи всегда почти секунда тишины — так детектор понял, что фраза
    кончилась. Модели она не нужна: об окончании мы сообщим сами.
    """
    if audio is None or len(audio) == 0:
        return audio
    win = IN_RATE // 50
    n = len(audio) // win
    if n == 0:
        return audio
    rms = np.sqrt((audio[:n * win].reshape(n, win) ** 2).mean(axis=1))
    loud = np.flatnonzero(rms > threshold)
    if loud.size == 0:
        return audio
    pad = int(keep_ms / 1000 * IN_RATE)
    start = max(0, loud[0] * win - pad)
    end = min(len(audio), (loud[-1] + 1) * win + pad)
    return audio[start:end]


class _Player:
    """Звук из сети → наушники, без рывков. Сбрасывается мгновенно, когда перебили.

    Живой тест 15.09.2026: звук «ломался». Замер показал, что сеть ни при чём —
    28 секунд речи приходят за 7.5, буфер всегда полон. Рвал сам проигрыватель:
      • блок устройства был 20 мс. Во время разговора в процессе работают
        микрофон, сеть, трей, будильник, и если поток звука ждёт своей очереди
        в Python дольше 20 мс, в наушниках щелчок. Теперь блок 50 мс;
      • каждый блок копировал и сдвигал весь накопленный буфер — до мегабайта;
        теперь куски лежат очередью и не двигаются;
      • фраза начинала звучать с первого пришедшего пакета. Теперь — когда
        накоплено 200 мс: заметно глазу не больше, чем пауза вдоха.
    """
    BLOCK = OUT_RATE // 20          # 50 мс
    PREBUFFER = int(0.20 * OUT_RATE) * 2
    REBUFFER = int(0.12 * OUT_RATE) * 2

    def __init__(self, device=None):
        import collections
        import sounddevice as sd
        self._chunks = collections.deque()
        self._offset = 0                 # сколько уже взято из первого куска
        self._queued = 0                 # байт в очереди
        self._lock = threading.Lock()
        self._playing = False
        self._turn_done = False
        self._threshold = self.PREBUFFER
        self.last_audio_at = 0.0
        self.gaps = 0                    # буфер кончился посреди фразы
        self.underflows = 0              # звуковая карта осталась без данных
        # Запас карты 300 мс: замер с открытым микрофоном и нагрузкой дал опоздания
        # обработчика до 155 мс при стандартном запасе 180 — впритык. Цена — при
        # перебивании голос умолкает на долю секунды позже, как у живого человека.
        self._stream = sd.RawOutputStream(samplerate=OUT_RATE, channels=1, dtype="int16",
                                          blocksize=self.BLOCK, latency=0.3,
                                          callback=self._cb, device=device)
        self._stream.start()

    def _take(self, n: int) -> bytes:
        out = bytearray()
        while n > 0 and self._chunks:
            chunk = self._chunks[0]
            avail = len(chunk) - self._offset
            if avail <= n:
                out += chunk[self._offset:] if self._offset else chunk
                self._chunks.popleft()
                self._offset = 0
                n -= avail
            else:
                out += chunk[self._offset:self._offset + n]
                self._offset += n
                n = 0
        self._queued -= len(out)
        return bytes(out)

    def _cb(self, outdata, frames, time_info, status):
        if status.output_underflow:
            self.underflows += 1
        need = frames * 2
        with self._lock:
            if not self._playing and self._queued and (
                    self._queued >= self._threshold or self._turn_done):
                self._playing = True
            data = self._take(need) if self._playing else b""
            if self._playing and not self._queued:
                self._playing = False
                if self._turn_done:
                    self._threshold = self.PREBUFFER     # следующая фраза — снова с запасом
                else:
                    self.gaps += 1                        # поток отстал посреди фразы
                    self._threshold = self.REBUFFER
        n = len(data)
        if n:
            outdata[:n] = data
            self.last_audio_at = time.monotonic()
        if n < need:
            outdata[n:need] = b"\x00" * (need - n)

    def feed(self, data: bytes):
        with self._lock:
            self._chunks.append(bytes(data))
            self._queued += len(data)
            self._turn_done = False

    def turn_done(self):
        """Модель договорила: хвост фразы играть сразу, не дожидаясь запаса."""
        with self._lock:
            self._turn_done = True

    def clear(self):
        with self._lock:
            self._chunks.clear()
            self._offset = 0
            self._queued = 0
            self._playing = False
            self._turn_done = False
            self._threshold = self.PREBUFFER

    @property
    def busy(self) -> bool:
        with self._lock:
            queued = self._queued
        return queued > 0 or time.monotonic() - self.last_audio_at < 0.35

    def close(self):
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass


class LiveConversation:
    def __init__(self, jarvis):
        self.j = jarvis
        self.cfg = jarvis.cfg
        lc = self.cfg.get("live", {})
        self.enabled = lc.get("enabled", True)
        self.model = lc.get("model", DEFAULT_MODEL)
        self.voice = lc.get("voice", "Charon")
        self.idle_timeout = float(lc.get("idle_timeout_s", 25))
        self.silence_ms = int(lc.get("silence_ms", 500))
        self.half_duplex = lc.get("duplex", "full") == "half"
        self.key = config.env("GEMINI_API_KEY")

        self.active = False
        self.last_error = ""
        self._session = None
        self._player = None
        self._stop = threading.Event()
        self._brain = None
        self.t_sent = None
        self.t_first_audio = None

        # Свой постоянный цикл событий в фоновом потоке: подключение можно начать
        # заранее из потока ушей и подхватить, когда выяснится, что звали Джарвиса
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True, name="live").start()
        self._prepared = None                  # Future → (контекст, сессия)
        self._idle_prepares = []               # когда заготовки пропали впустую
        self._prepare_off_until = 0.0

    # ---------- снаружи, из других потоков ----------
    @property
    def available(self) -> bool:
        if not (self.enabled and self.key):
            return False
        try:
            import google.genai  # noqa: F401
            return True
        except ImportError:
            return False

    def stop_speaking(self):
        """Ctrl+Alt+S посреди ответа — замолчать, но разговор не закрывать."""
        if self._player:
            self._player.clear()

    def end(self):
        self._stop.set()

    def inject(self, text: str) -> bool:
        """Сказать что-то посреди разговора — напоминание тем же голосом, без обрыва."""
        session = self._session
        if not (self.active and session):
            return False

        async def send():
            await session.send_realtime_input(text=text)

        asyncio.run_coroutine_threadsafe(send(), self._loop)
        return True

    # ---------- заготовка подключения ----------
    def prepare(self):
        """Начать подключение заранее — пока человек ещё договаривает фразу.

        Подключение отнимало около секунды у первого ответа. Если фраза окажется
        не обращением, заготовка тихо закрывается. Во время уроков в комнате
        говорят постоянно: после трёх холостых заготовок за полторы минуты они
        выключаются на пять минут, чтобы не долбить сервер впустую.
        """
        if not self.available or self.active or self._prepared is not None:
            return
        if time.monotonic() < self._prepare_off_until:
            return
        self._prepared = asyncio.run_coroutine_threadsafe(self._connect(), self._loop)

    def discard(self):
        """Имени во фразе не было — закрыть заготовку."""
        fut, self._prepared = self._prepared, None
        if fut is None:
            return
        asyncio.run_coroutine_threadsafe(self._close_prepared(fut), self._loop)
        now = time.monotonic()
        self._idle_prepares = [t for t in self._idle_prepares if now - t < 90] + [now]
        if len(self._idle_prepares) >= 3:
            self._prepare_off_until = now + 300
            self._idle_prepares.clear()
            log.write("info", "заготовки подключения на паузе 5 минут: вокруг разговаривают")

    async def _connect(self):
        from google import genai
        from google.genai import types
        net.prefer_ipv4()
        t0 = time.monotonic()
        client = genai.Client(api_key=self.key)
        ctx = client.aio.live.connect(model=self.model, config=self._config(types))
        session = await ctx.__aenter__()
        self._connect_s = time.monotonic() - t0
        return ctx, session

    async def _close_prepared(self, fut):
        try:
            ctx, _session = await asyncio.wrap_future(fut)
        except Exception:
            return
        try:
            await ctx.__aexit__(None, None, None)
        except Exception:
            pass

    # ---------- разговор ----------
    def run(self, first_audio=None, reason: str = "name") -> str:
        """Блокирует, пока идёт разговор. Возвращает причину конца или «error: …»."""
        fut = asyncio.run_coroutine_threadsafe(self._main(first_audio, reason), self._loop)
        try:
            return fut.result()
        except KeyboardInterrupt:
            self.end()
            raise
        except Exception as e:
            self.last_error = str(e)
            log.error("живой разговор", e)
            return f"error: {e}"
        finally:
            self.active = False
            self._session = None
            if self._player:
                self._player.close()
                self._player = None

    @property
    def brain(self):
        if self._brain is None:
            from core.brain import Brain
            self._brain = Brain(self.cfg)
        return self._brain

    def _instruction(self) -> str:
        now = datetime.now()
        stamp = (f"{WEEKDAYS[now.weekday()]}, {now.day} {MONTHS[now.month - 1]} "
                 f"{now.year} года, {now:%H:%M}")
        from core.brain import HONESTY
        # Кто хозяин — из настроек (about_owner), а не из кода: раньше описание
        # хозяина было вшито сюда — в публичном репозитории, и для любого
        # другого человека, например клиента, оно было бы неправдой
        about = self.cfg.get("about_owner", "").strip()
        return PERSONA.format(now=stamp, memory=memory.context_for_llm() or "пока ничего",
                              honesty=HONESTY, about=f"О хозяине: {about}\n" if about else "")

    def _config(self, types):
        from core.brain import TOOLS
        decls = []
        for t in TOOLS + LIVE_TOOLS:
            kw = {"name": t["name"], "description": t.get("description", "")}
            params = t.get("parameters") or {}
            if params.get("properties"):
                kw["parameters"] = _schema(types, params)
            decls.append(types.FunctionDeclaration(**kw))
        extra = {}
        thinking = self.cfg.get("live", {}).get("thinking_level", "MINIMAL")
        if thinking and "3." in self.model:          # у моделей 2.x этой настройки нет
            extra["thinking_config"] = types.ThinkingConfig(thinking_level=thinking)
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=self._instruction(),
            speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voice))),
            tools=[types.Tool(function_declarations=decls)],
            # Русский закреплён: по этой расшифровке проверяется «да» перед опасным
            input_audio_transcription=types.AudioTranscriptionConfig(
                language_codes=["ru-RU"], adaptation_phrases=["Джарвис"]),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            # Без высокой чувствительности к концу фразы сервер иногда не замечает,
            # что записанная фраза отправлена целиком, и молча ждёт — поймано на пробе
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    # Чувствительность к НАЧАЛУ речи не снижать: пробовал 15.09.2026 —
                    # модель перестала слышать живую запись хозяина («какая погода
                    # в Питере» осталась без ответа), а «Мм» всё равно обрывало её речь.
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                    silence_duration_ms=self.silence_ms,
                    prefix_padding_ms=200)),
            **extra,
        )

    def _reset(self):
        self._stop.clear()
        self.ending = False
        self.user_turn = ""
        self.said_turn = ""
        self.heard_since_pending = ""
        self.pending_since = None
        self.last_user_at = time.monotonic()
        self.t_sent = None                   # когда ушла первая фраза — для замера задержки
        self.t_first_audio = None
        self.turn_open = False               # модель говорит прямо сейчас

    async def _main(self, first_audio, reason):
        self._reset()
        prepared, self._prepared = self._prepared, None
        if prepared is not None:
            t0 = time.monotonic()
            try:
                ctx, session = await asyncio.wrap_future(prepared)
            except Exception as e:
                ctx = session = None
                log.write("info", f"заготовка не подключилась: {str(e)[:100]}")
            if session is not None:
                waited = time.monotonic() - t0
                try:
                    return await self._conversation(ctx, session, first_audio, reason,
                                                    f"заготовка, ждали {waited:.2f} c")
                except Exception as e:
                    # Фраза уже ушла — значит сломался сам разговор, а не заготовка
                    if self.t_sent is not None:
                        raise
                    # Заготовка умерла, пока ждала: сервер закрыл простаивающую сессию
                    if self._player:
                        self._player.close()
                        self._player = None
                    log.write("info", f"заготовка отказала ({str(e)[:80]}), подключаюсь заново")
                    self._reset()
        return await self._with_reconnect(first_audio, reason)

    @staticmethod
    def _transport_broke(e) -> bool:
        """Оборвалась связь, а не отказал сервис.

        Обрыв лечится переподключением, отказ — нет. Признак обрыва: код закрытия
        websocket (1011 «внутренняя ошибка», 1006 обрыв, 1001 уход) или ошибка TLS.
        Нехватку квоты (429), плохой запрос (400) и отказ по ключу (403) сюда не
        пускаем — от них переподключение не спасёт, нужен откат на старый путь.
        """
        text = str(e)
        if isinstance(e, (ConnectionError, OSError)) or "SSL" in text:
            return True
        code = getattr(e, "code", None)
        if code in (1000, 1001, 1006, 1011, 1012, 1013):
            return True
        return any(f"{c} " in text or f"({c}" in text for c in (1006, 1011, 1012, 1013))

    async def _with_reconnect(self, first_audio, reason):
        """Разговор, который переживает обрыв туннеля.

        На показе 02.10.2026 разговор падал с «1011 Internal error» — опыт
        (tests/probe_stream_end.py) показал, что сервер тут не при чём: тот же
        код отвечает 3 из 3, а рвётся соединение, у хозяина интернет идёт через
        VPN. Раньше обрыв считался отказом живого режима и на десять минут
        переводил Джарвиса на медленный путь — посреди разговора это слышно.
        Теперь он молча подключается заново и, если модель оборвало на полуслове,
        просит её договорить.
        """
        tail = None
        for attempt in range(3):
            ctx, session = await self._connect()
            how = f"подключение {self._connect_s:.2f} c" if not attempt else f"переподключение {attempt}"
            try:
                return await self._conversation(ctx, session, None if attempt else first_audio,
                                                reason, how, resume=tail)
            except Exception as e:
                if attempt == 2 or not self._transport_broke(e):
                    raise
                tail = self.said_turn.strip() if self.turn_open else None
                log.write("info", f"связь оборвалась ({str(e)[:60]}), подключаюсь заново")
                if self._player:
                    self._player.close()
                    self._player = None
                self._reset()

    async def _conversation(self, ctx, session, first_audio, reason, how, resume=None):
        from google.genai import types
        try:
            self._session = session
            self._player = _Player(self.cfg.get("live", {}).get("output_device"))
            self.active = True
            # Отсчёт тишины — с этой секунды, а не с момента вызова: на подключение
            # уходит 2-3 секунды, и они съедали окно ожидания. При коротком окне
            # разговор закрывался раньше, чем приходил ответ — на живой записи про
            # погоду он закрылся через секунду после открытия (15.09.2026).
            self.last_user_at = time.monotonic()
            log.write("info", f"живой разговор открыт ({how}, {self.model})")

            if first_audio is not None and len(first_audio):
                noise = getattr(self.j.ears, "_noise", 0.006)
                pcm = (np.clip(trim_silence(first_audio, noise), -1, 1) * 32767).astype("<i2").tobytes()
                step = IN_RATE * 2 // 5                          # по 200 мс, без пауз
                for i in range(0, len(pcm), step):
                    await session.send_realtime_input(
                        audio=types.Blob(data=pcm[i:i + step], mime_type="audio/pcm;rate=16000"))
                await session.send_realtime_input(audio_stream_end=True)
                self.t_sent = time.monotonic()
            elif resume:
                await session.send_realtime_input(
                    text=f"(Система: связь оборвалась, и ты замолчал на полуслове. "
                         f"Ты говорил: «{resume[-300:]}». Договори эту мысль одной фразой, "
                         f"без извинений и не начиная заново.)")
                self.t_sent = time.monotonic()
            elif reason == "hotkey":
                await session.send_realtime_input(
                    text="(Система: хозяин позвал тебя горячей клавишей. Отзовись одним-двумя словами.)")
                self.t_sent = time.monotonic()

            if getattr(self.j, "ears", None):
                self.j.ears.flush()          # звук, накопившийся пока подключались, не нужен

            tasks = [asyncio.create_task(self._pump_mic(session, types)),
                     asyncio.create_task(self._receive(session, types)),
                     asyncio.create_task(self._watchdog())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            result = "ended"
            for t in done:
                if t.exception():
                    raise t.exception()
                result = t.result() or result
            self._flush_heard()
            self._flush_said()
            log.write("info", f"живой разговор закрыт: {result}")
            return result
        finally:
            try:
                await ctx.__aexit__(None, None, None)
            except Exception:
                pass

    async def _pump_mic(self, session, types):
        q = self.j.ears._q
        while not self._stop.is_set():
            try:
                chunks = [await asyncio.to_thread(q.get, True, 0.25)]
            except queue.Empty:
                continue
            while True:
                try:
                    chunks.append(q.get_nowait())
                except queue.Empty:
                    break
            if self.half_duplex and self._player and self._player.busy:
                continue                     # колонки: пока говорит сам, не слушаем
            audio = np.concatenate(chunks)
            pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
            await session.send_realtime_input(
                audio=types.Blob(data=pcm, mime_type="audio/pcm;rate=16000"))
        return "stopped"

    async def _receive(self, session, types):
        while not self._stop.is_set():
            got = 0
            async for msg in session.receive():
                got += 1
                if msg.go_away:
                    return "go_away"                 # сервер закрывает сессию по времени
                if msg.tool_call:
                    await self._handle_tools(session, types, msg.tool_call)
                sc = msg.server_content
                if not sc:
                    continue
                if sc.interrupted:
                    self._player.clear()             # перебили — умолкнуть сразу
                    self._flush_said(interrupted=True)
                if sc.input_transcription and sc.input_transcription.text:
                    text = sc.input_transcription.text
                    self.user_turn += text
                    self.last_user_at = time.monotonic()
                    if self.pending_since is not None:
                        self.heard_since_pending += text
                if sc.output_transcription and sc.output_transcription.text:
                    self.said_turn += sc.output_transcription.text
                if sc.model_turn:
                    self._flush_heard()
                    for part in sc.model_turn.parts or []:
                        if part.inline_data and part.inline_data.data:
                            if self.t_first_audio is None and self.t_sent is not None:
                                self.t_first_audio = time.monotonic()
                                log.write("info", f"первый звук ответа через "
                                                  f"{self.t_first_audio - self.t_sent:.2f} c")
                            self.turn_open = True    # говорит прямо сейчас
                            self._player.feed(part.inline_data.data)
                if sc.turn_complete:
                    self._player.turn_done()         # хвост фразы — без ожидания запаса
                    self.turn_open = False
                    self._flush_heard()
                    self._flush_said()
            if got == 0:
                return "closed"                      # соединение закрылось
        return "stopped"

    async def _watchdog(self):
        while True:
            await asyncio.sleep(0.25)
            if self._stop.is_set():
                return "stopped"
            if not getattr(self.j, "running", True):
                return "shutdown"
            if getattr(self.j, "paused", False):
                return "paused"
            speaking = self._player.busy
            if self.ending and not speaking:
                await asyncio.sleep(0.3)
                return "goodbye"
            last = max(self.last_user_at, self._player.last_audio_at)
            if not speaking and time.monotonic() - last > self.idle_timeout:
                return "idle"

    # ---------- инструменты ----------
    async def _handle_tools(self, session, types, tool_call):
        responses = []
        for fc in tool_call.function_calls or []:
            args = dict(fc.args or {})
            print(f"   ⚙ {fc.name} {args}")
            log.write("tool", f"{fc.name} {args}")
            try:
                result = await self._run_tool(fc.name, args)
            except Exception as e:
                result = f"ошибка: {e}"
            responses.append(types.FunctionResponse(
                id=fc.id, name=fc.name, response={"result": str(result)[:2000]}))
        await session.send_tool_response(function_responses=responses)

    async def _run_tool(self, name: str, args: dict):
        if name == "end_conversation":
            self.ending = True
            return "Хорошо, разговор закончится, когда договоришь."
        if name == "confirm_pending":
            return await self._confirm(bool(args.get("confirmed", False)))
        before = self.brain.pending_confirm
        result = await asyncio.to_thread(self.brain._run_tool, name, args)
        if self.brain.pending_confirm is not None and self.brain.pending_confirm is not before:
            self.pending_since = time.monotonic()    # с этого момента ждём «да» голосом
            self.heard_since_pending = ""
        return result

    async def _confirm(self, confirmed: bool) -> str:
        pending = self.brain.pending_confirm
        if pending is None:
            return ("Подтверждать нечего: запроса ещё нет. Сначала вызови сам инструмент действия — "
                    "он создаст запрос, — и потом спроси хозяина.")
        if not confirmed:
            self.brain.pending_confirm = None
            self.pending_since = None
            return "Отменено."
        # Модели на слово не верим: «да» должно прозвучать в расшифровке голоса.
        # Расшифровка иногда отстаёт от вызова инструмента — ждём до двух секунд.
        for _ in range(8):
            heard = self.heard_since_pending
            if NO.search(heard):
                break
            if YES.search(heard):
                desc, action = pending
                self.brain.pending_confirm = None
                self.pending_since = None
                log.write("info", f"подтверждено голосом: {desc}")
                result = await asyncio.to_thread(action)
                return f"Выполнено: {result}"
            await asyncio.sleep(0.25)
        return ("Хозяин вслух не сказал «да». Не выполняй: спроси ещё раз и дождись "
                "явного согласия.")

    # ---------- журнал ----------
    def _flush_heard(self):
        text = getattr(self, "user_turn", "").strip()
        if text:
            print(f"👤 {text}")
            log.heard(text)
            memory.log_dialog("user", text)
        self.user_turn = ""

    def _flush_said(self, interrupted: bool = False):
        text = getattr(self, "said_turn", "").strip()
        if text:
            mark = " [перебили]" if interrupted else ""
            print(f"🗣 {text}{mark}")
            log.said(text + mark)
            memory.log_dialog("jarvis", text)
        self.said_turn = ""
