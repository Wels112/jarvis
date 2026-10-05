# -*- coding: utf-8 -*-
"""Руки по названию: нажимаем кнопки Калькулятора и проверяем ответ на табло.

Проверка настоящая и безобидная: открывается Калькулятор Windows, кнопки
нажимаются по названию, как их назвал бы человек («семь», «7», «плюс»), а
результат читается с табло через то же дерево элементов. В конце окно
закрывается. Если Калькулятор уже открыт у хозяина — тест его не трогает.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config


def display(hwnd) -> str:
    """Табло Калькулятора: текст «Отображение — 9»."""
    from skills.ui import _uia
    u = _uia()
    root = u.iuia.ElementFromHandle(hwnd)
    cond = u.iuia.CreatePropertyCondition(u.UIA_dll.UIA_AutomationIdPropertyId, "CalculatorResults")
    el = root.FindFirst(u.UIA_dll.TreeScope_Descendants, cond)
    return el.CurrentName if el else ""


def main():
    config.setup_console()
    from skills import system as S
    from skills import ui as UI
    import win32gui

    def visible_calc():
        # Только видимые окна: закрытое приложение из Store оставляет скрытое
        # окно с тем же заголовком, и FindWindow находит его
        return next((w[0] for w in S._visible_windows() if w[1] == "Калькулятор"), 0)

    if visible_calc():
        print("Калькулятор уже открыт у хозяина — не трогаю, проверка пропущена")
        return True
    errors = 0
    S.open_app("калькулятор")
    hwnd = 0
    for _ in range(30):
        time.sleep(0.3)
        hwnd = visible_calc()
        if hwnd:
            break
    time.sleep(1.0)
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass

    t0 = time.monotonic()
    report = UI.elements_report("калькулятор")
    took = time.monotonic() - t0
    ok = "Семь" in report and took < 1.5
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} что можно нажать — за {took:.2f} c: {report[:110]}…")

    for spoken in ("семь", "плюс", "2", "равно"):
        said = UI.click(spoken, "калькулятор")
        print(f"     «нажми {spoken}» → {said}")
        time.sleep(0.25)
    result = display(hwnd)
    ok = result.strip().endswith("9")
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} на табло: «{result}» (ожидаю 9)")

    said = UI.click("несуществующая кнопка", "калькулятор")
    ok = "нет" in said
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} несуществующее — честный отказ: {said}")

    t0 = time.monotonic()
    read = UI.read_text("калькулятор")
    took = time.monotonic() - t0
    ok = "9" in read and took < 1.5
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} прочитать окно за {took:.2f} c: {read[:90]}…")

    for name, want in (("Удаление предыдущего символа", True), ("Отправить", True),
                       ("Оплатить заказ", True), ("Не сохранять", True), ("Don't Save", True),
                       ("Семь", False), ("Сохранить", False)):
        got = UI.is_dangerous(name)
        errors += got != want
        print(f"{'ok ' if got == want else 'НЕТ'} «{name}» — {'спросит подтверждение' if got else 'нажмёт сразу'}")

    print("\nубираю за собой:", S.close_app("калькулятор"))
    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
