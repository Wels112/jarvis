# -*- coding: utf-8 -*-
"""Уши Джарвиса: микрофон → текст.

Работает потоком: постоянно слушает, сам определяет где начало и конец фразы
по громкости (с автокалибровкой под фоновый шум комнаты), и только законченную
фразу отдаёт в распознавание. Никаких кнопок «запись» — как у живого собеседника.

Распознавание в два шага — выбрано замером на 32 фразах, из них 8 живых:
  1) quick_wake: маленькая модель tiny слушает только первые три секунды —
     есть ли там имя. Полсекунды, ложных срабатываний 0 из 13.
  2) transcribe: модель small разбирает фразу целиком. Нужна, когда tiny
     имя не расслышал, и для работы без интернета, по правилам.
"""
import queue
import re
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

SR = 16000            # частота, которую ждёт whisper
FRAME_MS = 30
FRAME = SR * FRAME_MS // 1000

# Междометия и мычание — не команда. Живой тест дал «Аммммм…» на двести букв,
# и оно ушло в Gemini: «Меньше звуков, больше дела».
FILLERS = {"а", "о", "э", "у", "м", "мм", "ммм", "хм", "эм", "ага", "угу", "ну", "эээ",
           "ааа", "ой", "ах", "ох", "эх", "уф", "пф", "тсс"}


def is_junk(text: str, segments=None) -> bool:
    words = re.findall(r"[а-яёa-z]+", text.lower())
    meaningful = [w for w in words
                  if w not in FILLERS
                  and not re.fullmatch(r"(\w)\1*", w)          # «ммммм», «ааааа»
                  and not re.fullmatch(r"[аоэуиыея]*м{2,}", w)]  # «аммммм», «эммм»
    if not meaningful:
        return True
    # Зацикливание распознавателя: одна фраза по кругу даёт высокое сжатие
    return any(getattr(s, "compression_ratio", 0) > 2.4 for s in (segments or []))


