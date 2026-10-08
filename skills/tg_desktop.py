# -*- coding: utf-8 -*-
"""Telegram на компьютере: открыть чат, прочитать, написать — без входа в личный Telegram.

07.10.2026 хозяин попросил «напиши Хомяк Туп»: личный Telegram (вход через
my.telegram.org) не подключён. Раньше здесь можно было писать только в чат,
открытый вручную, — потому что открывали и печатали нажатиями клавиш, а однажды
так текст ушёл не в тот чат (Ctrl+K в поле сообщения — «вставить ссылку»).

С 08.10.2026 — без единого нажатия клавиш, через UI Automation, которую
Telegram Desktop отдаёт целиком: список чатов — строки, которые можно «нажать»
(Invoke), поле сообщения принимает текст напрямую (ValuePattern), кнопка
отправки называется «Send», когда в поле есть текст. Предохранители:

* Адресат ищется ДО вопроса «отправить?», и в вопросе звучит настоящее название
  чата из списка, а не сказанное голосом. Похожих несколько — не гадаем.
* После «да» чат открывается, и заголовок окна сверяется с названием: не тот —
  ничего не пишем.
* Черновик хозяина в поле не затираем: поле должно быть пустым.
* «Отправил» говорим, только когда после нажатия «Send» поле опустело.
"""
import re
import time

from skills import desktop as D
from skills import ui as UI

SEND_NAMES = ("send", "отправить")
SEARCH_NAMES = ("search", "поиск")


def telegram_window():
    """(hwnd, заголовок) окна Telegram Desktop или (None, '')."""
    for hwnd, title, proc in D.list_windows(80):
        if proc.lower().startswith("telegram"):
            return hwnd, title
    return None, ""


def _clean(text: str) -> str:
    """Без невидимых меток направления письма (U+200E), которые Telegram ставит в имена."""
    return re.sub(r"[‎‏‪-‮]", "", text or "").strip()


def chat_title(window_title: str) -> str:
    """Открытый чат по заголовку окна; '' — чат не открыт (в заголовке просто «Telegram»)."""
    t = re.sub(r"\s*\(\d+\)\s*$", "", window_title or "").strip()     # счётчик непрочитанного
    t = re.sub(r"\s*[–—-]\s*Telegram\s*$", "", t, flags=re.I).strip()
    return "" if _clean(t).lower() in ("", "telegram") else t


def _chat_of(window_title: str) -> str:
    """«Хомяк Туп @ Wels» → «Хомяк Туп»: после @ — имя аккаунта хозяина."""
    return re.sub(r"\s*@\s*[^@]*$", "", _clean(chat_title(window_title))).strip()


# «Избранное» в английском Telegram называется Saved Messages
SAVED = ("saved messages", "избранное")


def matches(name: str, title: str) -> bool:
    """«Хомяку» — это «Хомяк Туп», «Саше» — «Саша»: по основам слов, падеж не важен."""
    n, t = UI._norm(name), UI._norm(_clean(title))
    if not n or not t:
        return False
    if t in SAVED and re.fullmatch(r"(?:в\s+)?(?:избранн\w*|сохранен+\w*(?:\s+сообщени\w*)?)", n):
        return True
    if n in t:
        return True
    # Основа — с начала слова: «Оле» не должна находить «Кооле», а «мам» — «Пиццамама»
    stems = [w[:max(3, len(w) - 2)] for w in n.split() if len(w) >= 3]
    words = t.split()
    return bool(stems) and all(any(word.startswith(s) for word in words) for s in stems)


