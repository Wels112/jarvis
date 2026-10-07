# -*- coding: utf-8 -*-
"""Очистка диска — только то, что система пересоздаёт сама.

Граница проведена жёстко и намеренно: сюда попадают временные файлы, кэши
установщиков и логи, то есть данные, потеря которых ничего не значит. Корзина,
загрузки, документы и папки программ не трогаются никогда — даже если очень
хочется освободить место. Разбирать личные файлы должен человек, а не ассистент.

analyze() показывает, сколько где лежит, ничего не удаляя. clean() удаляет
только перечисленное в SAFE и возвращает отчёт.
"""
import json
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
# Что Windows не дала удалить: в оценку не входит месяц, потом попробуем снова
BLOCKED = Path(__file__).resolve().parent.parent / "data" / "cleanup_blocked.json"
BLOCKED_DAYS = 30
MIN_REPORT = 20 * 2 ** 20      # мельче не стоит упоминания
MIN_REFUSED = 100 * 2 ** 20    # столько осталось при неудачах — значит, не дали удалить
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


def _blocked() -> dict:
    """Что Windows не дала удалить в прошлый раз: {описание: когда}."""
    try:
        data = json.loads(BLOCKED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    import time as _time
    return {k: v for k, v in data.items() if _time.time() - v < BLOCKED_DAYS * 86400}


def analyze() -> dict:
    """Сколько можно освободить, ничего не удаляя.

    То, что в прошлый раз удалить не дали (нужны права администратора), в
    обещание не входит: 07.10.2026 Джарвис посулил «около 16 гигабайт», а
    половина лежала там, куда ему не дотянуться.
    """
    found, blocked = [], []
    total = 0
    no_access = _blocked()
    for label, path, _content_only in SAFE:
        if not path.exists():
            continue
        size = _dir_size(path)
        if size <= MIN_REPORT:
            continue
        if label in no_access:
            blocked.append((label, path, size))
        else:
            found.append((label, path, size))
            total += size
    found.sort(key=lambda x: -x[2])
    return {"items": found, "total": total, "blocked": blocked}


def free_space(drive: str = "C:") -> tuple:
    usage = shutil.disk_usage(drive + "\\")
    return usage.free, usage.total


def _gb_say(n: int) -> str:
    v = n / 2 ** 30
    return f"{v:.0f}" if v >= 10 or abs(v - round(v)) < 0.05 else f"{v:.1f}".replace(".", ",")


def clean(dry_run: bool = False) -> str:
    """Удаляет только безопасное. dry_run — посчитать, но не трогать."""
    before, _ = free_space("C:")
    report = analyze()
    blocked = report["blocked"]
    no_rights = ("Ещё " + _gb_say(sum(s for *_x, s in blocked)) + " ГБ — "
                 + ", ".join(label for label, *_ in blocked)
                 + " — удалить мне не дают: нужны права администратора.") if blocked else ""
    if not report["items"]:
        return ("Чистить нечего, мусора почти нет. " + no_rights).strip()

    if dry_run:
        lines = [f"{label} — {_gb_say(size)} ГБ" for label, _p, size in report["items"][:6]]
        return (f"Могу освободить примерно {_gb_say(report['total'])} ГБ: "
                + "; ".join(lines) + ". " + no_rights).strip()

    # По пунктам: что освободилось и что Windows не дала тронуть. Одна общая цифра
    # прятала провал: «освободил 0,1 ГБ» при обещанных шестнадцати
    done, refused = [], []
    for label, path, size in report["items"]:
        failed = _clean_dir(path)
        left = _dir_size(path)
        freed = max(0, size - left)
        if freed >= MIN_REPORT:
            done.append((label, freed))
        if failed and left > size * 0.9 and left > MIN_REFUSED:
            refused.append((label, left))
    _remember_blocked([label for label, _ in refused])
    after, _ = free_space("C:")
    removed = max(0, after - before)
    text = f"Освободил {_gb_say(removed)} ГБ на диске C"
    text += (": " + "; ".join(f"{label} — {_gb_say(n)} ГБ" for label, n in done) + ".") if done else "."
    if refused:
        text += (" Не смог очистить: " + ", ".join(f"{label} ({_gb_say(n)} ГБ)" for label, n in refused)
                 + " — Windows не дала, нужны права администратора.")
    return text


def _remember_blocked(labels):
    import time as _time
    data = _blocked()
    for label in labels:
        data[label] = _time.time()
    try:
        BLOCKED.parent.mkdir(parents=True, exist_ok=True)
        BLOCKED.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


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
