# -*- coding: utf-8 -*-
"""Руки по названию: нажать кнопку, пункт меню, ссылку или вкладку в любой программе.

До этого Джарвис управлял компьютером горячими клавишами: открыть, закрыть,
переключить вкладку. «Нажми Сохранить» или «включи первое видео на странице» —
нечем: на показе 05.10.2026 он пытался щёлкать по экрану через PowerShell,
получал отказ и рапортовал «нажал».

Здесь используется Windows UI Automation — то же дерево элементов, которое
читает экранный диктор для незрячих. У каждой кнопки, пункта меню и ссылки
есть название, и нажать её можно по названию, не зная, где она на экране.
Браузеры отдают в это дерево и содержимое страницы, так что работает и там.

Скорость. Обёртка pywinauto читала окно Калькулятора 6,1 с — для голоса это
пропасть. Здесь один запрос к UI Automation с кэшем нужных свойств — 0,05 с
на то же окно.

Безопасность. Кнопки, нажатие которых нельзя отменить или которые уводят
наружу — отправить, удалить, оплатить, купить, опубликовать, выйти, — через
подтверждение голосом, как все опасные действия Джарвиса.
"""
import difflib
import re
import threading
import time

import win32api
import win32con
import win32gui

_local = threading.local()           # COM-объекты привязаны к потоку — на поток свой

DANGER = re.compile(
    r"отправ|удал|стере|оплат|купи|покуп|заказ|подтверд|опублик|выйти|выход\b|формат|сброс|"
    r"очист\w* все|send|delete|remove|erase|\bpay\b|buy|purchase|checkout|order|confirm|"
    r"publish|post\b|sign ?out|log ?out|reset|format|"
    # Выбросить несохранённое — тоже безвозвратно. Нашлось на деле 05.10.2026:
    # «Не сохранять» в Блокноте нажималось без вопроса
    r"не сохран|don'?t save|discard|отбросить|без сохранения", re.I)

# Кнопки заголовка окна: есть в каждом окне и забивали список «что можно нажать»
CHROME = re.compile(r"^(свернуть|развернуть|восстановить|закрыть)\b|^система$|"
                    r"^(minimize|maximize|restore|close)\b|^system$", re.I)

# Как кнопки зовут голосом: «нажми 7» — у Калькулятора кнопка «Семь»
DIGITS = {"0": ("ноль", "нуль"), "1": ("один",), "2": ("два",), "3": ("три",),
          "4": ("четыре",), "5": ("пять",), "6": ("шесть",), "7": ("семь",),
          "8": ("восемь",), "9": ("девять",), "+": ("плюс",), "-": ("минус",), "=": ("равно",),
          "ноль": ("нуль",), "нуль": ("ноль",)}      # у Калькулятора кнопка — «Нуль»


def _uia():
    if not hasattr(_local, "uia"):
        import comtypes
        try:
            comtypes.CoInitialize()
        except OSError:
            pass
        from pywinauto.uia_defines import IUIA
        _local.uia = IUIA()
    return _local.uia