# ---------------- окно через UI Automation ----------------
class Window:
    """Окно Telegram Desktop. Тесты подменяют его своим (T.Window = Fake)."""

    def __init__(self, hwnd):
        self.hwnd = hwnd
        u = UI._uia()
        self.iuia, self.U = u.iuia, u.UIA_dll

    def _req(self):
        req = self.iuia.CreateCacheRequest()
        for p in (self.U.UIA_NamePropertyId, self.U.UIA_ControlTypePropertyId,
                  self.U.UIA_ClassNamePropertyId):
            req.AddProperty(p)
        return req

    def _all(self, control_type):
        root = self.iuia.ElementFromHandle(self.hwnd)
        found = root.FindAllBuildCache(
            self.U.TreeScope_Descendants,
            self.iuia.CreatePropertyCondition(self.U.UIA_ControlTypePropertyId, control_type),
            self._req())
        return [found.GetElement(i) for i in range(found.Length)]

    def _children(self, cls: str):
        lists = [e for e in self._all(self.U.UIA_ListControlTypeId) if cls in (e.CachedClassName or "")]
        if not lists:
            return []
        kids = lists[0].FindAllBuildCache(self.U.TreeScope_Children,
                                          self.iuia.CreateTrueCondition(), self._req())
        return [kids.GetElement(i) for i in range(kids.Length)]

    def rows(self):
        """[(строка, название чата)] — весь список чатов, не только видимое."""
        out = []
        for el in self._children("Dialogs"):
            # «Саша Петрова, последнее сообщение, 13:38» — название идёт первым
            title = _clean((el.CachedName or "").split(", ")[0])
            if title:
                out.append((el, title))
        return out

    def messages(self):
        """Тексты сообщений открытого чата: «Имя\\nтекст\\nSent at 19:52»."""
        return [el.CachedName or "" for el in self._children("HistoryInner")]

    def open(self, row) -> bool:
        from comtypes.gen.UIAutomationClient import IUIAutomationInvokePattern
        try:
            row.GetCurrentPattern(self.U.UIA_InvokePatternId).QueryInterface(
                IUIAutomationInvokePattern).Invoke()
            return True
        except Exception:
            return False

    def _field(self, search: bool):
        for el in self._all(self.U.UIA_EditControlTypeId):
            if not (el.CachedClassName or "").endswith("InputField::Inner"):
                continue
            is_search = UI._norm(el.CachedName or "") in SEARCH_NAMES
            if is_search == search:
                return el
        return None

    def _value(self, el):
        from comtypes.gen.UIAutomationClient import IUIAutomationValuePattern
        return el.GetCurrentPattern(self.U.UIA_ValuePatternId).QueryInterface(IUIAutomationValuePattern)

    def get_text(self, search: bool = False):
        el = self._field(search)
        return None if el is None else (self._value(el).CurrentValue or "")

    def set_text(self, text: str, search: bool = False) -> bool:
        el = self._field(search)
        if el is None:
            return False
        self._value(el).SetValue(text)
        return True

    def send_button(self):
        """(кнопка, её название): «Send», когда в поле есть текст, иначе «Record Voice Message»."""
        for el in self._all(self.U.UIA_ButtonControlTypeId):
            if "SendButton" in (el.CachedClassName or ""):
                return el, el.CachedName or ""
        return None, ""

    def press(self, button) -> bool:
        return UI._invoke(button)


def _window(launch: bool = False):
    """(hwnd, заголовок); нет окна и launch — запускаем Telegram и ждём до 12 секунд."""
    hwnd, title = telegram_window()
    if hwnd or not launch:
        return hwnd, title
    from skills import system as S
    S.open_app("telegram")
    for _ in range(24):
        time.sleep(0.5)
        hwnd, title = telegram_window()
        if hwnd:
            time.sleep(1.5)                  # список чатов догружается после окна
            return telegram_window()
    return None, ""


def find_chats(w, name: str):
    """Чаты, подходящие под сказанное имя. Точное совпадение — одно и сразу."""
    rows = w.rows()
    hits = [(el, t) for el, t in rows if matches(name, t)]
    exact = [h for h in hits if UI._norm(h[1]) == UI._norm(name)]
    if exact:
        return exact[:1]
    seen, unique = set(), []
    for el, t in hits:                      # один чат может встретиться в нескольких папках
        if t not in seen:
            seen.add(t)
            unique.append((el, t))
    return unique


def split_recipient(rest: str):
    """«Хомяк Туп привет как дела» → («Хомяк Туп», «привет как дела»).

    Голосом не слышно, где кончается имя и начинается текст. «что» разделяет
    явно («Саше что буду поздно»); иначе берём самое длинное начало фразы, под
    которое есть чат в списке Telegram. Нет такого чата — (None, None): гадать
    адресата нельзя.
    """
    m = re.match(r"(.+?)\s+что\s+(.+)$", rest)
    if m:
        return m.group(1), m.group(2)
    hwnd, _t = telegram_window()
    titles = [t for _, t in Window(hwnd).rows()] if hwnd else []
    words = rest.split()
    for k in (3, 2, 1):
        if len(words) > k:
            who = " ".join(words[:k])
            if any(matches(who, t) for t in titles):
                return who, " ".join(words[k:])
    return None, None


def _open(w, hwnd, title: str) -> bool:
    """Открыть чат с точным названием и дождаться, что окно показывает именно его."""
    if _chat_of(telegram_window()[1]) == title:
        return True
    rows = [el for el, t in w.rows() if t == title]
    if not rows or not w.open(rows[0]):
        return False
    for _ in range(10):
        time.sleep(0.2)
        if _chat_of(telegram_window()[1]) == title:
            return True
    return False


