# -*- coding: utf-8 -*-
"""Голос Джарвиса.

Движки по убыванию естественности:

edge    — нейросетевые голоса Microsoft (Дмитрий, Светлана). Звучат как живой
          диктор, сами правильно читают числа, время и английские названия.
          Бесплатно, нужен интернет. ~0.5–1 с на короткую фразу.
gemini  — голоса Google через ключ Gemini. Самые выразительные, но медленнее:
          длинная фраза синтезируется 7 секунд, а у бесплатного тарифа есть лимит.
silero  — локальная нейросеть, без интернета. Живой тест показал, что звучит
          механически, и сама не читает цифры — ей текст готовит speech_text.
sapi    — встроенная Windows-Ирина: последний рубеж, работает всегда.

Онлайн-голос откатывается на локальный сам: пропал интернет — Джарвис не
замолкает, а продолжает говорить Silero.

Длинная реплика режется на предложения. Два потока: один синтезирует куски
наперёд, другой проигрывает — первое предложение звучит, пока готовятся
следующие, и пауз между ними нет.
"""
import asyncio
import base64
import io
import queue
import re
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CHUNK_LIMIT = 220        # символов за один проход синтеза


def _split_sentences(text: str, limit: int = CHUNK_LIMIT):
    """Режем по предложениям: первое зазвучит раньше, а синтез не упрётся в предел."""
    sentences = re.split(r"(?<=[.!?;])\s+", text)
    chunks, cur = [], ""
    for s in sentences:
        while len(s) > limit:                        # предложение-простыня — режем по запятым
            cut = s.rfind(",", 0, limit)
            cut = cut if cut > 40 else s.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            chunks.append(s[:cut + 1].strip())
            s = s[cut + 1:].strip()
        # короткие предложения склеиваем: «Готово. Громкость тридцать.» — одним куском
        if cur and len(cur) + len(s) + 1 <= limit and len(cur) < 60:
            cur = f"{cur} {s}".strip()
        else:
            if cur:
                chunks.append(cur)
            cur = s
    if cur:
        chunks.append(cur)
    return [c for c in chunks if c.strip()]


# ================= синтезаторы =================
class _Synth:
    """Превращает текст в звук. Воспроизведением занимается Voice."""
    name = "?"
    local = True

    def prepare(self, text: str) -> str:
        return text

    def synth(self, text: str):
        """→ (numpy float32 моно, частота дискретизации)"""
        raise NotImplementedError


class EdgeSynth(_Synth):
    name = "edge"
    local = False

    def __init__(self, cfg):
        import edge_tts                               # noqa: F401 — проверяем, что стоит
        vc = cfg.get("voice", {})
        self.voice = vc.get("edge_voice", "ru-RU-DmitryNeural")
        self.rate = vc.get("edge_rate", "+0%")        # «+10%» — чуть быстрее

    def synth(self, text: str):
        import av
        import edge_tts
        import numpy as np

        async def fetch():
            import aiohttp
            # Только IPv4: на этой машине IPv6 не маршрутизируется, и первое
            # подключение без этого ждёт лишние полсекунды
            connector = aiohttp.TCPConnector(family=socket.AF_INET)
            out = bytearray()
            async for chunk in edge_tts.Communicate(text, self.voice, rate=self.rate,
                                                    connector=connector).stream():
                if chunk["type"] == "audio":
                    out.extend(chunk["data"])
            return bytes(out)

        data = asyncio.run(fetch())
        if not data:
            raise RuntimeError("Microsoft не прислал звук")
        with av.open(io.BytesIO(data)) as container:
            stream = container.streams.audio[0]
            rate = stream.rate
            frames = [f.to_ndarray() for f in container.decode(stream)]
        pcm = np.concatenate([f.mean(axis=0) if f.ndim > 1 else f for f in frames])
        return pcm.astype(np.float32), rate


