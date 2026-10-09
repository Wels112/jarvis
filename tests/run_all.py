# -*- coding: utf-8 -*-
"""Все проверки разом: python tests\\run_all.py

Каждый набор — отдельным процессом: падение одного не роняет остальные, и
чужое состояние (подменённые функции, временные файлы) не протекает. Пробы
(probe_*, bench_*) сюда не входят — они долгие и меряют, а не проверяют.
Звук системы и настоящие дела хозяина тесты не трогают.

Наборы, которые по-настоящему открывают окна (Калькулятор, Блокнот), идут
только по слову «окна»: run_all.py окна. Иначе прогон посреди работы хозяина
выскакивал у него на экране.
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUITES = [
    "test_commands", "test_reminders", "test_late_reminders", "test_plans", "test_announce", "test_phone",
    "test_phone_voice", "test_safety",
    "test_one_pending", "test_honesty_guard", "test_live_fallback", "test_hands_aware",
    "test_hybrid_brain", "test_files", "test_search",
    "test_cleanup", "test_diskspace", "test_uninstall", "test_tg_desktop",
    "test_speakable", "test_wake_name", "test_reconnect", "test_voice_pipeline",
    "test_single_instance", "test_update", "test_training", "check_py310",
]
WINDOWS = ["test_apps", "test_ui"]       # открывают и закрывают настоящие окна


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    only = [a for a in sys.argv[1:] if a != "окна"]
    suites = SUITES + (WINDOWS if "окна" in sys.argv[1:] else [])
    failed = []
    for name in suites:
        if only and not any(o in name for o in only):
            continue
        start = time.time()
        try:
            run = subprocess.run([sys.executable, str(ROOT / "tests" / f"{name}.py")],
                                 capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=600, cwd=ROOT)
            ok, out = run.returncode == 0, run.stdout + run.stderr
        except subprocess.TimeoutExpired:
            ok, out = False, "не уложился в 10 минут"
        print(f"{'ok ' if ok else 'НЕТ'} {name}  ({time.time() - start:.0f} с)", flush=True)
        if not ok:
            failed.append(name)
            bad = [l for l in out.splitlines() if l.startswith("НЕТ") or "Error" in l]
            for line in (bad or out.splitlines())[-8:]:
                print(f"      {line}")
    print(f"\nнаборов с ошибками: {len(failed)}" + (f" — {', '.join(failed)}" if failed else ""))
    return not failed


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
