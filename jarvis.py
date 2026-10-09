# -*- coding: utf-8 -*-
"""Джарвис — голосовой ассистент с полным доступом к компьютеру.

Запуск:
    jarvis.bat            — голосовой режим (слушает постоянно)
    jarvis.bat --text     — текстовый режим, набираешь команды руками
    jarvis.bat --once "команда"

Как он слушает. Микрофон открыт всегда, но разбирается на этом компьютере, и
Джарвис реагирует только на обращение по имени или Ctrl+Alt+J.

Услышав имя, он открывает живой разговор (core/live.py): модель слушает голос
и отвечает голосом, её можно перебивать, имя больше не нужно. Замолчали на
25 секунд или попрощались — разговор закрыт, Джарвис снова ждёт обращения.

Нет интернета или ключа — работает по-старому: распознать фразу, разобрать
правилами, при необходимости спросить текстовую модель, озвучить. После
обращения 30 секунд можно командовать подряд без имени.
"""
import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import config, log, memory, router
from core.voice import Voice

BANNER = r"""
   ___  _____   ___  _   _ ___ ___
  |_  |/ _ \ \ / / _\| | | |_ _/ __|   голосовой ассистент
   _| | (_) \ V /  _ \ |_| || |\__ \   доступ к компьютеру: полный
  |___|\___/ |_| |_| |_\___/|___|___/  опасное — только с подтверждения
"""

DIALOG_WINDOW = 30      # секунд после обращения, когда имя можно не повторять
LIVE_COOLDOWN = 600     # после сбоя живого режима не долбим сервер 10 минут
DISK_WARN_GB = 3.0      # меньше — Windows уже тормозит и не ставит обновления
# Дольше этого думает — скажем «Секунду», чтобы не висела тишина. Два с лишним:
# само слово звучит почти секунду, и на быстром ответе оно только мешает
FILLER_AFTER = 2.0
# Что и когда уже сказано по своей инициативе — живёт через перезапуски
ANNOUNCED = config.DATA / "brain" / ("announced.test.json" if log.TAG else "announced.json")


def _announced(key: str, within: float) -> bool:
    """Говорил ли это недавно — даже если Джарвиса с тех пор перезапускали."""
    import json
    try:
        return time.time() - json.loads(ANNOUNCED.read_text(encoding="utf-8")).get(key, 0) < within
    except (OSError, ValueError):
        return False


