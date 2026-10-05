# -*- coding: utf-8 -*-
"""Телефон как второй пульт к тому же Джарвису.

Зачем: голос работает, только когда ты за компьютером. С телефона можно написать
или наговорить то же самое — «запусти игру», «что на диске», «напомни вечером», —
и это выполнится на компьютере, а ответ придёт в чат. Плюс обратная связь:
напоминания и предупреждения долетают в Telegram, даже когда дома никого нет.

Решения, которые стоит знать:

* Отдельного «мозга для телефона» нет. Сообщение идёт тем же путём, что голос:
  правила роутера, потом Gemini с инструментами. Иначе получились бы два
  ассистента с разными умениями, и чинить пришлось бы дважды.

* Работаем по Bot API на обычном `requests`, без aiogram. Причина местная: на
  этой машине интернет идёт через VPN-клиент, и `aiohttp` системный прокси не
  подхватывает — бот на aiogram у хозяина падал по таймауту. `requests` прокси
  берёт сам, и лишней зависимости не нужно.

* Отвечаем только хозяину. Номер его чата лежит в настройках; любому другому
  бот говорит, что он личный, и больше ничего не делает. Без этого кто угодно,
  нашедший бота, получил бы доступ к компьютеру.

* Опасное действие подтверждается там же, где спрошено: подтверждение с
  телефона не закрывает вопрос, заданный голосом, и наоборот.
"""
import io
import threading
import time

import requests

from core import config, log

API = "https://api.telegram.org"
POLL_TIMEOUT = 25          # длинный опрос: соединение висит, пока нет сообщений
MAX_TEXT = 3900            # предел сообщения в Telegram — 4096, оставляем запас


