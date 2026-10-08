# -*- coding: utf-8 -*-
"""«Подключи обученную модель»: в фоне, своя модель выгружается, итог — хозяину.

Сам train/install_lora.py подменён (его конец к концу проверили 08.10.2026 на
надстройке из шума): здесь проверяется оболочка — что Джарвис не ждёт молча,
освобождает видеокарту, подхватывает надстройку и честно говорит, чем кончилось.
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import config


class FakeLocal:
    def __init__(self):
        self.stopped, self.lora_path, self._prefix_ready = 0, None, True

    def stop(self):
        self.stopped += 1


class Done:
    def __init__(self, code, out):
        self.returncode, self.stdout, self.stderr = code, out, ""


def main():
    config.setup_console()
    from skills import training as T
    import train.install_lora as IL
    errors = 0
    said = []
    real = (IL.find_download, T.subprocess.run)
    T.NOTIFY, T.LOCAL = said.append, FakeLocal()

    def wait():
        for _ in range(50):
            if not T._running.is_set():
                return
            time.sleep(0.1)

    try:
        IL.find_download = lambda: None
        r = T.start_install()
        ok = r.startswith("Файла обученной модели") and not T._running.is_set()
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} файла нет — честно и без фона: «{r[:60]}»")

        IL.find_download = lambda: Path("C:/Users/x/Downloads/jarvis-lora.gguf")
        T.subprocess.run = lambda *a, **k: (time.sleep(0.3), Done(0, "   исходная: верно 98/155\n"
                                                                     "   обученная: верно 131/155\nВключил"))[1]
        r = T.start_install()
        again = T.start_install()
        wait()
        ok = (r.startswith("Нашёл jarvis-lora.gguf") and again.startswith("Уже проверяю")
              and T.LOCAL.stopped == 1 and T.LOCAL.lora_path and T.LOCAL.lora_path.name == "jarvis-lora.gguf"
              and said and said[-1].startswith("Обученная модель подключена") and "131/155" in said[-1])
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} удача: модель выгружена, надстройка подхвачена — «{said[-1] if said else '—'}»")

        T.LOCAL = FakeLocal()
        T.subprocess.run = lambda *a, **k: Done(1, "   исходная: верно 98/155\n   обученная: верно 99/155\n"
                                                   "Обученная не лучше исходной — не включаю.")
        T.start_install()
        wait()
        ok = said[-1].startswith("Обученную модель не подключил") and T.LOCAL.lora_path is None
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} не лучше — не подключил и сказал почему: «{said[-1][:90]}»")
    finally:
        IL.find_download, T.subprocess.run = real
        T.NOTIFY = T.LOCAL = None

    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
