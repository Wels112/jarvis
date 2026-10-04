# -*- coding: utf-8 -*-
"""Очистка диска — только то, что система пересоздаёт сама.

Граница проведена жёстко и намеренно: сюда попадают временные файлы, кэши
установщиков и логи, то есть данные, потеря которых ничего не значит. Корзина,
загрузки, документы и папки программ не трогаются никогда — даже если очень
хочется освободить место. Разбирать личные файлы должен человек, а не ассистент.

analyze() показывает, сколько где лежит, ничего не удаляя. clean() удаляет
только перечисленное в SAFE и возвращает отчёт.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

LOCAL = Path(os.environ.get("LOCALAPPDATA", ""))
WIN = Path(os.environ.get("SYSTEMROOT", "C:/Windows"))

# Каждый пункт: (описание, путь, только содержимое или папку целиком)
SAFE = [
    ("временные файлы", Path(tempfile.gettempdir()), True),
    ("временные файлы Windows", WIN / "Temp", True),
    ("кэш загруженных обновлений", WIN / "SoftwareDistribution" / "Download", True),
    ("отчёты об ошибках", LOCAL / "CrashDumps", True),
    ("кэш эскизов", LOCAL / "Microsoft" / "Windows" / "Explorer", False),
    ("кэш установщиков pip", LOCAL / "pip" / "cache", True),
    ("кэш npm", LOCAL / "npm-cache" / "_cacache", True),
    ("кэш Nvidia-шейдеров", LOCAL / "NVIDIA" / "DXCache", True),
    ("кэш DirectX-шейдеров", LOCAL / "D3DSCache", True),
]


def _dir_size(path: Path) -> int:
    total = 0
    try:
        for p in path.rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except (OSError, PermissionError):
                pass
    except (OSError, PermissionError):
        pass
    return total


def _gb(n: int) -> float:
    return round(n / 2 ** 30, 2)


def analyze() -> dict:
    """Сколько можно освободить, ничего не удаляя."""
    found = []
    total = 0
    for label, path, _content_only in SAFE:
        if not path.exists():
            continue
        size = _dir_size(path)
        if size > 20 * 2 ** 20:            # мельче 20 МБ не стоит упоминания
            found.append((label, path, size))
            total += size
    found.sort(key=lambda x: -x[2])
    return {"items": found, "total": total}


def free_space(drive: str = "C:") -> tuple:
    usage = shutil.disk_usage(drive + "\\")
    return usage.free, usage.total


def clean(dry_run: bool = False) -> str:
    """Удаляет только безопасное. dry_run — посчитать, но не трогать."""
    before, _ = free_space("C:")
    report = analyze()
    if not report["items"]:
        return "Чистить нечего, мусора почти нет."

    if dry_run:
        lines = [f"{label} — {_gb(size)} ГБ" for label, _p, size in report["items"][:6]]
        return (f"Могу освободить примерно {_gb(report['total'])} ГБ: "
                + "; ".join(lines) + ".")

    # Файлы моложе часа почти наверняка принадлежат работающей прямо сейчас
    # программе. Удалить их технически можно, но это ломает живые процессы —
    # проверено на себе: очистка снесла временные файлы активной сессии.
    import time as _time
    fresh_cutoff = _time.time() - 3600

    failed = 0
    for _label, path, _size in report["items"]:
        try:
            for item in path.iterdir():
                try:
                    if item.stat().st_mtime > fresh_cutoff:
                        continue
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)
                except (OSError, PermissionError):
                    failed += 1
        except (OSError, PermissionError):
            failed += 1

    after, _ = free_space("C:")
    removed = max(0, after - before)
    tail = f" Часть файлов занята системой и осталась." if failed else ""
    return f"Освободил {_gb(removed)} ГБ на диске C.{tail}"


def disk_report() -> str:
    """Что с местом на дисках — для голосового ответа."""
    parts = []
    for d in ("C:", "D:"):
        try:
            free, total = free_space(d)
            parts.append(f"на диске {d[0]} свободно {_gb(free)} гигабайт из {_gb(total):.0f}")
        except Exception:
            pass
    return ", ".join(parts) + "."


if __name__ == "__main__":
    from core import config
    config.setup_console()
    print(disk_report())
    print()
    rep = analyze()
    print(f"Можно освободить: {_gb(rep['total'])} ГБ")
    for label, path, size in rep["items"]:
        print(f"  {_gb(size):>7.2f} ГБ  {label}")
        print(f"           {path}")
