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
  нашедший бота, получил бы доступ к компьютеру. Хозяином становится тот, кто
  пришлёт боту код, названный Джарвисом на компьютере: код знает только
  сидящий рядом, а подобрать его не дадут — пять промахов, и чат не слушаем.

* Опасное действие подтверждается там же, где спрошено: подтверждение с
  телефона не закрывает вопрос, заданный голосом, и наоборот.

* Дела и заметки висят в чате закреплённым сообщением и правятся на месте.
  Telegram хранит переписку на телефоне — так заметки видны и без интернета,
  без отдельного приложения (sync_digest, команда /notes).
"""
import io
import json
import secrets
import threading
import time

import requests

from core import config, log

CURRENT = None             # запущенный телефон — чтобы на «как подключить телефон» ответить кодом


def pending_hint() -> str:
    """Строчка для модели, пока телефон не привязан.

    В живом разговоре фразы идут прямо в Gemini, мимо правил. 07.10.2026 на
    «как подключить телефон» модель, не зная про код, посоветовала «скажи боту
    /start и пришли, что он ответит». Теперь код она видит в контексте.
    """
    p = CURRENT
    if p and p.pair_code and not p.owner:
        name = f" @{p.me}" if p.me else ""
        return (f"Телефон ещё не подключён. Чтобы подключить, хозяину нужно отправить в Telegram "
                f"боту{name} код {' '.join(p.pair_code)} — и всё, больше ничего не нужно.")
    return ""


def connected_hint() -> str:
    """Строчка для модели, когда телефон подключён: что через него можно.

    Без неё на «добавь мне в телеграм» модель звала инструменты личного
    Telegram хозяина (они не подключены), получала «Telegram не подключён» и
    говорила, что телефона нет, — хотя бот работал (07.10.2026).
    """
    p = CURRENT
    if not (p and p.owner and p.available):
        return ""
    name = f" @{p.me}" if p.me else ""
    text = (f"Телефон хозяина подключён: бот{name} в Telegram. Напоминания из дел сами приходят "
            "туда в срок, дела и заметки висят там закреплённым сообщением и обновляются сами. "
            "Написать хозяину на телефон — telegram_send с chat='me', уходит сразу; прислать "
            "файл — send_file.")
    try:
        from skills import telegram as TG
        if not TG.ready():
            text += (" Личный Telegram хозяина (его чаты с людьми) не подключён — это другое, "
                     "читать и писать людям пока нельзя.")
    except Exception:
        pass
    return text

API = "https://api.telegram.org"
POLL_TIMEOUT = 25          # длинный опрос: соединение висит, пока нет сообщений
MAX_TEXT = 3900            # предел сообщения в Telegram — 4096, оставляем запас
DIGEST_EVERY = 60          # сводку сверяем раз в минуту, правим — только если поменялась
PAIR_TRIES = 5             # промахов с кодом привязки, после которых чат не слушаем


class Phone:
    STATE = config.DATA / "brain" / "phone_digest.json"   # какое сообщение закреплено

    def __init__(self, jarvis):
        self.j = jarvis
        cfg = jarvis.cfg.get("phone", {})
        self.enabled = cfg.get("enabled", True)
        self.owner = int(cfg.get("owner_id", 0) or 0)
        self.voice_replies = cfg.get("voice_replies", "auto")   # auto | always | never
        self.push = cfg.get("push_reminders", True)
        self.pinned = cfg.get("pinned_digest", True)           # сводка заметок в закрепе
        self.confirm_tasks = cfg.get("confirm_tasks", True)    # «Записал: … — в 20:00» в чат
        self.token = config.env("TELEGRAM_BOT_TOKEN")
        self.session = requests.Session()
        self._offset = 0
        self._stop = threading.Event()
        self._thread = None
        self.me = ""
        # Пока хозяин не известен — код привязки. Его называет Джарвис на
        # компьютере, значит, знает только тот, кто рядом с ним. Раньше номер
        # чата надо было вписывать в настройки руками — у клиента это тупик
        self.pair_code = "" if self.owner else f"{secrets.randbelow(10 ** 6):06d}"
        self._pair_fails = {}

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
            return f"бот @{self.me} на связи и ждёт хозяина: отправь ему код {self.pair_code}"
        return f"бот @{self.me} на связи, хозяин {self.owner}"

    @staticmethod
    def status_phrase() -> str:
        """Ответ на «как подключить телефон»: код, «уже подключён» или чего не хватает."""
        p = CURRENT
        if p is None:
            return ("Телефон не настроен: нужен бот. Создай его у @BotFather командой /newbot "
                    "и впиши токен в config/.env, строка TELEGRAM_BOT_TOKEN.")
        if p.pair_code and not p.owner:
            return p.pairing_hint()
        return f"Телефон уже подключён — пиши боту{' @' + p.me if p.me else ''}."

    def pairing_hint(self) -> str:
        """Что сказать вслух при запуске, пока бот не знает хозяина."""
        if not (self.available and self.pair_code):
            return ""
        name = f" @{self.me}" if self.me else ""
        # Цифры через пробел — так их прочтут по одной, а не «четыреста восемьдесят…»
        return f"Чтобы подключить телефон, отправь боту{name} код {' '.join(self.pair_code)}."

    def _pair(self, chat: int):
        """Код совпал: этот чат — хозяин. Запоминаем в настройках, код больше не действует."""
        self.owner, self.pair_code = chat, ""
        self.j.cfg.setdefault("phone", {})["owner_id"] = chat
        try:
            config.update_setting("phone.owner_id", chat)
        except OSError as e:
            log.write("error", f"[телефон] не сохранил хозяина: {e}")
        log.write("info", f"[телефон] привязан хозяин {chat}")
        self.send("Готово: теперь я слушаюсь только тебя. Пиши или наговаривай — сделаю на "
                  "компьютере. Дела и заметки закреплю здесь — их видно и без интернета.")
        self.sync_digest()
        try:
            self.j.say("Телефон подключён.")
        except Exception:
            pass

    # ---------- отправка ----------
    def send(self, text: str, voice: bool = False, chat: int = 0) -> bool:
        """Сообщение в чат. True — Telegram принял все части: по этому инструмент
        честно отвечает «отправил» или «не ушло»."""
        chat = chat or self.owner
        if not (self.available and chat):
            return False
        ok = True
        for piece in [text[i:i + MAX_TEXT] for i in range(0, len(text), MAX_TEXT)] or [""]:
            ok = self._call("sendMessage", chat_id=chat, text=piece) is not None and ok
        if voice:
            self.send_voice(text, chat)
        return ok

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

    # ---------- закреплённая сводка ----------
    def sync_digest(self, renew: bool = False) -> bool:
        """Заметки и дела в закреплённом сообщении — видны в Telegram и без интернета.

        Хозяин хотел, чтобы заметки были под рукой, даже когда сети нет, и без
        отдельного приложения из Google Play. Telegram хранит переписку на
        телефоне, поэтому одно закреплённое сообщение и есть такая книжка.
        Сообщение одно и правится на месте: лента не засоряется, а закреп всегда
        свежий. Правим, только когда содержимое поменялось. Удалил хозяин
        сообщение — пришлём новое и закрепим его.
        """
        if not (self.available and self.owner and self.pinned):
            return False
        import hashlib
        from datetime import datetime
        from core import memory
        body = memory.digest()
        digest_hash = hashlib.sha1(body.encode("utf-8")).hexdigest()
        state = self._state()
        if not renew and state.get("hash") == digest_hash and state.get("message_id"):
            return True
        text = f"📌 Джарвис: дела и заметки\nобновлено {datetime.now():%d.%m в %H:%M}\n\n{body}"
        message_id = state.get("message_id") if not renew else None
        if message_id and self._call("editMessageText", chat_id=self.owner,
                                     message_id=message_id, text=text) is None:
            message_id = None           # сообщение удалили или оно слишком старое
        if not message_id:
            sent = self._call("sendMessage", chat_id=self.owner, text=text,
                              disable_notification="true")
            if not sent:
                return False
            message_id = sent["message_id"]
            self._call("pinChatMessage", chat_id=self.owner, message_id=message_id,
                       disable_notification="true")
        state.update(message_id=message_id, hash=digest_hash)
        self._save_state(state)
        return True

    def _state(self) -> dict:
        try:
            return json.loads(self.STATE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(self, state: dict):
        try:
            self.STATE.parent.mkdir(parents=True, exist_ok=True)
            self.STATE.write_text(json.dumps(state), encoding="utf-8")
        except OSError:
            pass

    def _timed_tasks(self):
        from datetime import datetime
        from core import memory
        now = datetime.now()
        return [t for t in memory._load(memory.TASKS, [])
                if not t["done"] and not t.get("timer") and t.get("when")
                and datetime.fromisoformat(t["when"]) > now]

    def mark_tasks_seen(self):
        """Дела, о которых чат уже знает: записанные с телефона — ответ там уже есть."""
        state = self._state()
        seen = set(state.get("seen_tasks", [])) | {t["id"] for t in self._timed_tasks()}
        state["seen_tasks"] = sorted(seen)[-300:]
        self._save_state(state)

    def announce_new_tasks(self) -> int:
        """Новое дело со сроком — сразу сообщением в чат.

        Хозяин просил (07.10.2026), чтобы бот писал «вот это, в такое-то время».
        В срок напоминание и так приходит; а это — подтверждение, что записано
        верно, видное сразу, а не только в правке закрепа (о ней Telegram не
        уведомляет). Первый запуск ничего не объявляет: старое не новость.
        """
        if not (self.available and self.owner and self.confirm_tasks):
            return 0
        from datetime import datetime
        from core import memory
        state = self._state()
        if "seen_tasks" not in state:
            self.mark_tasks_seen()
            return 0
        seen = set(state["seen_tasks"])
        new = [t for t in self._timed_tasks() if t["id"] not in seen]
        for t in new:
            when = memory.when_phrase(datetime.fromisoformat(t["when"]))
            self.send(f"📌 Записал: {t['text']} — {when}. Напомню здесь.")
        if new:
            self.mark_tasks_seen()
        return len(new)

    def _digest_loop(self):
        while not self._stop.is_set():
            for step in (self.announce_new_tasks, self.sync_digest):
                try:
                    step()
                except Exception as e:
                    log.write("error", f"[телефон] {step.__name__}: {type(e).__name__} {str(e)[:90]}")
            self._stop.wait(DIGEST_EVERY)

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
        if self.pair_code and not self.owner:
            # Подбирать код бессмысленно: пять промахов — и чат больше не слушаем
            fails = self._pair_fails[chat] = self._pair_fails.get(chat, 0) + 1
            if fails > PAIR_TRIES:
                return
            self.send("Это личный ассистент. Если это ты — отправь код, который Джарвис "
                      "назвал на компьютере.", chat=chat)
        else:
            self.send("Это личный ассистент, он отвечает только хозяину.", chat=chat)
        log.write("info", f"[телефон] чужой чат {chat} — не отвечаю")

    def _handle(self, message: dict):
        chat = (message.get("chat") or {}).get("id", 0)
        if not chat:
            return
        if not self.owner:
            typed = (message.get("text") or "").replace(" ", "").strip()
            if (self.pair_code and self._pair_fails.get(chat, 0) <= PAIR_TRIES
                    and secrets.compare_digest(typed, self.pair_code)):
                self._pair(chat)
            else:
                self._stranger(chat)
            return
        if chat != self.owner:
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
        if text.split()[0] == "/notes":
            ok = self.sync_digest(renew=True)
            self.send("Закрепил свежую сводку дел и заметок — она видна и без интернета."
                      if ok else "Не вышло закрепить сводку — посмотри журнал.")
            return
        if text.startswith("/"):
            text = {"/start": "привет", "/help": "что ты умеешь",
                    "/tasks": "какие у меня задачи"}.get(text.split()[0], text.lstrip("/"))

        self._call("sendChatAction", chat_id=chat, action="typing")
        log.write("info", f"[телефон] {text[:80]}")
        answer = self.j.answer_text(text, source="phone")
        speak = self.voice_replies == "always" or (self.voice_replies == "auto" and was_voice)
        self.send(answer or "Сделал.", voice=speak)
        self.mark_tasks_seen()      # записанное с телефона уже подтверждено ответом
        self.sync_digest()          # записал с телефона — закреп сразу свежий

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
        global CURRENT
        if not self.available:
            return False
        CURRENT = self
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        threading.Thread(target=self._digest_loop, daemon=True).start()
        return True

    def stop(self):
        self._stop.set()
