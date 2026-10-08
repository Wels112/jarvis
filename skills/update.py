# -*- coding: utf-8 -*-
"""Обновление Джарвиса с GitHub — у заказчика, к которому не подойдёшь.

Разработчик выкладывает исправление, заказчик говорит «Джарвис, обновись» (или
запускает обновить.bat) — и всё. Код берётся тем же архивом, что ставит
установщик. Своё у хозяина не трогаем: ключи (config/.env), настройки
(config/settings.json), память и журналы (data/), окружение (.venv), модели.
Зависимости доставляем, только если поменялся requirements.txt — torch и
прочее тяжёлое заново не качается.

В рабочей папке разработчика (есть .git) не обновляем: архив затёр бы
несохранённые правки — там обновляются через git.
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
REPO = "Wels112/jarvis"
BRANCH = "main"
VERSION = ROOT / "data" / "version.json"
KEEP_DIRS = {".venv", "data", "models", "llm", ".git", "__pycache__"}
KEEP_FILES = {"config/.env", "config/settings.json"}


def _req_hash(root: Path) -> str:
    try:
        return hashlib.sha1((root / "requirements.txt").read_bytes()).hexdigest()
    except OSError:
        return ""


def _installed() -> dict:
    try:
        return json.loads(VERSION.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def latest():
    """Последняя версия на GitHub: {sha, date, message} или None (нет сети)."""
    try:
        r = requests.get(f"https://api.github.com/repos/{REPO}/commits/{BRANCH}", timeout=15,
                         headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        c = r.json()
        return {"sha": c["sha"], "date": c["commit"]["committer"]["date"][:10],
                "message": c["commit"]["message"].splitlines()[0][:120]}
    except Exception:
        return None


def _dev_tree() -> bool:
    return (ROOT / ".git").exists()


def check() -> str:
    """«Есть обновления?» — что нового, без установки."""
    new = latest()
    if not new:
        return "GitHub не ответил — проверь интернет."
    if _dev_tree():
        return f"Это папка разработчика, она обновляется через git. Последняя версия — от {new['date']}."
    if _installed().get("sha") == new["sha"]:
        return f"Обновлений нет: стоит последняя версия от {new['date']}."
    return f"Есть обновление от {new['date']}: {new['message']}. Скажи «обновись»."


def apply(restart_after: float = 0) -> str:
    """Скачать и разложить новую версию. restart_after > 0 — через столько секунд
    перезапустить Джарвиса (чтобы успеть сказать ответ)."""
    if _dev_tree():
        return "НЕ ОБНОВЛЕНО: это папка разработчика (git) — архив затёр бы правки. Обновляй через git pull."
    new = latest()
    if not new:
        return "НЕ ОБНОВЛЕНО: GitHub не ответил — проверь интернет."
    if _installed().get("sha") == new["sha"]:
        return f"Обновлять нечего: уже стоит последняя версия от {new['date']}."
    try:
        r = requests.get(f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip", timeout=120)
        r.raise_for_status()
        before = _req_hash(ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            zipfile.ZipFile(io.BytesIO(r.content)).extractall(tmp)
            inner = next(Path(tmp).iterdir())
            copied = _copy_tree(inner, ROOT)
        deps = ""
        if _req_hash(ROOT) != before:
            pip = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r",
                                  str(ROOT / "requirements.txt")], capture_output=True, timeout=1800)
            deps = " Зависимости обновлены." if pip.returncode == 0 else \
                " Зависимости не встали — запусти установщик ещё раз."
        VERSION.parent.mkdir(parents=True, exist_ok=True)
        VERSION.write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        return f"НЕ ОБНОВЛЕНО: {type(e).__name__}: {str(e)[:120]}"
    if restart_after:
        restart(restart_after)
    return (f"Обновил до версии от {new['date']} ({copied} файлов): {new['message']}.{deps}"
            + (" Перезапускаюсь." if restart_after else " Перезапусти Джарвиса."))


def _copy_tree(src: Path, dst: Path) -> int:
    n = 0
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        if rel.parts and rel.parts[0] in KEEP_DIRS or rel.as_posix() in KEEP_FILES:
            continue
        target = dst / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            n += 1
    return n


def restart(after: float = 3):
    """Запустить Джарвиса заново и выйти из этого. Новый ждёт 6 секунд: второй
    экземпляр не стартует, пока жив первый (мьютекс), а первому нужно договорить."""
    bat = ROOT / "jarvis.bat"
    subprocess.Popen(f'cmd /c timeout /t 6 /nobreak >nul & start "" "{bat}"',
                     cwd=str(ROOT), creationflags=subprocess.CREATE_NEW_CONSOLE)

    def bye():
        time.sleep(after)
        os._exit(0)
    import threading
    threading.Thread(target=bye, daemon=True).start()


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    from core import config
    config.setup_console()
    print(check())
    if "--apply" in sys.argv:
        print(apply())
