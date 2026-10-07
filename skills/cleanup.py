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
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

LOCAL = Path(os.environ.get("LOCALAPPDATA", ""))
WIN = Path(os.environ.get("SYSTEMROOT", "C:/Windows"))
PROGRAMDATA = Path(os.environ.get("PROGRAMDATA") or "C:/ProgramData")

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
    # Лаунчеры оставляют скачанное после установки: у хозяина 07.10.2026 это
    # 7,8 ГБ патчей Ubisoft и 7,0 ГБ пакетов драйвера NVIDIA. Понадобятся —
    # скачаются заново. Свежее (идущая сейчас загрузка) не трогаем, см. MIN_AGE
    ("кэш патчей Ubisoft", PROGRAMDATA / "Ubisoft" / "Ubisoft Game Launcher" / "patch", True),
    ("скачанные обновления NVIDIA",
     PROGRAMDATA / "NVIDIA Corporation" / "NVIDIA App" / "UpdateFramework" / "ota-artifacts", True),
]

# Файл моложе суток может принадлежать работающей сейчас программе
MIN_AGE = 24 * 3600
REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
# Рабочие файлы сессий Claude Code: выводы фоновых команд, черновики. Возраст
# тут не помогает — сессия идёт сутками, а нужен ей и вчерашний файл
KEEP = {"claude"}


def _dir_size(path: Path) -> int:
    """Размер без захода в ссылки — тем же обходом, что и удаление (KEEP не считаем)."""
    total = 0
    stack = [(str(path), True)]
    while stack:
        d, top = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            if top and e.name.lower() in KEEP:
                continue
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            if getattr(st, "st_file_attributes", 0) & REPARSE or e.is_symlink():
                continue
            if stat.S_ISDIR(st.st_mode):
                stack.append((e.path, False))
            else:
                total += st.st_size
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

    failed = sum(_clean_dir(path) for _label, path, _size in report["items"])
    after, _ = free_space("C:")
    removed = max(0, after - before)
    tail = (" Часть файлов занята программами или требует прав администратора — осталась."
            if failed else "")
    return f"Освободил {_gb(removed)} ГБ на диске C.{tail}"


def _clean_dir(path: Path, now: float = None) -> int:
    """Удалить внутри path файлы старше MIN_AGE и опустевшие папки. Вернуть число неудач.

    Возраст смотрим у каждого файла, а не у папки верхнего уровня: дата папки
    меняется, только когда в ней самой появляется или пропадает запись, и не
    меняется, когда пишут в файлы глубже. Прежняя проверка «папка старше часа —
    сносим целиком» так и снесла рабочие файлы живой сессии Claude Code.

    Обход свой, а не os.walk: тот не заходит в символические ссылки, но заходит
    в точки соединения (junction) — и ссылка из Temp на папку с играми стоила бы
    этой папки. В ссылки любого вида не заходим и сами ссылки не трогаем.
    """
    import time as _time
    cutoff = (now or _time.time()) - MIN_AGE
    failed = 0

    def sweep(d: str, top: bool) -> None:
        nonlocal failed
        try:
            entries = list(os.scandir(d))
        except OSError:
            failed += 1
            return
        for e in entries:
            if top and e.name.lower() in KEEP:
                continue
            try:
                st = e.stat(follow_symlinks=False)
                if getattr(st, "st_file_attributes", 0) & REPARSE or e.is_symlink():
                    continue
                if stat.S_ISDIR(st.st_mode):
                    sweep(e.path, False)
                    try:
                        os.rmdir(e.path)        # только пустую: со свежими файлами не выйдет
                    except OSError:
                        pass
                elif st.st_mtime < cutoff:
                    try:
                        os.unlink(e.path)
                    except PermissionError:     # «только чтение» Windows не удаляет
                        os.chmod(e.path, stat.S_IWRITE)
                        os.unlink(e.path)
            except OSError:
                failed += 1

    sweep(str(path), True)
    return failed


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
