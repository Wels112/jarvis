# -*- coding: utf-8 -*-
"""«Джарвис, подключи обученную модель» — голосом, без консоли.

Сама работа — train/install_lora.py: найти скачанную из Colab надстройку,
сравнить с исходной моделью и включить, только если стало лучше. Здесь — запуск
этого в фоне, пока Джарвис продолжает слушать, и рассказ, чем кончилось.
Своя модель Джарвиса на время проверки выгружается: проверка поднимает свою на
том же порту и той же видеокарте.
"""
import subprocess
import sys
import threading
from pathlib import Path

from core import log

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "llm" / "models"
NOTIFY = None          # jarvis.notify — ставит Джарвис при запуске
LOCAL = None           # своя модель Джарвиса (LocalModel) — выгрузить и потом подхватить надстройку
_running = threading.Event()


def start_install() -> str:
    if _running.is_set():
        return "Уже проверяю обученную модель — скажу, когда закончу."
    sys.path.insert(0, str(ROOT))
    from train.install_lora import find_download
    src = find_download()
    if not src:
        return ("Файла обученной модели в «Загрузках» нет. Дождись конца обучения в Colab — последняя "
                "ячейка скачивает его сама.")
    _running.set()
    threading.Thread(target=_job, args=(src,), daemon=True).start()
    return f"Нашёл {src.name}. Сравниваю с исходной моделью — минут пять-десять, потом скажу, что вышло."


def _job(src: Path):
    try:
        if LOCAL is not None:
            LOCAL.stop()
        p = subprocess.run([sys.executable, str(ROOT / "train" / "install_lora.py"), str(src)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=3600, cwd=str(ROOT))
        out = (p.stdout + p.stderr).strip()
        scores = [line.strip() for line in out.splitlines()
                  if line.strip().startswith(("исходная", "обученная"))]
        if p.returncode == 0:
            if LOCAL is not None:
                LOCAL.lora_path = MODELS / "jarvis-lora.gguf"     # со следующего запуска своей модели
                LOCAL._prefix_ready = False
            msg = "Обученная модель подключена. " + "; ".join(scores)
        else:
            last = out.splitlines()[-1] if out else "без подробностей"
            msg = f"Обученную модель не подключил: {last}" + (f" ({'; '.join(scores)})" if scores else "")
    except Exception as e:
        msg = f"Проверка обученной модели сорвалась: {type(e).__name__}: {e}"
    try:
        log.write("info", f"[обучение] {msg}")
        if NOTIFY:
            NOTIFY(msg)
    finally:
        _running.clear()               # только после итога: «уже проверяю» не врёт
