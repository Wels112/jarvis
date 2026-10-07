# -*- coding: utf-8 -*-
"""Удалить установленную программу или игру — как через «Установку и удаление программ».

07.10.2026 хозяин сказал «удали Far Cry 5». Джарвис попробовал PowerShell
(Uninstall-Package — эта команда видит не все программы), ничего не нашёл и
ответил «не нашлось». Правильный путь — тот же, что у Windows: список
установленного в реестре (ключи Uninstall) и собственный деинсталлятор
программы. У игры Steam это steam://uninstall/<id> — Steam сам переспросит, у
остальных — их установщик со своим окном подтверждения.

Сам Джарвис ничего не удаляет: только находит, называет размер и после «да»
запускает деинсталлятор, где хозяин подтверждает ещё раз.
"""
import os
import re
import stat
import subprocess
import winreg

from skills.system import _forms, _score

UNINSTALL_KEYS = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
]
REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
GB = 2 ** 30


def installed() -> list:
    """Установленное — как в «Установке и удалении программ»: с именем и деинсталлятором."""
    found = {}
    for hive, path in UNINSTALL_KEYS:
        try:
            root = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                try:
                    with winreg.OpenKey(root, winreg.EnumKey(root, i)) as key:
                        def val(name):
                            try:
                                return winreg.QueryValueEx(key, name)[0]
                            except OSError:
                                return None
                        name, cmd = val("DisplayName"), val("UninstallString")
                        # Обновления и части других программ Windows сама не показывает
                        if not name or not cmd or val("SystemComponent") == 1 or val("ParentKeyName"):
                            continue
                        found.setdefault(name.lower(), {
                            "name": name, "uninstall": cmd,
                            "location": (val("InstallLocation") or "").strip().strip('"'),
                            "size_kb": val("EstimatedSize") or 0})
                except OSError:
                    continue
    return list(found.values())


def find(name: str):
    """Лучшее совпадение тем же сравнением, что для запуска программ; «v.1.2.0» не мешает."""
    index = {}
    for p in installed():
        key = re.sub(r"\s+v?\.?\d+(\.\d+)+.*$", "", p["name"].lower()).strip()   # «far cry 5 v.1.2.0»
        index.setdefault(key, p)
    scored = [(_score(v, key), -len(key), key) for v in _forms(name) for key in index]
    scored = [s for s in scored if s[0] >= 60]
    return index[max(scored)[2]] if scored else None


def size_of(program: dict) -> int:
    """Сколько занимает: по папке установки, если она есть (в реестре размер часто врёт —
    у Far Cry 5 записано 2 МБ при 26 ГБ). Сама папка может быть ссылкой — внутрь неё
    заходим, а во вложенные ссылки нет."""
    loc = program.get("location")
    if not loc or not os.path.isdir(loc):
        return int(program.get("size_kb") or 0) * 1024
    total, stack = 0, [loc]
    while stack:
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for e in entries:
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            if getattr(st, "st_file_attributes", 0) & REPARSE:
                continue
            if e.is_dir(follow_symlinks=False):
                stack.append(e.path)
            else:
                total += st.st_size
    return total


def uninstall_command(cmd: str) -> str:
    """MsiExec /I{…} в реестре — это «изменить»; удалить — /X{…}."""
    return re.sub(r"(?i)(msiexec(?:\.exe)?\"?\s+)/i", r"\1/X", cmd, count=1)


def prepare(name: str):
    """(описание для подтверждения, действие) или (None, ответ хозяину)."""
    p = find(name)
    if not p:
        return None, f"Не нашёл «{name}» среди установленных программ."
    size = size_of(p)
    shown = f" — {size / GB:.0f} ГБ" if size >= 10 * GB else (f" — {size / GB:.1f} ГБ".replace(".", ",")
                                                               if size >= GB // 10 else "")
    desc = f"удалить {p['name']}{shown}"

    def run():
        subprocess.Popen(uninstall_command(p["uninstall"]), shell=True)
        return (f"Запустил удаление {p['name']} — дальше подтверди в окне удаления: "
                "удалится, только когда подтвердишь там.")
    return desc, run