class GeminiSynth(_Synth):
    name = "gemini"
    local = False
    MODELS = ["gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts"]

    def __init__(self, cfg):
        from core import config
        self.key = config.env("GEMINI_API_KEY")
        if not self.key:
            raise RuntimeError("нет ключа Gemini")
        self.voice = cfg.get("voice", {}).get("gemini_voice", "Charon")

    def synth(self, text: str):
        import numpy as np
        import requests
        import urllib3.util.connection as urllib3_conn
        urllib3_conn.allowed_gai_family = lambda: socket.AF_INET

        payload = {
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self.voice}}},
            },
        }
        last = ""
        for model in self.MODELS:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": self.key}, json=payload, timeout=60)
            if r.status_code != 200:
                last = f"{model}: HTTP {r.status_code}"
                continue
            part = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
            rate = 24000
            if "rate=" in part.get("mimeType", ""):
                rate = int(part["mimeType"].split("rate=")[1].split(";")[0])
            pcm = np.frombuffer(base64.b64decode(part["data"]), dtype=np.int16)
            return pcm.astype(np.float32) / 32768.0, rate
        raise RuntimeError(last or "Google не прислал звук")


class SileroSynth(_Synth):
    name = "silero"

    def __init__(self, cfg):
        import torch
        vc = cfg.get("voice", {})
        self.speaker = vc.get("silero_speaker", "eugene")
        torch.hub.set_dir(str(Path(__file__).resolve().parent.parent / "models" / "torch" / "hub"))
        torch.set_num_threads(vc.get("threads", 4))
        self.model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-models", model="silero_tts",
            language="ru", speaker="v4_ru", trust_repo=True, verbose=False,
        )
        self.model.to("cpu")
        try:                                           # первый синтез всегда медленный
            self.model.apply_tts(text="Готов.", speaker=self.speaker, sample_rate=48000)
        except Exception:
            pass

    def prepare(self, text: str) -> str:
        # Silero молча пропускает цифры и латиницу — переводим в слова заранее
        from skills.speech_text import for_tts
        return for_tts(text)

    def synth(self, text: str):
        audio = self.model.apply_tts(text=text, speaker=self.speaker, sample_rate=48000)
        return audio.numpy(), 48000


# ================= встроенная Ирина =================
class _SapiVoice:
    """Работает всегда, даже без torch и интернета. Звучит механически."""
    name = "sapi"

    def __init__(self, cfg):
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        vc = cfg.get("voice", {})
        self._sp = win32com.client.Dispatch("SAPI.SpVoice")
        want = vc.get("sapi_voice", "Irina")
        for v in self._sp.GetVoices():
            if want.lower() in v.GetDescription().lower():
                self._sp.Voice = v
                break
        self._sp.Rate = vc.get("rate", 1)

    def say(self, text):
        self._sp.Speak(text, 1 | 2 | 16)

    def stop(self):
        self._sp.Speak("", 1 | 2)

    def wait(self):
        self._sp.WaitUntilDone(-1)

    @property
    def busy(self):
        try:
            return self._sp.Status.RunningState == 2
        except Exception:
            return False