def _norm(text: str) -> str:
    text = (text or "").lower().replace("ё", "е")
    text = re.sub(r"[\"'«»“”.,:;!?()\[\]]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ---------- какое окно ----------
def _is_ours(hwnd) -> bool:
    """Окно самого Джарвиса: консоль, где он печатает, — не цель для нажатий."""
    title = win32gui.GetWindowText(hwnd).lower()
    return title.startswith("jarvis") or "jarvis.py" in title


def _target_window(hint: str = ""):
    """Окно по подсказке («в телеграме») или то, с которым хозяин сейчас работает."""
    from skills.system import _visible_windows
    windows = [w for w in _visible_windows() if not _is_ours(w[0])]
    if hint:
        h = _norm(hint)
        for hwnd, title, pname, _ in windows:
            if h in _norm(title) or h in pname:
                return hwnd, title
        return None, hint
    fg = win32gui.GetForegroundWindow()
    if fg and not _is_ours(fg) and win32gui.IsWindowVisible(fg):
        return fg, win32gui.GetWindowText(fg)
    # Если впереди консоль Джарвиса — берём следующее за ней окно
    return (windows[0][0], windows[0][1]) if windows else (None, "")


# ---------- что в окне ----------
def _elements(hwnd, offscreen: bool = False):
    """[(элемент, название, тип)] доступных интерактивных элементов.

    Сначала ищем среди видимых — как и человек. offscreen=True — по всей
    странице: ссылка в статье ниже края экрана тоже нажимается, браузер сам
    её прокрутит.
    """
    u = _uia()
    iuia, U = u.iuia, u.UIA_dll
    root = iuia.ElementFromHandle(hwnd)
    req = iuia.CreateCacheRequest()
    for prop in (U.UIA_NamePropertyId, U.UIA_ControlTypePropertyId,
                 U.UIA_IsOffscreenPropertyId, U.UIA_IsEnabledPropertyId,
                 U.UIA_BoundingRectanglePropertyId):
        req.AddProperty(prop)
    kinds = {U.UIA_ButtonControlTypeId: "кнопка", U.UIA_MenuItemControlTypeId: "меню",
             U.UIA_HyperlinkControlTypeId: "ссылка", U.UIA_TabItemControlTypeId: "вкладка",
             U.UIA_ListItemControlTypeId: "пункт", U.UIA_CheckBoxControlTypeId: "флажок",
             U.UIA_RadioButtonControlTypeId: "переключатель", U.UIA_SplitButtonControlTypeId: "кнопка",
             U.UIA_TreeItemControlTypeId: "пункт", U.UIA_EditControlTypeId: "поле",
             U.UIA_ComboBoxControlTypeId: "список"}
    cond = iuia.CreateOrConditionFromArray(
        [iuia.CreatePropertyCondition(U.UIA_ControlTypePropertyId, ct) for ct in kinds])
    found = root.FindAllBuildCache(U.TreeScope_Descendants, cond, req)
    out = []
    for i in range(min(found.Length, 2000)):
        el = found.GetElement(i)
        name = (el.CachedName or "").strip()
        if not name or not el.CachedIsEnabled or (el.CachedIsOffscreen and not offscreen):
            continue
        out.append((el, name, kinds.get(el.CachedControlType, "элемент")))
    return out


def elements_report(window: str = "") -> str:
    """Что можно нажать в окне — коротко, по группам, чтобы прочитать вслух или модели."""
    hwnd, title = _target_window(window)
    if not hwnd:
        return f"Не нашёл окно «{window}»." if window else "Не вижу активного окна."
    items = _elements(hwnd)
    if not items:
        return f"В окне «{title[:40]}» не нашёл ничего, что можно нажать."
    groups = {}
    for _, name, kind in items:
        if CHROME.match(name):               # кнопки заголовка окна есть всегда — это шум
            continue
        names = groups.setdefault(kind, [])
        if name not in names:
            names.append(name)
    parts, budget = [], 60                   # больше шестидесяти — это уже простыня
    for kind, names in groups.items():
        take = names[:max(5, min(50, budget))]
        budget -= len(take)
        parts.append(f"{kind}: " + ", ".join(n[:40] for n in take)
                     + (f" и ещё {len(names) - len(take)}" if len(names) > len(take) else ""))
        if budget <= 0:
            break
    return f"В окне «{title[:40]}» — " + "; ".join(parts) + "."


# ---------- найти по названию ----------
def _score(query: str, name: str) -> int:
    q, n = _norm(query), _norm(name)
    if not q or not n:
        return 0
    if n == q:
        return 100
    if n.startswith(q + " ") or n.startswith(q):
        return 85
    if q in n.split():
        return 80
    if q in n:
        return 70
    if len(n) >= 3 and n in q:
        return 60
    ratio = difflib.SequenceMatcher(None, q, n).ratio()
    return int(ratio * 60) if ratio >= 0.75 else 0


def find(name: str, window: str = ""):
    """(элемент, название, тип, заголовок окна) или (None, причина, похожие, заголовок)."""
    hwnd, title = _target_window(window)
    if not hwnd:
        return None, "окно не найдено", [], window
    queries = {name}
    queries.update(DIGITS.get(name.strip().lower(), ()))
    preferred = {"кнопка": 3, "меню": 3, "ссылка": 2, "вкладка": 2}

    def best_of(items):
        return sorted(((max(_score(q, n) for q in queries), preferred.get(k, 0), -len(n), el, n, k)
                       for el, n, k in items), key=lambda x: x[:3], reverse=True)

    items = _elements(hwnd)
    scored = best_of(items)
    if not scored or scored[0][0] < 70:
        # На экране точного нет — ищем по всему окну, включая то, что ниже края
        everything = _elements(hwnd, offscreen=True)
        wider = best_of(everything)
        if wider and (not scored or wider[0][0] > scored[0][0]):
            items, scored = everything, wider
    if not scored or scored[0][0] == 0:
        similar = [n for _, n, _ in items if difflib.SequenceMatcher(
            None, _norm(name), _norm(n)).ratio() > 0.5][:5]
        return None, "не найдено", similar, title
    best = scored[0]
    return best[3], best[4], best[5], title


# ---------- нажать ----------
def _invoke(el, hwnd_title: str = "") -> bool:
    """Нажать так, как нажимает экранный диктор: без мыши, даже если кнопку
    что-то заслоняет. Мышью — только если элемент иначе не умеет."""
    u = _uia()
    U = u.UIA_dll
    import comtypes
    for pattern_id, iface, method in (
            (U.UIA_InvokePatternId, U.IUIAutomationInvokePattern, "Invoke"),
            (U.UIA_SelectionItemPatternId, U.IUIAutomationSelectionItemPattern, "Select"),
            (U.UIA_TogglePatternId, U.IUIAutomationTogglePattern, "Toggle"),
            (U.UIA_ExpandCollapsePatternId, U.IUIAutomationExpandCollapsePattern, "Expand")):
        try:
            pat = el.GetCurrentPattern(pattern_id)
            if pat:
                getattr(pat.QueryInterface(iface), method)()
                return True
        except (comtypes.COMError, ValueError, AttributeError):
            continue
    # Мышью в середину элемента, потом курсор на место
    try:
        r = el.CurrentBoundingRectangle
        x, y = (r.left + r.right) // 2, (r.top + r.bottom) // 2
        if r.right <= r.left or r.bottom <= r.top:
            return False
        was = win32api.GetCursorPos()
        win32api.SetCursorPos((x, y))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.05)
        win32api.SetCursorPos(was)
        return True
    except Exception:
        return False


