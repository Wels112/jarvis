# -*- coding: utf-8 -*-
"""Очистка удаляет только старое и только у себя.

Строим на D: настоящую папку: старые и свежие файлы, свежий файл глубоко в
старой папке (его прежняя очистка сносила вместе с папкой), папку claude
(рабочие файлы Claude Code), файл «только чтение» и точку соединения на
папку снаружи — в неё очистка заходить не должна вовсе.
"""
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

BASE = Path("D:/pytmp/test_cleanup")


def touch(path: Path, age_hours: float = 0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x" * 1000, encoding="utf-8")
    t = time.time() - age_hours * 3600
    os.utime(path, (t, t))


def main():
    config.setup_console()
    from skills import cleanup as CL

    if BASE.exists():
        shutil.rmtree(BASE)
    box, outside = BASE / "temp", BASE / "outside"
    touch(box / "old.txt", 48)
    touch(box / "fresh.txt")
    touch(box / "olddir" / "deep" / "fresh_nested.txt")
    touch(box / "olddir" / "old_nested.txt", 48)
    os.utime(box / "olddir", (time.time() - 72 * 3600,) * 2)      # сама папка — старая
    touch(box / "emptied" / "old.log", 48)
    touch(box / "claude" / "session" / "old_task.output", 48)
    touch(box / "readonly.tmp", 48)
    os.chmod(box / "readonly.tmp", stat.S_IREAD)
    touch(outside / "precious_old.txt", 48)
    subprocess.run(["cmd", "/c", "mklink", "/J", str(box / "link_out"), str(outside)],
                   check=True, capture_output=True)

    size = CL._dir_size(box)
    failed = CL._clean_dir(box)

    checks = [
        ("старый файл удалён", not (box / "old.txt").exists()),
        ("свежий файл на месте", (box / "fresh.txt").exists()),
        ("свежий файл в старой папке на месте", (box / "olddir" / "deep" / "fresh_nested.txt").exists()),
        ("старый файл в той же папке удалён", not (box / "olddir" / "old_nested.txt").exists()),
        ("опустевшая папка убрана", not (box / "emptied").exists()),
        ("папка claude не тронута", (box / "claude" / "session" / "old_task.output").exists()),
        ("«только чтение» тоже удалён", not (box / "readonly.tmp").exists()),
        ("по ссылке наружу не ходил", (outside / "precious_old.txt").exists()),
        ("сама ссылка на месте", (box / "link_out").exists()),
        # old, fresh, fresh_nested, old_nested, emptied/old.log, readonly — шесть
        ("размер без ссылки и без claude", size == 6 * 1000),
        ("без неудач", failed == 0),
    ]
    errors = 0
    for name, ok in checks:
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} {name}")

    # Ссылку убираем как ссылку (rmdir), иначе rmtree пошёл бы внутрь
    os.rmdir(box / "link_out")
    shutil.rmtree(BASE)
    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
