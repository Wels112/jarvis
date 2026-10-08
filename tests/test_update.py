# -*- coding: utf-8 -*-
"""Обновление у заказчика: новый код ложится, его ключи, настройки и память — нет.

Папка заказчика имитируется во временной, архив GitHub собирается из этого же
репозитория (git archive), сеть подменена. Перезапуск не вызывается.
"""
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import config


class Resp:
    def __init__(self, content=b"", data=None):
        self.content, self._data = content, data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def main():
    config.setup_console()
    from skills import update as U
    errors = 0
    archive = subprocess.run(["git", "archive", "--format=zip", "--prefix=jarvis-main/", "HEAD"],
                             cwd=ROOT, capture_output=True).stdout
    commit = {"sha": "abc123", "commit": {"committer": {"date": "2026-10-08T03:00:00Z"},
                                          "message": "Новые умения\n\nподробности"}}
    real = (U.ROOT, U.VERSION, U.requests.get, U.restart)
    with tempfile.TemporaryDirectory() as tmp:
        client = Path(tmp)
        (client / "config").mkdir()
        (client / "config" / ".env").write_text("GEMINI_API_KEY=ключ-заказчика\n", encoding="utf-8")
        (client / "config" / "settings.json").write_text('{"owner": "Иван"}', encoding="utf-8")
        (client / "data" / "brain").mkdir(parents=True)
        (client / "data" / "brain" / "tasks.json").write_text("[1]", encoding="utf-8")
        (client / "jarvis.py").write_text("# старая версия", encoding="utf-8")
        (client / "requirements.txt").write_bytes((ROOT / "requirements.txt").read_bytes())
        restarted = []
        U.ROOT, U.VERSION = client, client / "data" / "version.json"
        U.restart = lambda after=3: restarted.append(after)
        U.requests.get = lambda url, **k: Resp(data=commit) if "api.github.com" in url else Resp(archive)
        try:
            said = U.check()
            ok = said.startswith("Есть обновление от 2026-10-08: Новые умения")
            errors += not ok
            print(f"{'ok ' if ok else 'НЕТ'} проверка: «{said}»")

            said = U.apply(restart_after=6)
            env = (client / "config" / ".env").read_text(encoding="utf-8")
            settings = json.loads((client / "config" / "settings.json").read_text(encoding="utf-8"))
            ok = (said.startswith("Обновил до версии от 2026-10-08") and "Перезапускаюсь" in said
                  and env == "GEMINI_API_KEY=ключ-заказчика\n" and settings == {"owner": "Иван"}
                  and (client / "data" / "brain" / "tasks.json").read_text(encoding="utf-8") == "[1]"
                  and (client / "jarvis.py").read_text(encoding="utf-8") != "# старая версия"
                  and (client / "skills" / "system.py").exists() and restarted == [6]
                  and "Зависимости" not in said)              # requirements не менялся — pip не трогаем
            errors += not ok
            print(f"{'ok ' if ok else 'НЕТ'} обновил: «{said[:90]}»")
            print(f"     ключи и настройки на месте: {env.strip()}, {settings}")

            said = U.apply()
            ok = said.startswith("Обновлять нечего")
            errors += not ok
            print(f"{'ok ' if ok else 'НЕТ'} второй раз: «{said}»")

            (client / ".git").mkdir()
            said = U.apply()
            ok = said.startswith("НЕ ОБНОВЛЕНО: это папка разработчика")
            errors += not ok
            print(f"{'ok ' if ok else 'НЕТ'} папку разработчика не трогает: «{said[:60]}»")
        finally:
            U.ROOT, U.VERSION, U.requests.get, U.restart = real

    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