def _choose(name: str, hits) -> str:
    names = ", ".join(f"«{t}»" for _, t in hits[:4])
    return f"похожих чатов несколько — {names}. Скажи точнее, какой."


def open_chat(name: str) -> str:
    """«Открой чат с Сашей» — открыть его в Telegram на компьютере и показать окно."""
    hwnd, _t = _window(launch=True)
    if not hwnd:
        return "Не открыл: Telegram на компьютере не запускается."
    w = Window(hwnd)
    hits = find_chats(w, name)
    if not hits:
        return f"Чата «{name}» в Telegram на компьютере не нашёл. Как он называется?"
    if len(hits) > 1:
        return "Не открыл: " + _choose(name, hits)
    title = hits[0][1]
    if not _open(w, hwnd, title):
        return f"Не смог открыть чат «{title}» — Telegram не переключился."
    D.focus_window("telegram")
    return f"Открыл чат «{title}» в Telegram."


def read_chat(name: str, n: int = 5) -> str:
    """Последние сообщения чата — открыв его в Telegram на компьютере."""
    opened = open_chat(name)
    if not opened.startswith("Открыл"):
        return opened
    title = opened.split("«", 1)[1].split("»", 1)[0]
    hwnd, _t = telegram_window()
    lines = []
    for raw in Window(hwnd).messages()[-n:]:
        parts = [p.strip() for p in raw.split("\n") if p.strip()]
        if len(parts) < 2:
            continue
        at = re.search(r"(\d{1,2}:\d{2})\s*$", parts[-1])
        body = parts[1:-1] if at else parts[1:]
        if body:
            lines.append(f"{parts[0]}{' в ' + at.group(1) if at else ''}: {' '.join(body)[:200]}")
    if not lines:
        return f"Открыл чат «{title}», но сообщений в нём не вижу."
    return f"Чат «{title}», последние сообщения: " + " | ".join(lines)


def prepare(name: str, text: str):
    """(описание для подтверждения, действие) или (None, почему нельзя)."""
    hwnd, wtitle = _window(launch=True)
    if not hwnd:
        return None, ("НЕ ОТПРАВЛЕНО: Telegram на компьютере не запускается, а личный Telegram "
                      "не подключён.")
    current = _chat_of(wtitle)
    if current and matches(name, current):
        title = current
    else:
        hits = find_chats(Window(hwnd), name)
        if not hits:
            return None, (f"НЕ ОТПРАВЛЕНО: чата «{name}» в Telegram на компьютере не нашёл. "
                          "Уточни, как он называется.")
        if len(hits) > 1:
            return None, "НЕ ОТПРАВЛЕНО: " + _choose(name, hits)
        title = hits[0][1]
    desc = f"отправить в чат «{title}» (Telegram на компьютере) сообщение: «{text}»"
    return desc, (lambda: send_to_chat(title, text))


def send_to_chat(title: str, text: str) -> str:
    """Открыть чат, вписать текст и нажать «Send». Вызывается только после «да»."""
    hwnd, _t = telegram_window()
    if not hwnd:
        return "НЕ ОТПРАВЛЕНО: окно Telegram закрыли."
    w = Window(hwnd)
    if not _open(w, hwnd, title):
        return f"НЕ ОТПРАВЛЕНО: не смог открыть чат «{title}» — Telegram не переключился."
    draft = w.get_text()
    if draft is None:
        return "НЕ ОТПРАВЛЕНО: поле сообщения в Telegram не нашёл."
    if draft.strip():
        return (f"НЕ ОТПРАВЛЕНО: в чате «{title}» уже есть недописанное сообщение «{draft[:60]}» — "
                "не затираю его.")
    if not w.set_text(text) or (w.get_text() or "").strip() != text.strip():
        w.set_text("")
        return "НЕ ОТПРАВЛЕНО: текст не вписался в поле сообщения."
    button, label = w.send_button()
    if button is None or UI._norm(label) not in SEND_NAMES:
        w.set_text("")
        return "НЕ ОТПРАВЛЕНО: кнопку отправки не нашёл — текст убрал из поля."
    if not w.press(button):
        return "НЕ ОТПРАВЛЕНО: кнопка отправки не нажалась. Текст в поле — проверь окно Telegram."
    for _ in range(10):
        time.sleep(0.2)
        if not (w.get_text() or "").strip():
            return f"Отправил в «{title}» через Telegram на компьютере."
    return f"Не уверен, что ушло: нажал «Send», но текст остался в поле. Проверь чат «{title}»."