class Phone:
    def __init__(self, jarvis):
        self.j = jarvis
        cfg = jarvis.cfg.get("phone", {})
        self.enabled = cfg.get("enabled", True)
        self.owner = int(cfg.get("owner_id", 0) or 0)
        self.voice_replies = cfg.get("voice_replies", "auto")   # auto | always | never
        self.push = cfg.get("push_reminders", True)
        self.token = config.env("TELEGRAM_BOT_TOKEN")
        self.session = requests.Session()
        self._offset = 0
        self._stop = threading.Event()
        self._thread = None
        self.me = ""

    # ---------- связь ----------
    @property
    def available(self) -> bool:
        return bool(self.enabled and self.token)

    # Служебные имена с подчёркиванием: у Telegram свой параметр timeout (длина
    # опроса), и без разделения он затирал таймаут самого запроса
    def _call(self, method: str, _wait: int = 20, _files=None, **params):
        url = f"{API}/bot{self.token}/{method}"
        try:
            r = self.session.post(url, data=params, files=_files, timeout=_wait)
            data = r.json()
            if not data.get("ok"):
                log.write("error", f"[телефон] {method}: {str(data)[:120]}")
                return None
            return data.get("result")
        except Exception as e:
            log.write("error", f"[телефон] {method}: {type(e).__name__} {str(e)[:90]}")
            return None

    def check(self) -> str:
        """Проверка перед запуском: отвечает ли бот и кто он."""
        if not self.token:
            return "нет токена: заведи бота у @BotFather и впиши TELEGRAM_BOT_TOKEN в config/.env"
        me = self._call("getMe", _wait=25)
        if not me:
            return "Telegram не ответил — проверь интернет и токен"
        self.me = me.get("username", "")
        if not self.owner:
            return (f"бот @{self.me} на связи, но не знает хозяина. Напиши ему что угодно — "
                    "он подскажет твой номер, впиши его в phone.owner_id")
        return f"бот @{self.me} на связи, хозяин {self.owner}"

    # ---------- отправка ----------
    def send(self, text: str, voice: bool = False, chat: int = 0):
        chat = chat or self.owner
        if not (self.available and chat):
            return
        for piece in [text[i:i + MAX_TEXT] for i in range(0, len(text), MAX_TEXT)] or [""]:
            self._call("sendMessage", chat_id=chat, text=piece)
        if voice:
            self.send_voice(text, chat)

    def send_voice(self, text: str, chat: int = 0):
        """Ответ голосом — тем же голосом, которым он говорит вслух."""
        chat = chat or self.owner
        data = self._to_ogg(text)
        if data:
            self._call("sendVoice", chat_id=chat, _wait=60,
                       _files={"voice": ("jarvis.ogg", data, "audio/ogg")})

    def _to_ogg(self, text: str):
        """Синтез в ogg/opus — в таком виде Telegram показывает это голосовым."""
        try:
            import av
            import numpy as np
            synth = self.j.voice.primary or self.j.voice.fallback
            if synth is None:
                return None
            pcm, rate = synth.synth(synth.prepare(text))
            pcm = (np.clip(np.asarray(pcm, dtype="float32"), -1, 1) * 32767).astype("<i2")
            buf = io.BytesIO()
            with av.open(buf, "w", format="ogg") as out:
                stream = out.add_stream("libopus", rate=rate)
                stream.layout = "mono"
                frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="s16",
                                                   layout="mono")
                frame.rate = rate
                for packet in stream.encode(frame):
                    out.mux(packet)
                for packet in stream.encode(None):
                    out.mux(packet)
            return buf.getvalue()
        except Exception as e:
            log.write("error", f"[телефон] голосовой ответ: {type(e).__name__} {str(e)[:90]}")
            return None

    def send_file(self, path: str, chat: int = 0) -> str:
        """Прислать файл с компьютера в чат хозяина.

        Ровно то, о чём хозяин просил для телефона: «достань мне файл». Боту
        Telegram разрешено присылать до 50 МБ; больше — честно говорим, что
        не пролезет, а не делаем вид, что отправили.
        """
        import os
        chat = chat or self.owner
        if not (self.available and chat):
            return "Телефон не подключён: нужен токен бота и номер твоего чата в настройках."
        if not os.path.exists(path):
            return f"Файла {os.path.basename(path)} уже нет на месте."
        size = os.path.getsize(path)
        if size > 50 * 1024 * 1024:
            return (f"{os.path.basename(path)} весит {size / 1024 ** 2:.0f} МБ, а Telegram "
                    "принимает от бота до 50 — не пролезет.")
        with open(path, "rb") as f:
            ok = self._call("sendDocument", chat_id=chat, _wait=300,
                            caption=os.path.basename(path)[:200],
                            _files={"document": (os.path.basename(path), f)})
        if ok is None:
            return f"Не смог отправить {os.path.basename(path)} — Telegram не принял."
        return f"Отправил {os.path.basename(path)} тебе в Telegram."

    def notify(self, text: str):
        """Напоминание или предупреждение — в телефон, если так настроено."""
        if self.push and self.available and self.owner:
            self.send(text)

    # ---------- приём ----------
    def _download(self, file_id: str):
        info = self._call("getFile", file_id=file_id)
        if not info or not info.get("file_path"):
            return None
        try:
            url = f"{API}/file/bot{self.token}/{info['file_path']}"
            return self.session.get(url, timeout=60).content
        except Exception as e:
            log.write("error", f"[телефон] загрузка файла: {str(e)[:90]}")
            return None

    def _voice_to_text(self, file_id: str) -> str:
        """Голосовое из Telegram — тем же распознавателем, что слушает микрофон."""
        if not getattr(self.j, "ears", None):
            return ""
        data = self._download(file_id)
        if not data:
            return ""
        try:
            import av
            import numpy as np
            with av.open(io.BytesIO(data)) as container:
                stream = container.streams.audio[0]
                rate = stream.rate
                frames = [f.to_ndarray() for f in container.decode(stream)]
            pcm = np.concatenate([f.mean(axis=0) if f.ndim > 1 else f.ravel() for f in frames])
            pcm = pcm.astype("float32")
            if pcm.max() > 1.5:                       # пришло целыми числами
                pcm /= 32768.0
            if rate != 16000:                         # распознаватель работает на 16 кГц
                idx = np.round(np.arange(0, len(pcm), rate / 16000)).astype(int)
                pcm = pcm[idx[idx < len(pcm)]]
            return self.j.ears.transcribe(pcm) or ""
        except Exception as e:
            log.write("error", f"[телефон] разбор голосового: {type(e).__name__} {str(e)[:90]}")
            return ""

    def _stranger(self, chat: int):
        self.send("Это личный ассистент, он отвечает только хозяину.\n"
                  f"Если это ты — впиши номер {chat} в config/settings.json, "
                  "раздел phone, поле owner_id.", chat=chat)
        log.write("info", f"[телефон] чужой чат {chat} — не отвечаю")

    def _handle(self, message: dict):
        chat = (message.get("chat") or {}).get("id", 0)
        if not chat:
            return
        if not self.owner or chat != self.owner:
            self._stranger(chat)
            return

        was_voice = bool(message.get("voice") or message.get("audio"))
        if was_voice:
            self._call("sendChatAction", chat_id=chat, action="typing")
            blob = message.get("voice") or message.get("audio")
            text = self._voice_to_text(blob.get("file_id", ""))
            if not text:
                self.send("Голосовое не разобрал. Напиши словами?")
                return
            self.send(f"Услышал: {text}")
        else:
            text = (message.get("text") or "").strip()
        if not text:
            return
        if text.startswith("/"):
            text = {"/start": "привет", "/help": "что ты умеешь",
                    "/tasks": "какие у меня задачи"}.get(text.split()[0], text.lstrip("/"))

        self._call("sendChatAction", chat_id=chat, action="typing")
        log.write("info", f"[телефон] {text[:80]}")
        answer = self.j.answer_text(text, source="phone")
        speak = self.voice_replies == "always" or (self.voice_replies == "auto" and was_voice)
        self.send(answer or "Сделал.", voice=speak)

    def _poll_loop(self):
        while not self._stop.is_set():
            updates = self._call("getUpdates", _wait=POLL_TIMEOUT + 10,
                                 offset=self._offset, timeout=POLL_TIMEOUT,
                                 allowed_updates='["message"]')
            if updates is None:
                time.sleep(5)                         # связь дрогнула — не долбим
                continue
            for upd in updates:
                self._offset = upd["update_id"] + 1
                message = upd.get("message")
                if not message:
                    continue
                try:
                    self._handle(message)
                except Exception as e:
                    log.write("error", f"[телефон] обработка: {type(e).__name__} {str(e)[:90]}")
                    self.send("Споткнулся на этом. Посмотри журнал.")

    def start(self) -> bool:
        if not self.available:
            return False
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
