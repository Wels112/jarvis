# -*- coding: utf-8 -*-
"""Сколько времени занимает обойти диски в поисках файла — чтобы выбрать способ поиска."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

SKIP = {".venv", "venv", "node_modules", ".git", "__pycache__", "SteamLibrary", "steamapps",
        "models", ".cache", "cache", "site-packages", "$RECYCLE.BIN", "System Volume Information",
        "Windows", "Program Files", "Program Files (x86)", "ProgramData", "AppData", "pytmp", "llm"}


def walk(root, budget):
    t0 = time.time()
    files = dirs = 0
    stack = [root]
    while stack and time.time() - t0 < budget:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False):
                        if e.name not in SKIP and not e.name.startswith("."):
                            stack.append(e.path)
                            dirs += 1
                    else:
                        files += 1
        except OSError:
            pass
    return files, dirs, time.time() - t0, bool(stack)


if __name__ == "__main__":
    config.setup_console()
    for root in ("D:\\", str(Path.home())):
        f, d, t, cut = walk(root, 20)
        print(f"{root:22} файлов {f:>8} папок {d:>7} за {t:5.1f} c "
              f"{'(не успел целиком)' if cut else '(весь)'}")
