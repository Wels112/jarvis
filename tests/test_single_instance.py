# -*- coding: utf-8 -*-
"""Второй голосовой Джарвис не запускается: два хором — беда, бот работает только у одного.

Ничего не запускаем по-настоящему: проверяем, что второй процесс видит занятый
мьютекс — неважно, держит ли его этот тест или уже работающий Джарвис.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import config


def main():
    config.setup_console()
    import jarvis as J
    J._single_instance()                       # держим мьютекс сами (или его держит живой Джарвис)
    out = subprocess.run([sys.executable, "-c",
                          "import sys; sys.path.insert(0, r'%s'); import jarvis; "
                          "print(jarvis._single_instance())" % ROOT],
                         capture_output=True, text=True, timeout=120).stdout.strip().splitlines()
    ok = bool(out) and out[-1] == "False"
    print(f"{'ok ' if ok else 'НЕТ'} второй экземпляр видит, что Джарвис уже запущен: {out[-1] if out else '—'}")
    print(f"\nошибок: {int(not ok)}")
    return ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