# ================= голос =================
class Voice:
    def __init__(self, cfg: dict):
        import numpy as np
        import sounddevice as sd
        self.np, self.sd = np, sd
        self.cfg = cfg
        want = cfg.get("voice", {}).get("engine", "edge")

        self.primary = None
        self.fallback = None
        self.sapi = None

        makers = {"edge": EdgeSynth, "gemini": GeminiSynth, "silero": SileroSynth}
        if want in makers:
            try:
                self.primary = makers[want](cfg)
            except Exception as e:
                print(f"[voice] {want} недоступен ({e})")

        if self.primary is None:
            self._load_fallback()                     # основного нет — нужен сразу
        # Для онлайн-голоса запасной Silero заранее не грузим совсем. Torch занимает
        # процессор на добрый десяток секунд: при загрузке на старте первый звук
        # отъезжал до 4 секунд, а при отложенной — тормозило бы распознавание первых
        # команд. Грузим, только когда интернет действительно пропал.
        self._fallback_loading = False

        if self.primary is None and self.fallback is None:
            self.sapi = _SapiVoice(cfg)
        self._emergency = None                        # Ирина, если сбой случился до загрузки Silero

        self._gen = 0
        self._lock = threading.Lock()
        self._text_q = queue.Queue()
        self._audio_q = queue.Queue(maxsize=3)
        self._busy = threading.Event()
        self._synth_done = threading.Event()
        threading.Thread(target=self._synth_worker, daemon=True).start()
        threading.Thread(target=self._play_worker, daemon=True).start()

    def _load_fallback(self):
        if self.fallback is not None:
            return
        try:
            self.fallback = SileroSynth(self.cfg)
        except Exception as e:
            print(f"[voice] локальный запасной голос не поднялся: {e}")

    @property
    def kind(self) -> str:
        if self.sapi:
            return "sapi"
        return (self.primary or self.fallback).name

    # ---------- синтез наперёд ----------
    def _synth_one(self, chunk: str):
        """Основной движок, при сбое — локальный. Возвращает (pcm, rate) или None.

        Если основной упал раньше, чем успел загрузиться запасной Silero, реплика
        уходит встроенной Ирине — лучше механический голос, чем тишина.
        """
        for engine in (self.primary, self.fallback):
            if engine is None:
                continue
            try:
                pcm, rate = engine.synth(engine.prepare(chunk))
                return self._trim(pcm, rate), rate
            except Exception as e:
                print(f"[voice] {engine.name} не ответил: {str(e)[:70]}")
                if engine is self.primary and self.fallback is None and not self._fallback_loading:
                    # Интернет пропал — поднимаем локальный голос в фоне, а пока говорит Ирина
                    self._fallback_loading = True
                    threading.Thread(target=self._load_fallback, daemon=True).start()
        try:
            if self._emergency is None:
                self._emergency = _SapiVoice(self.cfg)
            self._emergency.say(chunk)
            self._emergency.wait()
        except Exception as e:
            print(f"[voice] и встроенный голос не смог: {e}")
        return None

    def _trim(self, pcm, rate):
        """Срезать тишину по краям.

        Microsoft кладёт в начало каждого файла четверть секунды тишины — это
        треть всей задержки до первого звука. Тишина в конце вредна по-другому:
        пока она «играет», микрофон выключен и Джарвис не слышит ответ хозяина.
        """
        np = self.np
        loud = np.flatnonzero(np.abs(pcm) > 0.01)
        if loud.size == 0:
            return pcm
        start = max(0, loud[0] - int(0.02 * rate))
        end = min(len(pcm), loud[-1] + int(0.08 * rate))
        return pcm[start:end]

    def _synth_worker(self):
        while True:
            gen, text = self._text_q.get()
            if gen != self._gen:
                continue
            self._synth_done.clear()
            for chunk in _split_sentences(text):
                if gen != self._gen:
                    break
                result = self._synth_one(chunk)
                if result is None or gen != self._gen:
                    continue
                while gen == self._gen:               # ждём место в очереди, не теряя отмену
                    try:
                        self._audio_q.put((gen, result), timeout=0.2)
                        break
                    except queue.Full:
                        continue
            self._synth_done.set()
            self._audio_q.put((gen, None))            # маркер конца реплики

    def _play_worker(self):
        while True:
            gen, item = self._audio_q.get()
            if gen != self._gen:
                continue
            if item is None:
                with self._lock:
                    if gen == self._gen and self._text_q.empty():
                        self._busy.clear()
                continue
            pcm, rate = item
            try:
                self.sd.play(pcm, rate)
                self.sd.wait()
            except Exception as e:
                print(f"[voice] не смог проиграть: {e}")

    def _drain(self, q):
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                return

    # ---------- интерфейс ----------
    def say(self, text: str, block: bool = False):
        if not text:
            return
        text = str(text).strip()
        print(f"🔊 {text}")
        if self.sapi:
            self.sapi.say(text)
            if block:
                self.sapi.wait()
            return
        with self._lock:
            self._gen += 1
            self._drain(self._text_q)
            self._drain(self._audio_q)
            # «Занят» — с момента заказа, а не с первого звука: иначе в зазоре
            # главный цикл решит, что тихо, и микрофон услышит сам голос
            self._busy.set()
            self.sd.stop()
            self._text_q.put((self._gen, text))
        if block:
            self.wait()

    def stop(self):
        if self.sapi:
            self.sapi.stop()
            return
        with self._lock:
            self._gen += 1
            self._drain(self._text_q)
            self._drain(self._audio_q)
            self.sd.stop()
            self._busy.clear()

    def wait(self):
        if self.sapi:
            self.sapi.wait()
            return
        while self._busy.is_set():
            time.sleep(0.05)

    @property
    def speaking(self) -> bool:
        if self.sapi:
            return self.sapi.busy
        return self._busy.is_set()


if __name__ == "__main__":
    from core import config
    config.setup_console()
    v = Voice(config.CFG)
    print("движок:", v.kind)
    t = time.time()
    v.say("Добрый вечер. Громкость 30 процентов, урок с Петей в 16:30.")
    while v.speaking and time.time() - t < 30:
        time.sleep(0.05)
    print(f"отговорил за {time.time() - t:.1f} c")