def _document_text(root, cap: int) -> str:
    """Видимый текст страницы в браузере: документ с текстовым шаблоном."""
    u = _uia()
    iuia, U = u.iuia, u.UIA_dll
    doc = root.FindFirst(U.TreeScope_Descendants, iuia.CreatePropertyCondition(
        U.UIA_ControlTypePropertyId, U.UIA_DocumentControlTypeId))
    pat = doc.GetCurrentPattern(U.UIA_TextPatternId) if doc else None
    if not pat:
        return ""
    tp = pat.QueryInterface(U.IUIAutomationTextPattern)
    # Текст от левого верхнего угла документа до правого нижнего — два лёгких
    # запроса. Через GetVisibleRanges браузер сам считал, что видно, и это
    # занимало 2,8 с; по двум точкам — 0,02 с (замер 05.10.2026)
    try:
        from ctypes.wintypes import POINT
        r = doc.CurrentBoundingRectangle
        span = tp.RangeFromPoint(POINT(r.left + 8, r.top + 8))
        span.MoveEndpointByRange(1, tp.RangeFromPoint(POINT(r.right - 30, r.bottom - 8)), 1)
        text = span.GetText(cap)
        if text.strip():
            return text.replace("￼", " ")
    except Exception:
        pass
    # Запасной путь — по видимым кускам. Сбойный кусок (встроенная картинка)
    # пропускаем: раньше один такой молча выбрасывал весь текст страницы
    ranges = tp.GetVisibleRanges()
    pieces = []
    for i in range(min(ranges.Length, 400)):
        try:
            pieces.append(ranges.GetElement(i).GetText(2000))
        except Exception:
            continue
    return " ".join(pieces).replace("￼", " ")


def read_text(window: str = "", limit: int = 3000) -> str:
    """Что написано в окне — без снимка экрана и без интернета.

    look_at_screen отправляет снимок в облако: нужен интернет и несколько
    секунд. А дерево элементов отдаёт сам текст. У браузера — видимую часть
    страницы (то, что сейчас на экране), у обычных программ — подписи и поля.
    Так «что тут написано» работает и у своей модели без сети.
    """
    hwnd, title = _target_window(window)
    if not hwnd:
        return f"Не нашёл окно «{window}»." if window else "Не вижу активного окна."
    u = _uia()
    iuia, U = u.iuia, u.UIA_dll
    root = iuia.ElementFromHandle(hwnd)
    try:
        text = _document_text(root, limit * 3)
    except Exception:
        text = ""
    if not text.strip():
        # Обычная программа: подписи и содержимое полей на экране
        req = iuia.CreateCacheRequest()
        for prop in (U.UIA_NamePropertyId, U.UIA_IsOffscreenPropertyId,
                     U.UIA_ValueValuePropertyId):
            req.AddProperty(prop)
        cond = iuia.CreateOrConditionFromArray([iuia.CreatePropertyCondition(
            U.UIA_ControlTypePropertyId, ct) for ct in (U.UIA_TextControlTypeId,
                                                        U.UIA_EditControlTypeId,
                                                        U.UIA_DocumentControlTypeId)])
        found = root.FindAllBuildCache(U.TreeScope_Descendants, cond, req)
        seen, parts = set(), []
        for i in range(min(found.Length, 400)):
            el = found.GetElement(i)
            if el.CachedIsOffscreen:
                continue
            for piece in (el.CachedName, el.GetCachedPropertyValue(U.UIA_ValueValuePropertyId)):
                piece = (piece or "").strip() if isinstance(piece, str) else ""
                if piece and piece not in seen:
                    seen.add(piece)
                    parts.append(piece)
        text = " · ".join(parts)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return f"В окне «{title[:40]}» не нашёл текста."
    cut = text[:limit] + ("…" if len(text) > limit else "")
    return f"В окне «{title[:40]}» написано: {cut}"


def is_dangerous(name: str) -> bool:
    return bool(DANGER.search(name or ""))


def click(name: str, window: str = "") -> str:
    el, found, kind, title = find(name, window)
    if el is None:
        if found == "окно не найдено":
            return f"Не нашёл окно «{window}»."
        hint = f" Похоже: {', '.join(kind)}." if kind else ""
        return f"В окне «{title[:40]}» нет «{name}».{hint}"
    if not _invoke(el):
        return f"Нашёл «{found}», но нажать не получилось — элемент не отвечает."
    return f"Нажал «{found}» в окне «{title[:40]}»."
