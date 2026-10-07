# -*- coding: utf-8 -*-
"""«Удали игру Far Cry 5»: найти в списке установленного и спросить — не удаляя.

07.10.2026 Джарвис на эту просьбу полез в PowerShell (Uninstall-Package), не
нашёл и ответил «не нашлось». Здесь — настоящий список программ этого
компьютера; деинсталлятор не запускается ни разу.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config


def main():
    config.setup_console()
    from core import brain as B, router
    from skills import programs as PR
    import subprocess
    launched = []
    real_popen = subprocess.Popen
    subprocess.Popen = lambda *a, **k: launched.append(a)       # ничего не запускаем
    errors = 0

    def check(name, ok, detail=""):
        nonlocal errors
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} {name}{' — ' + str(detail)[:100] if detail else ''}")

    try:
        progs = PR.installed()
        check("список установленного прочитан", len(progs) > 20, f"{len(progs)} программ")
        fc = PR.find("far cry 5")
        check("«far cry 5» найден, хоть он и «v.1.2.0»", fc and fc["name"].startswith("Far Cry 5"),
              fc and fc["name"])
        dota = PR.find("дота")
        check("«дота» — это Dota 2 через Steam", dota and dota["name"] == "Dota 2"
              and "steam://uninstall" in dota["uninstall"], dota and dota["uninstall"])
        desc, action = PR.prepare("far cry 5")
        check("размер — по папке, а не по реестру (2 МБ)", desc and "ГБ" in desc, desc)
        check("несуществующее — честно", PR.prepare("абракадабра проги")[0] is None,
              PR.prepare("абракадабра проги")[1])
        check("MsiExec /I превращается в /X",
              PR.uninstall_command("MsiExec.exe /I{1234-ABCD}") == "MsiExec.exe /X{1234-ABCD}")

        r = router.handle(router.normalize("удали игру дота"), config.CFG)
        check("«удали игру дота» — спрашивает «да»", r and r.pending and "Dota 2" in r.say, r and r.say)
        r = router.handle(router.normalize("удали файл отчёт"), config.CFG)
        check("«удали файл …» сюда не попадает", not (r and r.pending_desc and "удалить" in r.pending_desc
                                                      and "Far" in (r.say or "")))

        b = B.Brain(config.CFG)
        said = b._run_tool("uninstall_app", {"name": "Far Cry 5"})
        check("инструмент мозга ждёт подтверждения", b.pending_confirm and said.startswith("ТРЕБУЕТСЯ"), said)
        check("до «да» ничего не запущено", not launched)
        result = b.pending_confirm[1]()
        check("после «да» — деинсталлятор игры и честный ответ",
              launched and "unins000.exe" in str(launched[-1]) and "только когда подтвердишь" in result,
              result)
        from core.honesty import failed
        check("ответ после запуска — не «отказ» для сторожа честности", not failed(result))
    finally:
        subprocess.Popen = real_popen

    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
