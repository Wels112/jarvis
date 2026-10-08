# -*- coding: utf-8 -*-
"""Подключить обученную в Colab надстройку: найти, сравнить, включить — одной командой.

Ноутбук в конце скачивает в «Загрузки» jarvis-lora.gguf (или архив
jarvis-lora.zip, если упаковать в GGUF там не вышло). Здесь:
  1. берётся самый свежий такой файл из «Загрузок» (или путь из аргумента);
  2. архив упаковывается в GGUF тем же llama.cpp, что проверял train/check_lora.py;
  3. файл кладётся в llm/models;
  4. исходная модель и модель с надстройкой сравниваются на отложенных фразах
     (train/evaluate.py) — надстройка включается, только если стало лучше:
     верных ответов больше, а «сделал» без действия не больше;
  5. в настройки пишется brain.local_lora — Джарвис подхватит её при запуске.

Запуск:  .venv\\Scripts\\python.exe train\\install_lora.py [путь] [--no-eval]
"""
import shutil
import socket
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import config

MODELS = ROOT / "llm" / "models"
BASE = "Qwen3.5-2B-Q4_K_M.gguf"
NAME = "jarvis-lora.gguf"
NBTEST_PY = ROOT / "llm" / "nbtest" / "venv" / "Scripts" / "python.exe"


def find_download():
    """Самый свежий результат обучения в «Загрузках» и на рабочем столе."""
    found = []
    for folder in (Path.home() / "Downloads", Path.home() / "Desktop"):
        if folder.exists():
            found += [p for p in folder.glob("jarvis-lora*") if p.suffix.lower() in (".gguf", ".zip")]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def to_gguf(src: Path) -> Path:
    """GGUF — как есть; архив PEFT — упаковать тем же llama.cpp, что у хозяина."""
    if src.suffix.lower() == ".gguf":
        return src
    if not NBTEST_PY.exists():
        raise RuntimeError("для упаковки архива нужно окружение llm\\nbtest (см. train/check_template.py)")
    work = Path(tempfile.mkdtemp())
    with zipfile.ZipFile(src) as z:
        z.extractall(work)
    adapter = next((p.parent for p in work.rglob("adapter_config.json")), None)
    if adapter is None:
        raise RuntimeError("в архиве нет adapter_config.json — это не надстройка LoRA")
    out = work / NAME
    code = ("import sys; sys.path.insert(0, r'%s'); from check_lora import convert; "
            "ok, tail = convert(__import__('pathlib').Path(r'%s'), __import__('pathlib').Path(r'%s')); "
            "print(tail); sys.exit(0 if ok else 1)") % (ROOT / "train", adapter, out)
    p = subprocess.run([str(NBTEST_PY), "-c", code], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0 or not out.exists():
        raise RuntimeError("упаковка не удалась:\n" + (p.stdout + p.stderr)[-600:])
    return out


def port_busy(port: int = 8090) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def main():
    config.setup_console()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    src = Path(args[0]) if args else find_download()
    if not src or not src.exists():
        print("Не нашёл jarvis-lora.gguf / jarvis-lora.zip в «Загрузках». Дождись конца обучения в Colab "
              "(последняя ячейка скачивает файл сама) или передай путь: install_lora.py путь\\к\\файлу")
        return False
    print(f"надстройка: {src} ({src.stat().st_size / 2**20:.0f} МБ)")
    gguf = to_gguf(src)
    target = MODELS / NAME
    if target.exists():
        shutil.copy2(target, target.with_suffix(".gguf.prev"))     # прежняя — на случай отката
    shutil.copy2(gguf, target)
    print(f"положил в {target}")

    if "--no-eval" not in sys.argv:
        if port_busy():
            print("Порт 8090 занят — похоже, своя модель Джарвиса сейчас загружена. Закрой Джарвиса на "
                  "время проверки или запусти с --no-eval.")
            return False
        from train import evaluate
        items = evaluate.cases()
        print(f"сравниваю на {len(items)} фразах — несколько минут…")
        before = evaluate.run(BASE, items)
        after = evaluate.run(f"{BASE}+{NAME}", items)
        for name, r in (("исходная", before), ("обученная", after)):
            print(f"   {name}: верно {r['hits']}/{r['total']}, «сделал» без действия {r['lies']}, "
                  f"ответ {r['median']:.2f} с")
        # Порог — три фразы: надстройка из чистого шума (train/check_lora.py) на проверке
        # 08.10.2026 дала 99 против 98 — случайный разброс, а не обучение
        if after["hits"] < before["hits"] + 3 or after["lies"] > before["lies"]:
            print("Обученная не лучше исходной — не включаю. Файл оставил в llm\\models для разбора.")
            return False

    config.update_setting("brain.local_lora", NAME)
    print("Включил: brain.local_lora = jarvis-lora.gguf. Перезапусти Джарвиса — своя модель будет с надстройкой.")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
