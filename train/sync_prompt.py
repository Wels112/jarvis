# -*- coding: utf-8 -*-
"""Совпадает ли учебник своей модели с тем, что она видит в работе.

Своя модель получает системный текст PERSONA + LOCAL_HINTS и описания всех
инструментов из core/brain.py. Учебник (train/data/system.txt, tools.json)
должен быть ровно таким же: модель учится выбирать инструмент по этим
описаниям, и поправленное в коде, но не в учебнике описание — это обучение
на одном тексте и работа на другом.

  .venv\\Scripts\\python.exe train\\sync_prompt.py           — проверить
  .venv\\Scripts\\python.exe train\\sync_prompt.py --write   — выгрузить из кода

Примеры учебника от этого не меняются: в них только имена инструментов и
аргументы, а описания модель видит в начале каждого запроса.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = ROOT / "train" / "data"


def live_prompt():
    from core.brain import TOOLS, PERSONA
    from core.local_brain import LOCAL_HINTS
    tools = [{"name": t["name"], "description": t.get("description", ""),
              "parameters": t.get("parameters") or {"type": "object", "properties": {}}}
             for t in TOOLS]
    return PERSONA + LOCAL_HINTS, tools


def main():
    from core import config
    config.setup_console()
    system, tools = live_prompt()
    if "--write" in sys.argv:
        (DATA / "tools.json").write_text(json.dumps(tools, ensure_ascii=False, indent=1), encoding="utf-8")
        (DATA / "system.txt").write_text(system, encoding="utf-8")
        print("учебник: инструменты и системный текст выгружены из кода")
    saved_tools = json.loads((DATA / "tools.json").read_text(encoding="utf-8"))
    saved_system = (DATA / "system.txt").read_text(encoding="utf-8")
    differ = [a["name"] for a, b in zip(tools, saved_tools) if a != b]
    ok_tools = tools == saved_tools
    ok_system = system == saved_system
    print(f"{'ok ' if ok_tools else 'НЕТ'} инструменты: в работе {len(tools)}, в учебнике "
          f"{len(saved_tools)}{', разные: ' + ', '.join(differ) if differ else ''}")
    print(f"{'ok ' if ok_system else 'НЕТ'} системный текст")
    if not (ok_tools and ok_system):
        print("\nВыгрузи заново: train\\sync_prompt.py --write — и запушь, ноутбук берёт учебник с GitHub")
    return ok_tools and ok_system


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