def _mark_announced(key: str):
    import json
    try:
        data = json.loads(ANNOUNCED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data[key] = time.time()
    try:
        ANNOUNCED.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def ring_phrase(t: dict) -> str:
    """Звонок будильника. Со временем: в телефоне сообщение читают позже, чем оно пришло."""
    from datetime import datetime
    if t.get("timer"):
        return "Время вышло."
    return f"Напоминаю: {t['text']} — {datetime.fromisoformat(t['when']):%H:%M}."


def late_phrases(late: list, at_start: bool, now=None) -> list:
    """Что сказать про напоминания, проскочившие окно будильника.

    При запуске — одной фразой «пока меня не было». На ходу опоздание в пару
    минут (круг будильника затянулся) звонит как обычно, а большое значит, что
    компьютер спал: так и сказать, иначе «Напоминаю: в 19:50» в девять вечера
    звучит как ошибка.

    Пары (фраза, задача): задача — для кнопок «Сделано/отложить» в телефоне;
    у сводки про несколько дел её нет — кнопки были бы непонятно к чему.
    """
    from datetime import datetime
    now = now or datetime.now()
    when = lambda t: datetime.fromisoformat(t["when"])
    out = []
    if not at_start:
        out = [(ring_phrase(t), t) for t in late if (now - when(t)).total_seconds() < 600]
        late = [t for t in late if (now - when(t)).total_seconds() >= 600]
    if late:
        parts = [f"«{t['do']}» — {memory.when_phrase(when(t))} (не выполнил)" if t.get("do")
                 else f"{t['text']} — {memory.when_phrase(when(t))}" for t in late[:3]]
        more = f" И ещё {len(late) - 3}." if len(late) > 3 else ""
        lead = ("Пока меня не было, ты просил напомнить" if at_start
                else "Опоздал: компьютер, похоже, спал. Ты просил напомнить")
        out.append((f"{lead}: {'; '.join(parts)}.{more}", late[0] if len(late) == 1 else None))
    return out


class Jarvis:
    def __init__(self, voice_mode: bool = True):
        self.cfg = config.CFG
        self.voice = Voice(self.cfg)
        self.voice_mode = voice_mode
        self.ears = None
        self.brain = None
        self.awake_until = 0.0
        self.pending = None            # (описание, функция) — ждёт «да»
        self.pending_from = ""         # где спросили: voice или phone
        self._quiet = False            # отвечаем текстом, не вслух (запрос с телефона)
        self._answer = []              # собранный текст ответа
        self._talk_lock = threading.Lock()
        self.phone = None
        self.running = True
        self.paused = False            # трей и Ctrl+Alt+P
        self.tray = None
        self.hotkeys = None
        self.live = None               # живой разговор, поднимается в голосовом режиме
        self.live_request = False      # Ctrl+Alt+J — открыть разговор без имени
        self.live_off_until = 0.0      # пауза после сбоя живого режима
        self._vpn_told = 0.0           # когда говорил, что Gemini не пускает без VPN
        log.cleanup()                  # журналы старше двух недель ни к чему
        self._init_brain()

    # ---------- трей и горячие клавиши ----------
    def _init_tray(self):
        try:
            from core.tray import Tray, AVAILABLE
            if not AVAILABLE:
                return
            self.tray = Tray(self)
            if self.tray.start():
                print("[трей] иконка рядом с часами")
        except Exception as e:
            print(f"[трей] не поднялся: {e}")
            self.tray = None

    def _init_hotkeys(self):
        try:
            from core.hotkey import HotkeyListener
            hk = HotkeyListener()
            hk.add("ctrl+alt+j", self._hk_wake, "Ctrl+Alt+J — позвать")
            hk.add("ctrl+alt+s", self._hk_stop, "Ctrl+Alt+S — замолчать")
            hk.add("ctrl+alt+p", self._hk_pause, "Ctrl+Alt+P — пауза")
            if hk.start():
                self.hotkeys = hk
        except Exception as e:
            print(f"[клавиши] не поднялись: {e}")

    def _hk_wake(self):
        """Позвать молча: открывает разговор, имя произносить не нужно."""
        if self.paused:
            self.paused = False
            self._set_tray("listen")
        if self._live_ready():
            if not self.live.active:
                self.live_request = True
                if self.ears:
                    self.ears.interrupt.set()    # не ждать фразу, открыть разговор сразу
            return
        self.awake_until = time.time() + DIALOG_WINDOW
        self.voice.say("Да?")

    def _hk_stop(self):
        if self.live and self.live.active:
            self.live.stop_speaking()           # умолкнуть, но разговор не рвать
            return
        self.voice.stop()
        self.awake_until = 0

    def _hk_pause(self):
        if self.tray:
            self.tray._toggle_pause()
        else:
            self.paused = not self.paused
            self.say("Пауза." if self.paused else "Снова слушаю.")

    def _set_tray(self, state: str):
        if self.tray:
            self.tray.set_state(state)

    def _init_brain(self):
        try:
            from core.brain import Brain
            from core.local_brain import HybridBrain
            # Облако, пока отвечает; упало — своя модель на видеокарте (core/local_brain.py)
            self.brain = HybridBrain(Brain(self.cfg), self.cfg)
        except Exception as e:
            print(f"[brain] не поднялся: {e}")
            self.brain = None
        # «Подключи обученную модель»: проверка в фоне выгружает свою модель и
        # потом рассказывает, чем кончилось (skills/training.py)
        from skills import training
        training.NOTIFY = self.notify
        training.LOCAL = getattr(self.brain, "local", None)
        try:
            # Список файлов на дисках — в фоне: обойти D: с холодного диска
            # занимает до двадцати секунд, а искать по готовому — мгновенно
            from skills import files
            files.start_background()
        except Exception as e:
            print(f"[файлы] список не строится: {e}")
        try:
            # Что занимает место на C: — тоже в фоне: обход диска идёт около минуты
            from skills import diskspace
            diskspace.start_background()
        except Exception as e:
            print(f"[диск] замер не идёт: {e}")

    # ---------- речь ----------
    def say(self, text: str, aloud: bool = False):
        """aloud — вслух, даже пока отвечаем телефону. Тишина на время запроса с
        телефона общая для всех потоков, и напоминание, прозвеневшее в эти
        секунды, уходило в чужой ответ в чат, а в комнате молчало."""
        if not text:
            return
        quiet = self._quiet and not aloud
        memory.log_dialog("jarvis", text, via="Telegram" if quiet else "голос")
        log.said(text)
        if quiet:
            self._answer.append(text)     # спросили с телефона: ответ уходит в чат
            return
        self.voice.say(text)

    def answer_text(self, text: str, source: str = "phone") -> str:
        """Выполнить просьбу и вернуть ответ текстом, не говоря вслух.

        Нужно для телефона: хозяина нет у компьютера, и говорить в пустую комнату
        бессмысленно. Путь тот же, что у голоса — правила, потом мозг с
        инструментами, — меняется только куда уходит ответ.

        Замок на весь разговор: голос и телефон делят `pending` и историю мозга,
        и два запроса сразу перепутали бы, кто что подтверждал.
        """
        with self._talk_lock:
            self._quiet, self._answer = True, []
            try:
                self.process(text, from_voice=False)
            except Exception as e:
                log.write("error", f"[{source}] {type(e).__name__}: {str(e)[:120]}")
                self._answer.append("Споткнулся на этом. Подробности в журнале.")
            finally:
                self._quiet = False
                answer = " ".join(self._answer).strip()
                self._answer = []
        return answer

    def notify(self, text: str, task: dict = None):
        """Сказать от себя: посреди живого разговора — голосом модели, иначе обычным.

        Напоминание не должно перебивать разговор чужим голосом: оно встраивается
        в сам разговор, и модель передаёт его своими словами. task — задача, о
        которой напоминаем: в телефоне под ней будут кнопки «Сделано» и «отложить».
        """
        if self.phone:
            self.phone.notify(text, task)  # дома может никого не быть — пусть дойдёт в телефон
        if self.live and self.live.active:
            if self.live.inject(f"(Система напоминаний, не хозяин: передай ему своими словами — {text})"):
                log.write("info", f"напоминание в разговор: {text}")
                return
        self.say(text, aloud=True)        # в телефон уже ушло выше

    # ---------- живой разговор ----------
    def _live_ready(self) -> bool:
        return bool(self.live and self.live.available and time.time() >= self.live_off_until)

    def _converse(self, audio=None, reason: str = "name") -> bool:
        """Живой разговор. Возвращает False, если пора выключаться."""
        self.voice.stop()
        self.awake_until = 0
        self._set_tray("think")
        print(f"\n🎙 разговор ({'по имени' if reason == 'name' else 'по клавише'})")
        result = self.live.run(first_audio=audio, reason=reason)
        self.ears.flush()
        self.ears.interrupt.clear()
        self._set_tray("listen")
        print(f"🎙 разговор закрыт ({result})\n")

        if not result.startswith("error"):
            return result != "shutdown"

        # Страховка: сервер не ответил или кончился лимит. Если модель так ничего и
        # не сказала — отвечаем по-старому, чтобы просьба не пропала.
        self.live_off_until = time.time() + LIVE_COOLDOWN
        print(f"[живой разговор] недоступен 10 минут: {result[:160]}")
        # Gemini не пускает из России без VPN (1007, 06.10.2026). Джарвис молча
        # становился «глупее» — пусть скажет почему, не чаще раза в полчаса
        if "location is not supported" in result.lower() and time.time() - self._vpn_told > 1800:
            self._vpn_told = time.time()
            self.say("Gemini не пускает из этой страны — похоже, выключен VPN. Пока отвечаю сам, попроще.")
        if self.live.t_first_audio is not None:
            return True
        if audio is None:
            self.awake_until = time.time() + DIALOG_WINDOW
            self.say("Да?")
            return True
        text = self.ears.transcribe(audio)
        # По имени уже позвали — это и открыло разговор. Вторая расшифровка
        # может исказить имя («Джарус»), и без открытого окна просьба молча
        # отбрасывалась бы как сказанная не Джарвису
        self.awake_until = time.time() + DIALOG_WINDOW
        return self.process(text, from_voice=True) if text else True

    def _on_speech_start(self):
        """Человек заговорил — живой режим начинает подключаться, не дожидаясь конца фразы."""
        if self._live_ready() and not self.paused and not self.voice.speaking:
            self.live.prepare()

    def _handle_phrase(self, audio) -> bool:
        """Фраза с микрофона: ищем имя, открываем разговор или отвечаем по-старому."""
        live = self._live_ready()
        if live:
            # Шаг 1: имя в начале фразы — быстрая модель, полсекунды
            found, head = self.ears.quick_wake(audio)
            if found:
                self.ears.save(audio, f"[имя] {head}")
                return self._converse(audio, reason="name")

        # Шаг 2: фраза целиком — точная модель
        text = self.ears.transcribe(audio)
        if text:
            self.ears.save(audio, text)
        if live and text and router.has_wake(text):
            return self._converse(audio, reason="name")
        if self.live:
            self.live.discard()               # не обращение — заготовка не пригодится
        return self.process(text, from_voice=True) if text else True

    # ---------- обработка одной реплики ----------
    def process(self, text: str, from_voice: bool = True) -> bool:
        """Возвращает False, если пора выходить."""
        text = text.strip()
        if not text:
            return True

        wake = self.cfg["wake_words"]
        now = time.time()

        if from_voice:
            called = router.has_wake(text, wake)
            in_window = now < self.awake_until
            if not called and not in_window:
                print(f"   (мимо: {text})")
                return True
            if called:
                text = router.strip_wake(router.normalize(text), wake)
                if not text:
                    self.awake_until = now + DIALOG_WINDOW
                    self.say("Слушаю.")
                    return True
            self.awake_until = now + DIALOG_WINDOW

        print(f"👤 {text}")
        memory.log_dialog("user", text, via="Telegram" if self._quiet else "голос")
        log.heard(text)

        # ждём подтверждения опасного действия
        if self.pending:
            desc, action = self.pending
            # Подтверждают там, где спросили: «да», сказанное в комнату, не должно
            # закрывать вопрос, заданный с телефона, и наоборот
            source = "phone" if self._quiet else "voice"
            if self.pending_from and self.pending_from != source:
                self.say(f"Я спрашивал про «{desc}» {'голосом' if source == 'phone' else 'в телефоне'} — "
                         "подтверди там же.")
                return True
            if router.normalize(text) in ("да", "да давай", "подтверждаю", "выполняй",
                                          "конечно", "ага", "точно", "делай"):
                self.pending = None
                self.pending_from = ""
                self.say(str(action() or "Сделано."))
                return True
            self.pending = None
            self.pending_from = ""
            self.say("Отменил.")
            return True

        reply = router.handle(router.normalize(text), self.cfg)

        if reply.stop_speech:
            self.voice.stop()
            self.awake_until = 0
            return True
        if reply.quit:
            self.say(reply.say)
            self.voice.wait()
            return False
        if reply.pending:
            self.pending = (reply.pending_desc, reply.pending)
            self.pending_from = "phone" if self._quiet else "voice"
            self.say(reply.say)
            return True

        if reply.to_llm:
            if reply.say:                 # первые команды из нескольких уже выполнены правилами
                self.say(reply.say)
            if not self.brain or not self.brain.ready:
                self.say("Это уже за пределами простых команд, а умный режим не подключён. "
                         "Нужен ключ Gemini.")
                return True
            answer = self._think(reply.meta.get("llm_text", text))
            if self.brain.pending_confirm:
                self.pending = self.brain.pending_confirm
                self.pending_from = "phone" if self._quiet else "voice"
                self.brain.pending_confirm = None
            self.say(answer)
            return True

        self.say(reply.say)
        return True

    def _init_phone(self):
        """Поднять связь с телефоном, если бот настроен."""
        try:
            from core.phone import Phone
            phone = Phone(self)
            if not phone.available:
                return
            status = phone.check()
            print(f"[телефон] {status}")
            if phone.start():
                self.phone = phone
                self._pair_hint = phone.pairing_hint()     # скажем после приветствия
                # Инструменты получают облачный мозг — пусть знает про телефон
                target = getattr(self.brain, "cloud", self.brain)
                if target is not None:
                    target.phone = phone
                log.write("info", f"[телефон] {status}")
        except Exception as e:
            print(f"[телефон] не поднялся: {e}")

    def _think(self, text: str) -> str:
        """Спросить мозг, а «Секунду» сказать только если он правда задумался.

        Раньше это звучало перед каждым ответом — на показе 02.10.2026 вышло
        заикание: «Секунду… Открываю», и так двадцать раз. Короткий ответ
        приходит быстрее, чем успеваешь это произнести, так что слово нужно
        только когда ждать действительно приходится.
        """
        result = {}

        def ask():
            try:
                result["a"] = self.brain.ask(text)
            except Exception as e:                # иначе падение мозга выглядело как пустой ответ
                log.write("error", f"[мозг] {type(e).__name__}: {str(e)[:120]}")
        worker = threading.Thread(target=ask, daemon=True)
        worker.start()
        worker.join(FILLER_AFTER)
        if worker.is_alive():
            if not self._quiet:           # в чате «Секунду.» перед ответом — лишнее
                self.say("Секунду.")
            # Ждать ответа — всегда. 07.10.2026 ожидание стояло под тем же
            # условием, и телефон через 2 секунды получал «Не получилось ответить»,
            # а мозг тем временем молча записывал дело и находил список планов
            worker.join()
        return result.get("a") or ("Не получилось ответить: умный режим промолчал. "
                                   "Простые команды — дела, видео, программы — работают и так.")

    # ---------- фоновые напоминания ----------
    def _check_training_result(self):
        """Обучение в Colab закончилось — файл молча лёг в «Загрузки»: сказать об этом.

        Раз в минуту и только про файл, о котором ещё не говорили (по его имени и
        времени): хозяин ждёт результата обучения часами, а браузер о нём молчит.
        """
        now = time.time()
        if now - getattr(self, "_lora_checked", 0) < 60:
            return
        self._lora_checked = now
        try:
            sys.path.insert(0, str(config.ROOT))
            from train.install_lora import find_download
            src = find_download()
            if not src or now - src.stat().st_mtime > 6 * 3600:
                return
            key = f"lora:{src.name}:{int(src.stat().st_mtime)}"
            if _announced(key, 30 * 24 * 3600):
                return
            _mark_announced(key)
        except Exception:
            return
        self.notify("Обучение закончилось: файл модели пришёл в «Загрузки». Скажи «подключи обученную "
                    "модель» — сравню с исходной и подключу, если стала лучше.")

    def _check_disk(self):
        """Предупредить, если на системном диске почти не осталось места.

        Помощник должен говорить о беде сам, а не ждать вопроса. 05.10.2026 на
        диске C: у хозяина оставалось 1,5 ГБ — при таком остатке Windows
        тормозит, не ставит обновления и может уронить файл подкачки, а Джарвис
        знал и молчал. Предупреждаем не чаще раза в шесть часов, чтобы не нудить.
        """
        from skills import cleanup as CL
        from skills import diskspace as DS
        try:
            free, _total = CL.free_space("C:")
        except Exception:
            return
        gb = free / 1024 ** 3
        now = time.time()
        # Не чаще раза в шесть часов — и через перезапуски: хозяин закрывает и
        # открывает Джарвиса по нескольку раз в день, и предупреждение звучало каждый раз
        if gb >= DISK_WARN_GB or _announced("disk", 6 * 3600):
            return
        # Сказать сразу, куда ушло место: «почисти временные файлы» при 74 ГБ
        # игры на диске — не помощь. Замер идёт в фоне около минуты; первые три
        # минуты после запуска ждём его, дальше предупреждаем и без него
        hint = DS.top_phrase()
        self._disk_check_since = getattr(self, "_disk_check_since", None) or now
        if not hint and now - self._disk_check_since < 180:
            return
        _mark_announced("disk")
        amount = f"{gb:.1f}".replace(".", ",")          # «1,7» — по-русски, а не «один точка семь»
        self.notify(f"На диске C осталось {amount} гигабайта — это мало, Windows может начать "
                    f"тормозить. {hint + ' ' if hint else ''}Скажи «почисти диск» — уберу мусор, "
                    "или «что занимает место» — расскажу подробнее.")

    def _tell_today(self):
        """Что впереди за сегодня — одной фразой, и только если есть что сказать.

        Помощник полезен, когда сам говорит о близком, а не ждёт вопроса. Но
        болтать при каждом запуске он не должен: пустой день — молчим.
        """
        from datetime import datetime
        from skills import lessons
        bits = []
        try:
            now = datetime.now()
            ahead = [t for t in memory._load(memory.TASKS, [])
                     if not t["done"] and not t.get("timer") and t["when"]
                     and now <= datetime.fromisoformat(t["when"])
                     and datetime.fromisoformat(t["when"]).date() == now.date()]
            ahead.sort(key=lambda t: t["when"])
            if ahead:
                near = ", ".join(f"{t['text']} в {datetime.fromisoformat(t['when']):%H:%M}"
                                 for t in ahead[:2])
                tail = f" и ещё {len(ahead) - 2}" if len(ahead) > 2 else ""
                bits.append(f"сегодня {near}{tail}")
        except Exception as e:
            print(f"[план дня] задачи: {e}")
        try:
            # Время занятия — в поле at (datetime). Прежняя проверка смотрела в
            # несуществующее time, и уроки в плане дня не звучали никогда
            today = lessons._planned_for(datetime.now().date())
            upcoming = [it for it in today if it["at"] >= datetime.now()]
            if upcoming:
                bits.append(f"уроков впереди {len(upcoming)}, первый в {upcoming[0]['at']:%H:%M}")
        except Exception as e:
            print(f"[план дня] уроки: {e}")
        if bits and not _announced("today", 3 * 3600):
            _mark_announced("today")
            self.say("Из плана: " + "; ".join(bits) + ".")

    def _tell_overdue(self, at_start: bool = False):
        """Сказать про напоминания, которые прозвенели бы без меня.

        Через notify, а не say: Джарвиса включили, а хозяина дома может и не быть.
        """
        from datetime import datetime
        try:
            late = memory.overdue()
        except Exception as e:
            print(f"[будильник] просроченные: {e}")
            return
        # Отложенная команда, опоздавшая на минуты, ещё к месту — выполняем.
        # Опоздавшую на часы (компьютер спал) — не выполняем, а говорим об этом
        for t in [t for t in late if t.get("do")]:
            if (datetime.now() - datetime.fromisoformat(t["when"])).total_seconds() < 600:
                late.remove(t)
                self._run_planned(t)
        for text, task in late_phrases(late, at_start):
            self.notify(text, task)

    def _run_planned(self, t: dict):
        """Отложенная команда пришла в срок: выполнить, как будто сказана сейчас.

        Опасное («выключи», «удали») без хозяина не делаем: в срок его может не
        быть рядом, чтобы сказать «да», — честно говорим, что ждёт подтверждения.
        """
        cmd = t["do"]
        memory.finish(t["id"])                      # второй раз не выполнится
        log.write("info", f"[по плану] {cmd}")
        try:
            with self._talk_lock:
                reply = router.handle(router.normalize(cmd), self.cfg)
                if reply.pending:
                    result = "это нужно подтвердить — скажи ещё раз, если всё ещё нужно"
                elif reply.to_llm and self.brain and self.brain.ready:
                    result = " ".join(filter(None, [reply.say, self._think(reply.meta.get("llm_text", cmd))]))
                    if self.brain.pending_confirm:
                        self.brain.pending_confirm = None
                        result = "это нужно подтвердить — скажи ещё раз, если всё ещё нужно"
                elif reply.to_llm:
                    result = "так я не умею без умного режима"
                else:
                    result = reply.say or "сделано"
        except Exception as e:
            log.write("error", f"[по плану] {cmd}: {type(e).__name__} {str(e)[:90]}")
            result = "не получилось — посмотри журнал"
        self.notify(f"По плану: {cmd}. {result[:1].upper() + result[1:]}")

    def _reminder_loop(self):
        # 10 секунд, а не 30: таймер, опоздавший на полминуты, уже бесполезен
        from skills import lessons
        self.voice.wait()                 # сначала поздороваться, потом докладывать
        self._tell_overdue(at_start=True)
        self._tell_today()
        while self.running:
            try:
                for t in memory.due_now(window_min=0.2):
                    if t.get("do"):
                        self._run_planned(t)
                    else:
                        self.notify(ring_phrase(t), t)
            except Exception as e:
                print(f"[будильник] {e}")
            # Срок проскочил окно: компьютер спал или круг затянулся
            self._tell_overdue()

            try:
                # Урок начинается — предупредить заранее, чтобы успеть открыть доску
                for it in lessons.due_soon(minutes=10):
                    name = lessons.decline(it["name"], "тв")
                    self.notify(f"Через {it['left']} минут урок с {name}.")
            except Exception as e:
                print(f"[уроки] {e}")

            self._check_disk()           # сам замолкает на шесть часов после предупреждения
            self._check_training_result()
            time.sleep(10)

    # ---------- режимы ----------
    def run_text(self):
        print(BANNER)
        print("Текстовый режим. Пиши команды, «выход» — закончить.\n")
        self.say("Джарвис на связи.")
        threading.Thread(target=self._reminder_loop, daemon=True).start()
        while self.running:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            if not self.process(line, from_voice=False):
                break
        self.running = False

    def run_voice(self):
        from core.ears import Ears
        print(BANNER)
        print("Поднимаю слух...")
        self.ears = Ears(self.cfg, str(config.MODELS))
        self.ears.start()
        self._init_tray()
        self._init_hotkeys()

        from core.live import LiveConversation
        self.live = LiveConversation(self)
        self.ears.on_speech_start = self._on_speech_start

        name = self.cfg["name"]
        if self.live.available:
            print(f"\nГотов. Скажи «{name}» и говори как с человеком — дальше без имени.")
            print("Живой разговор: закрывается после 25 секунд тишины или «пока».")
        else:
            print(f"\nГотов. Скажи «{name}» и команду. (Живой разговор выключен: нет ключа "
                  "Gemini или библиотеки google-genai.)")
        print("Ctrl+Alt+J — позвать молча · Ctrl+Alt+S — замолчать · Ctrl+Alt+P — пауза")
        print("Ctrl+C — выход\n")
        self._init_phone()
        self.say(f"{name} на связи. Слушаю.")
        if getattr(self, "_pair_hint", ""):
            self.say(self._pair_hint)
        # Будильник поднимаем после приветствия: иначе просроченное напоминание
        # звучало раньше «Джарвис на связи» — как будто он заговорил посреди фразы
        threading.Thread(target=self._reminder_loop, daemon=True).start()

        try:
            while self.running:
                # На паузе микрофон не разбираем — просто выбрасываем звук,
                # иначе очередь распухнет и он «догонит» старыми фразами
                if self.paused:
                    self.ears.flush()
                    time.sleep(0.4)
                    continue

                # Пока говорит сам — не слушаем: через колонки он услышал бы
                # собственный голос и ответил сам себе.
                if self.voice.speaking:
                    self.voice.wait()
                    time.sleep(0.25)          # хвост эха в комнате
                    self.ears.flush()
                    self._set_tray("listen")

                if self.live_request:
                    self.live_request = False
                    if not self._converse(None, reason="hotkey"):
                        break
                    continue

                try:
                    audio = self.ears.listen_phrase()
                except Exception as e:
                    print(f"[слух] сбой: {e}")
                    log.error("слух", e)
                    time.sleep(1)
                    continue

                if audio is None or self.paused or self.live_request:
                    if self.live and not self.live_request:
                        self.live.discard()       # щелчок или пауза — заготовка не нужна
                    continue

                try:
                    self._set_tray("think")
                    ok = self._handle_phrase(audio)
                    self._set_tray("listen")
                    if not ok:
                        break
                except Exception as e:
                    # Одна кривая команда не должна ронять ассистента целиком
                    print(f"[обработка] сбой: {e}")
                    log.error("обработка", e)
                    self._set_tray("listen")
                    self.say("Что-то пошло не так, но я на месте.")
        except KeyboardInterrupt:
            print("\nостановлен с клавиатуры")
        finally:
            self.running = False
            if self.ears:
                self.ears.stop()
            if self.hotkeys:
                self.hotkeys.stop()
            if self.tray:
                self.tray.stop()


_MUTEX = None


def _single_instance() -> bool:
    """Первый ли это голосовой Джарвис на компьютере.

    Два сразу — беда: оба слушают один микрофон и отвечают хором, а бот в
    Telegram отдаёт сообщения только одному из них (второй получает «409»).
    Второй запуск случается легко: автозапуск плюс ярлык, двойной щелчок.
    """
    global _MUTEX
    try:
        import win32api
        import win32event
        import winerror
    except ImportError:
        return True
    _MUTEX = win32event.CreateMutex(None, False, "Local\\JarvisVoiceAssistant")
    return win32api.GetLastError() != winerror.ERROR_ALREADY_EXISTS


def main():
    config.setup_console()
    ap = argparse.ArgumentParser(description="Джарвис")
    ap.add_argument("--text", action="store_true", help="текстовый режим без микрофона")
    ap.add_argument("--once", metavar="КОМАНДА", help="выполнить одну команду и выйти")
    args = ap.parse_args()

    if not args.text and not args.once and not _single_instance():
        print("Джарвис уже запущен — второй не нужен: окно «Jarvis» или иконка у часов.")
        try:
            import win32gui
            hwnd = win32gui.FindWindow(None, "Jarvis")
            if hwnd:
                win32gui.ShowWindow(hwnd, 9)          # SW_RESTORE
                win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        time.sleep(3)                                 # чтобы успеть прочитать, почему окно закрылось
        return

    j = Jarvis(voice_mode=not args.text)

    if args.once:
        j.process(args.once, from_voice=False)
        j.voice.wait()
        return
    if args.text:
        j.run_text()
    else:
        j.run_voice()


if __name__ == "__main__":
    main()
