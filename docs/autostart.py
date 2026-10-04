# -*- coding: utf-8 -*-
"""Включить или выключить старт Джарвиса вместе с Windows.

Раньше это жило прямо в автозапуск.bat, но русский текст внутри батника ломает
cmd.exe, поэтому интерфейс переехал сюда, а батник остался ASCII-запускалкой.
Ярлык кладётся в пользовательскую папку «Автозагрузка» — никаких служб,
планировщика и прав администратора.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

ROOT = Path(__file__).resolve().parent.parent
STARTUP = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"
LINK = STARTUP / "Jarvis.lnk"


def enable() -> str:
    import win32com.client
    shell = win32com.client.Dispatch("WScript.Shell")
    link = shell.CreateShortcut(str(LINK))
    link.TargetPath = str(ROOT / "jarvis.bat")
    link.WorkingDirectory = str(ROOT)
    link.WindowStyle = 7                 # свёрнутым: сам ассистент живёт в трее
    link.Description = "Голосовой ассистент Джарвис"
    link.Save()
    return "Готово: Джарвис будет стартовать вместе с Windows, свёрнутым."


def disable() -> str:
    if LINK.exists():
        LINK.unlink()
        return "Автозапуск выключен."
    return "Автозапуск и так не был включён."


def main():
    config.setup_console()
    state = "включён" if LINK.exists() else "выключен"
    print(f"\nАвтозапуск Джарвиса сейчас {state}.\n")
    print("  1 — включить")
    print("  2 — выключить")
    print("  Enter — ничего не менять\n")
    choice = input("Выбор: ").strip()
    if choice == "1":
        print("\n" + enable())
    elif choice == "2":
        print("\n" + disable())
    else:
        print("\nНичего не менял.")


if __name__ == "__main__":
    main()
