# -*- coding: utf-8 -*-
"""Джарвис знает свои руки — на двух фразах из журнала 05.10.2026.

«Можешь моей мышкой нажать на YouTube?» — модель ответила «управлять мышкой я
не могу», хотя ui_click нажимает кнопки и ссылки по названию. «Напиши в поиске
Cloud Code …» — полезла печатать в закрытый браузер вместо окна Claude.
Окна подменены; модель настоящая (Gemini), если есть ключ и связь.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config


def main():
    config.setup_console()
    from skills import desktop as D
    import win32gui
    errors = 0

    # 1. Переключение окна понимает, как программу называют вслух
    real_list, real_fg = D.list_windows, win32gui.SetForegroundWindow
    D.list_windows = lambda limit=12: [(1, "YouTube — Google Chrome", "chrome.exe"),
                                       (2, "Claude", "claude.exe")]
    focused = []
    win32gui.SetForegroundWindow = lambda hwnd: focused.append(hwnd)
    try:
        for said, want in (("Cloud Code", 2), ("клод", 2), ("клод код", 2), ("браузер", 1)):
            focused.clear()
            D.focus_window(said)
            ok = focused == [want]
            errors += not ok
            print(f"{'ok ' if ok else 'НЕТ'} окно по «{said}» → {focused}")
    finally:
        D.list_windows, win32gui.SetForegroundWindow = real_list, real_fg

    # 2. Модель сама: инструмент вместо «не умею» (нужен ключ Gemini и связь)
    from core import brain as B
    b = B.Brain(config.CFG)
    if not b.ready:
        print("(ключа Gemini нет — проверку модели пропускаю)")
    else:
        # Модель отвечает с разбросом (температура 0.7): три попытки, нужно две верных
        good, tries = 0, 0
        for _ in range(3):
            called = []
            b = B.Brain(config.CFG)
            b._run_tool = lambda name, args: called.append((name, args)) or "Нажал «YouTube» в окне «Chrome»."
            answer = b.ask("Можешь моей мышкой нажать на YouTube?")
            if b.last_error is not None:          # облако не ответило (нет VPN, лимит)
                continue
            tries += 1
            names = [n for n, _ in called]
            # Нажать по названию или открыть сайт — оба делают дело; плохо — «не умею» и пустые слова
            hit = bool({"ui_click", "open_site", "browser"} & set(names)) and "не могу" not in answer.lower()
            good += hit
            print(f"   {'+' if hit else '-'} «нажми мышкой» → {names} · «{answer[:60]}»")
        if not tries:
            print("(модель недоступна — пропускаю)")
        else:
            ok = good >= 2 if tries == 3 else good == tries
            errors += not ok
            print(f"{'ok ' if ok else 'НЕТ'} «нажми мышкой» — инструмент, а не «не умею»: {good} из {tries}")

    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
