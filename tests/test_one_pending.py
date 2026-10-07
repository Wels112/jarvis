# -*- coding: utf-8 -*-
"""Одно опасное действие за раз — на сценарии из журнала 07.10.2026.

«Почисти диск C и удали Far Cry 5»: модель вызвала очистку (нужно «да»), а
следом удаление через PowerShell (тоже нужно «да»). Второй запрос затёр первый,
на «да» выполнилось одно удаление, очистка пропала молча, и модель сказала
«диск почистил». Теперь второй запрос не принимается, пока первый ждёт ответа.
Ничего не выполняется: проверяется только, что ждёт подтверждения.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config


def main():
    config.setup_console()
    from core import brain as B
    from skills import cleanup as CL
    CL.clean = lambda dry_run=False: "Могу освободить примерно 16 ГБ (оценка теста)."
    b = B.Brain(config.CFG)
    errors = 0

    def check(name, ok, detail=""):
        nonlocal errors
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} {name}{' — ' + detail[:90] if detail else ''}")

    r1 = b._run_tool("clean_disk", {})
    first = b.pending_confirm
    check("очистка ждёт «да»", first is not None and "ПОДТВЕРЖДЕНИЕ" in r1, r1)

    uninstall = {"command": 'Get-Package -Name "Far Cry 5" | Uninstall-Package',
                 "reason": "Удаление Far Cry 5 по запросу пользователя"}
    r2 = b._run_tool("powershell", uninstall)
    check("второе опасное не затирает первое", b.pending_confirm is first, r2)
    check("…и модели сказано спросить по очереди", r2.startswith("НЕ ПРИНЯТО") and "очистить диск" in r2)

    r3 = b._run_tool("disk_space", {})
    check("безопасный инструмент при этом работает", b.pending_confirm is first and "свободно" in r3, r3)

    b.pending_at -= B.PENDING_TTL + 1          # вопрос брошен: хозяин так и не ответил
    r4 = b._run_tool("powershell", uninstall)
    check("брошенный вопрос не держит вечно", b.pending_confirm is not first and "ПОДТВЕРЖДЕНИЕ" in r4, r4)

    b.pending_confirm = None                   # хозяин ответил — можно следующее
    r5 = b._run_tool("clean_disk", {})
    check("после ответа следующий вопрос принимается", b.pending_confirm is not None and "ПОДТВЕРЖДЕНИЕ" in r5)

    from core import live as L
    check("сторож честности ловит «сделал» после НЕ ПРИНЯТО",
          bool(L.false_claim("Диск почистил, Far Cry удалил.", [("powershell", r2)])))

    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