class Ears:
    def __init__(self, cfg: dict, models_dir: str):
        e = cfg.get("ears", {})
        self.device_idx = e.get("input_device")
        self.language = e.get("language", "ru")
        self.silence_frames = int(e.get("silence_ms", 900) / FRAME_MS)
        self.max_frames = int(e.get("max_phrase_s", 20) * 1000 / FRAME_MS)
        self.min_frames = int(300 / FRAME_MS)      # короче 0.3 с — это щелчок, не речь
        self.preroll_frames = int(e.get("preroll_ms", 500) / FRAME_MS)
        # Подсказка «Джарвис» — только быстрой модели. У small на живом мычании
        # она однажды выдала «Джарвис» из ничего — там подсказку не даём.
        self.hotwords = e.get("hotwords", "Джарвис")
        self.save_audio = e.get("save_audio", True)
        self.keep_audio = int(e.get("keep_audio", 40))
        self.audio_dir = Path(models_dir).parent / "data" / "logs" / "audio"
        self._q = queue.Queue()
        self._noise = 0.006                        # стартовый порог, дальше калибруется
        self._stream = None
        self.interrupt = threading.Event()         # горячая клавиша прерывает ожидание фразы
        self.on_speech_start = None                # позвать, когда человек начал говорить

        # Модель намеренно small, а не base: замер показал, что base вдвое быстрее,
        # но коверкает глаголы — «откроет браузер» вместо «открой», «поставить»
        # вместо «поставь». В командах глагол и есть действие, поэтому точность
        # важнее полутора секунд.
        print(f"[ears] загружаю модели {e.get('wake_model', 'tiny')} и {e.get('model', 'small')} ...",
              flush=True)
        common = dict(device=e.get("device", "cpu"), compute_type="int8",
                      download_root=models_dir, num_workers=1,
                      cpu_threads=e.get("cpu_threads", 4))
        self.model = WhisperModel(e.get("model", "small"), **common)
        self.wake_model = WhisperModel(e.get("wake_model", "tiny"), **common)
        self.wake_head_s = float(e.get("wake_head_s", 3.0))
        print("[ears] модели готовы", flush=True)

    # ---------- захват ----------
    def _cb(self, indata, frames, time_info, status):
        self._q.put(indata[:, 0].copy())

    def start(self):
        self._stream = sd.InputStream(
            samplerate=SR, blocksize=FRAME, dtype="float32",
            channels=1, callback=self._cb, device=self.device_idx,
        )
        self._stream.start()
        self._calibrate()

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def flush(self):
        """Выбросить всё, что накопилось в очереди.

        Нужно после того, как Джарвис отговорил: через колонки микрофон слышит
        его собственный голос, распознаёт как команду и отвечает сам себе.
        В наушниках проблемы нет, но колонки планируются — дешевле защититься.
        """
        dropped = 0
        while True:
            try:
                self._q.get_nowait()
                dropped += 1
            except queue.Empty:
                break
        return dropped

    def _calibrate(self, seconds: float = 1.0):
        """Замер фонового шума, чтобы вентилятор и кулер не считались речью."""
        vals = []
        need = int(seconds * 1000 / FRAME_MS)
        while len(vals) < need:
            try:
                vals.append(float(np.sqrt(np.mean(self._q.get(timeout=2) ** 2))))
            except queue.Empty:
                break
        if vals:
            base = float(np.median(vals))
            self._noise = max(base * 3.5, 0.004)
        print(f"[ears] порог шума: {self._noise:.4f}")

    # ---------- одна фраза ----------
    def listen_phrase(self):
        """Ждёт речь, пишет до паузы, возвращает numpy-аудио. None — если тишина
        или ожидание прервали горячей клавишей.

        Запись стартует по первому громкому кадру, но к ней приклеиваются
        предыдущие полсекунды. Без этого терялось начало слова: «Джарвис»
        начинается с тихой смычки «Д», и пока звук нарастал до порога, она не
        попадала в запись.
        """
        from collections import deque
        preroll = deque(maxlen=self.preroll_frames)
        buf, started, silence = [], False, 0
        while True:
            if self.interrupt.is_set() and not started:
                return None
            try:
                chunk = self._q.get(timeout=0.25)
            except queue.Empty:
                if started and buf:
                    break
                continue
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            loud = rms > self._noise
            if not started:
                if loud:
                    started = True
                    buf.extend(preroll)
                    buf.append(chunk)
                    if self.on_speech_start:
                        try:
                            self.on_speech_start()     # живой режим начнёт подключаться заранее
                        except Exception:
                            pass
                else:
                    preroll.append(chunk)
            else:
                buf.append(chunk)
                silence = 0 if loud else silence + 1
                if silence >= self.silence_frames or len(buf) >= self.max_frames:
                    break
        if len(buf) - len(preroll) < self.min_frames:
            return None
        return np.concatenate(buf)

    def quick_wake(self, audio) -> tuple:
        """Есть ли имя в начале фразы — по первым трём секундам, быстрой моделью.

        Возвращает (найдено, услышанный текст начала).
        """
        from core import wake
        if audio is None or len(audio) == 0:
            return False, ""
        head = audio[:int(self.wake_head_s * SR)]
        extra = {"hotwords": self.hotwords} if self.hotwords else {}
        segments, _ = self.wake_model.transcribe(
            head, language=self.language, beam_size=1, vad_filter=False,
            condition_on_previous_text=False, temperature=0.0,
            without_timestamps=True, **extra)
        text = " ".join(s.text.strip() for s in segments).strip()
        return wake.find(text.lower())[0], text

    def transcribe(self, audio) -> str:
        """Фраза целиком. Встроенный фильтр тишины выключен намеренно.

        Разбор живых записей 14.09.2026: фильтр отрезал начало фразы вместе
        с именем. С ним — «Какая погода в Санкт-Чербурге», без него —
        «Жарис, какая погода в Санкт-Петербурге». Свой детектор речи у ушей
        уже есть, второй был лишним.
        """
        if audio is None or len(audio) == 0:
            return ""
        segments, _ = self.model.transcribe(
            audio, language=self.language, beam_size=1,
            vad_filter=False, condition_on_previous_text=False, temperature=0.0,
        )
        segments = list(segments)
        text = " ".join(s.text.strip() for s in segments).strip()
        if text and is_junk(text, segments):
            print(f"   (шум, не команда: {text[:40]})")
            return ""
        return text

    def save(self, audio, text: str):
        """Последние фразы в WAV — чтобы отлаживать распознавание на живом голосе.

        Синтетические голоса не воспроизводят реальных искажений: именно по этим
        записям нашлось, что фильтр тишины отрезал имя. Хранится только на этом
        компьютере, старые файлы удаляются сами.
        """
        if not self.save_audio or audio is None:
            return
        try:
            import wave
            from datetime import datetime
            self.audio_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = self.audio_dir / f"{stamp}.wav"
            pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SR)
                w.writeframes(pcm.tobytes())
            path.with_suffix(".txt").write_text(text, encoding="utf-8")
            files = sorted(self.audio_dir.glob("*.wav"))
            for old in files[:-self.keep_audio]:
                old.unlink(missing_ok=True)
                old.with_suffix(".txt").unlink(missing_ok=True)
        except Exception as e:
            print(f"[ears] не сохранил запись: {e}")

    def listen(self) -> str:
        """Полный цикл без живого режима: услышать фразу → вернуть текст."""
        audio = self.listen_phrase()
        text = self.transcribe(audio)
        if text:
            self.save(audio, text)
        return text


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from core import config
    config.setup_console()
    ears = Ears(config.CFG, str(config.MODELS))
    ears.start()
    print("\nГовори в микрофон. Ctrl+C — выход.\n")
    try:
        while True:
            txt = ears.listen()
            if txt:
                print(f"👂 {txt}")
    except KeyboardInterrupt:
        ears.stop()
        print("\nстоп")
