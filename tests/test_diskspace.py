# -*- coding: utf-8 -*-
"""«Что занимает место»: узнаваемые названия, советы по делу, вопрос понят.

Диск выдуманный, но устроен как у хозяина 07.10.2026: Dota 2 в Steam, игра в
C:\\Games, кэши лаунчеров в глубине ProgramData, «Загрузки». Плюс настоящий
обход маленькой папки с точкой соединения — её считать нельзя.
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

GB = 2 ** 30


def fake_disk(DS):
    """Размеры по папкам, как их складывает scan(): каждая папка — сумма всего внутри."""
    files = {
        r"C:\Program Files (x86)\Steam\steamapps\common\dota 2 beta\game": 72 * GB,
        r"C:\Program Files (x86)\Steam\steamapps\workshop\content\570": 2 * GB,
        r"C:\Games\Far Cry 5\data_final": 26 * GB,
        str(DS.PROGRAMDATA / "Ubisoft" / "Ubisoft Game Launcher" / "patch" / "13247"): 7.8 * GB,
        str(DS.PROGRAMDATA / "NVIDIA Corporation" / "NVIDIA App" / "UpdateFramework" / "ota-artifacts"): 7 * GB,
        str(DS.HOME / "Downloads" / "PS"): 8 * GB,
        str(DS.WINDIR / "WinSxS"): 21 * GB,
        str(DS.LOCAL / "Kingsoft" / "WPS Office"): 3.1 * GB,
        str(DS.LOCAL / "Temp"): 0.3 * GB,          # мелочь — не упоминать
    }
    sizes = {}
    for path, size in files.items():
        p = path
        while True:
            sizes[p] = sizes.get(p, 0) + int(size)
            parent = os.path.dirname(p)
            if parent == p:
                break
            p = parent
    return {"drive": "C:", "at": time.time(), "total": 232 * GB, "free": int(1.1 * GB),
            "counted": sizes["C:\\"], "sizes": sizes, "big_files": []}


def main():
    config.setup_console()
    from core import router
    from skills import diskspace as DS
    errors = 0

    def check(name, ok, detail=""):
        nonlocal errors
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} {name}{' — ' + detail if detail else ''}")

    # 1. Названия и порядок
    DS._steam_names = lambda common: {"dota 2 beta": "Dota 2"}   # манифест Steam
    data = fake_disk(DS)
    items = DS.hogs(data, top=8)
    labels = [label for label, *_ in items]
    print("   " + "; ".join(f"{l} {s / GB:.1f}" for l, _k, _p, s in items))
    check("Dota 2 первой и по имени из манифеста", labels[0] == "Dota 2")
    check("Far Cry 5 — игра", ("Far Cry 5", "game") in [(l, k) for l, k, *_ in items])
    check("кэш Ubisoft найден в глубине «Ubisoft»", "кэш патчей Ubisoft" in labels)
    check("обновления NVIDIA найдены в глубине", "скачанные обновления NVIDIA" in labels)
    check("«Загрузки» по-человечески", "папка «Загрузки»" in labels)
    check("Windows названа", "сама Windows" in labels)
    check("моды Steam — отдельной строкой", "моды из мастерской Steam" in labels)
    check("мелочь не упомянута", "временные файлы" not in labels)

    # 2. Голосовой ответ и советы
    DS._state["data"] = data
    text = DS.report()
    print(f"   «{text}»")
    check("ответ начинается со свободного места", text.startswith("На диске C свободно"))
    check("советует почистить кэши", "почисти диск" in text)
    check("советует перенести игры", "перенести" in text)
    check("в предупреждение — две главные", DS.top_phrase().startswith("Больше всего места занимают Dota 2 (72 ГБ)"))

    # 3. Роутер понимает вопрос по-разному
    for phrase in ("что занимает место на диске", "что у меня занимает место",
                   "чем забит диск", "куда делось место", "что столько места занимает",
                   "что жрёт место на компе"):
        r = router.handle(router.normalize(phrase), config.CFG)
        check(f"«{phrase}»", r is not None and r.say == text, (r.say[:40] if r else "не понял"))
    r = router.handle(router.normalize("сколько свободного места"), config.CFG)
    check("«сколько свободного места» — по-прежнему коротко", r is not None and "Больше всего" not in r.say)

    # 4. Настоящий обход: точка соединения не считается (перенесённая игра — не на этом диске)
    base = Path("D:/pytmp/test_diskspace")
    if base.exists():
        subprocess.run(["cmd", "/c", "rmdir", str(base / "box" / "moved_game")], capture_output=True)
        shutil.rmtree(base)
    (base / "box" / "real").mkdir(parents=True)
    (base / "box" / "real" / "a.bin").write_bytes(b"x" * 5000)
    (base / "elsewhere").mkdir()
    (base / "elsewhere" / "big.bin").write_bytes(b"x" * 90000)
    subprocess.run(["cmd", "/c", "mklink", "/J", str(base / "box" / "moved_game"),
                    str(base / "elsewhere")], check=True, capture_output=True)
    real_cache = DS.CACHE
    DS.CACHE = base / "cache.json"
    try:
        scanned = DS.scan(str(base / "box"))
    finally:
        DS.CACHE = real_cache
    root = str(base / "box") + "\\"
    check("обход не зашёл в точку соединения", scanned["sizes"].get(root) == 5000,
          f"посчитано {scanned['sizes'].get(root)} байт")
    subprocess.run(["cmd", "/c", "rmdir", str(base / "box" / "moved_game")], capture_output=True)
    shutil.rmtree(base)

    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
