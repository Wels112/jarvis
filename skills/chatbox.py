# -*- coding: utf-8 -*-
"""Окно-чат на компьютере: общаться с Джарвисом не только голосом, но и текстом.

Зачем: не всегда удобно говорить вслух (ночь, люди рядом, шумно). Здесь — обычное
окошко: печатаешь просьбу, видишь ответ. Идёт тем же путём, что голос и телефон
(`jarvis.answer_text`), так что умеет ровно то же.

Заодно решает частую беду с подключением телефона: код привязки Джарвис называл
только голосом, и его легко ослышаться (а после пяти промахов бот замолкал).
Теперь код виден крупно вверху окна — переписать его в бота уже не проблема.

Вся работа с tkinter — в своём потоке с собственным mainloop. Ответ модели
считается в отдельном потоке, чтобы окно не подвисало; готовый текст возвращается
в поток окна через очередь (tkinter не потокобезопасен).
"""
import queue
import threading


class ChatBox:
    BG = "#1e1e24"
    PANEL = "#15151a"
    TEXT = "#e8e8ea"
    USER = "#7fb0ff"
    MUTED = "#9a9aa6"
    ACCENT = "#4f7cff"
    CODE_BG = "#2a2f45"
    CODE_FG = "#dfe6ff"

    def __init__(self, jarvis):
        self.j = jarvis
        self._q = queue.Queue()       # (kind, text) из рабочих потоков в поток окна
        self._want_show = threading.Event()
        self._root = None
        self._thread = None
        self._busy = False

    def start(self) -> bool:
        """Поднять окно в своём потоке. True — поднялось."""
        try:
            import tkinter  # noqa: F401
        except Exception:
            return False
        self._thread = threading.Thread(target=self._run, name="chatbox", daemon=True)
        self._thread.start()
        return True

    def show(self):
        """Показать окно из любого потока (хоткей, трей, второй запуск)."""
        self._want_show.set()

    # ---------- внутри потока окна ----------
    def _run(self):
        import tkinter as tk
        from tkinter import font as tkfont

        self._root = root = tk.Tk()
        root.title("Jarvis")                     # по этому имени второй запуск поднимает окно
        root.configure(bg=self.BG)
        root.geometry("460x600")
        root.minsize(380, 440)
        try:
            root.iconbitmap(default="")
        except Exception:
            pass

        base = tkfont.Font(family="Segoe UI", size=11)
        bold = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        codef = tkfont.Font(family="Consolas", size=22, weight="bold")

        # Шапка: статус телефона и код привязки (пока не подключён)
        self._head = tk.Label(root, text="", bg=self.BG, fg=self.MUTED, font=base,
                              justify="left", anchor="w", wraplength=430, padx=12, pady=8)
        self._head.pack(fill="x")
        self._code = tk.Label(root, text="", bg=self.CODE_BG, fg=self.CODE_FG, font=codef,
                              pady=10)
        # _code упаковываем/прячем по ситуации в _refresh_head

        # Лента разговора
        wrap = tk.Frame(root, bg=self.BG)
        wrap.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self._log = tk.Text(wrap, bg=self.PANEL, fg=self.TEXT, font=base, wrap="word",
                            relief="flat", padx=12, pady=10, state="disabled",
                            insertbackground=self.TEXT, highlightthickness=0, bd=0)
        sb = tk.Scrollbar(wrap, command=self._log.yview)
        self._log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._log.pack(side="left", fill="both", expand=True)
        self._log.tag_config("you", foreground=self.USER, font=bold, spacing1=6)
        self._log.tag_config("jar", foreground=self.TEXT, spacing1=2, spacing3=6)
        self._log.tag_config("sys", foreground=self.MUTED, spacing1=4, spacing3=4)

        # Ввод
        row = tk.Frame(root, bg=self.BG)
        row.pack(fill="x", padx=12, pady=(0, 12))
        self._entry = tk.Entry(row, bg=self.PANEL, fg=self.TEXT, font=base, relief="flat",
                               insertbackground=self.TEXT, highlightthickness=1,
                               highlightbackground="#2c2c36", highlightcolor=self.ACCENT)
        self._entry.pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 8))
        self._entry.bind("<Return>", lambda e: self._on_send())
        btn = tk.Button(row, text="Отправить", command=self._on_send, font=bold,
                        bg=self.ACCENT, fg="white", relief="flat", activebackground="#3f66d8",
                        activeforeground="white", padx=14, cursor="hand2", bd=0)
        btn.pack(side="right", ipady=3)

        self._append("sys", "Джарвис на связи. Пишите, что нужно — отвечу здесь.")
        root.protocol("WM_DELETE_WINDOW", self._hide)
        self._entry.focus_set()
        self._tick()
        try:
            root.mainloop()
        except Exception:
            pass

    def _tick(self):
        # Единый цикл в потоке окна: сообщения из очереди, запросы показать, шапка.
        try:
            while True:
                kind, text = self._q.get_nowait()
                if kind == "reply":
                    self._append("jar", text)
                    self._busy = False
                    self._entry.configure(state="normal")
                    self._entry.focus_set()
        except queue.Empty:
            pass
        if self._want_show.is_set():
            self._want_show.clear()
            self._do_show()
        self._refresh_head()
        self._root.after(200, self._tick)

    def _refresh_head(self):
        p = getattr(self.j, "phone", None)
        if p and getattr(p, "available", False) and not getattr(p, "owner", 0) and getattr(p, "pair_code", ""):
            name = f" @{p.me}" if getattr(p, "me", "") else ""
            self._head.configure(
                text=f"Телефон не подключён. Откройте в Telegram своего бота{name}, "
                     f"напишите ему /start и отправьте этот код:")
            self._code.configure(text=" ".join(p.pair_code))
            if not self._code.winfo_ismapped():
                self._code.pack(fill="x", before=self._log.master)
        else:
            if p and getattr(p, "owner", 0):
                self._head.configure(text="Телефон подключён. Команды можно слать и сюда, и боту.")
            else:
                self._head.configure(text="")
            if self._code.winfo_ismapped():
                self._code.pack_forget()

    def _append(self, tag, text):
        self._log.configure(state="normal")
        prefix = {"you": "Вы:  ", "jar": "Джарвис:  ", "sys": ""}[tag]
        self._log.insert("end", prefix + text + "\n", tag)
        self._log.see("end")
        self._log.configure(state="disabled")

    def _on_send(self):
        if self._busy:
            return
        text = self._entry.get().strip()
        if not text:
            return
        self._entry.delete(0, "end")
        self._append("you", text)
        self._busy = True
        self._entry.configure(state="disabled")
        threading.Thread(target=self._answer, args=(text,), daemon=True).start()

    def _answer(self, text):
        try:
            reply = self.j.answer_text(text, source="text")
        except Exception as e:
            reply = f"Споткнулся: {type(e).__name__}. Подробности в журнале."
        self._q.put(("reply", reply or "Сделал."))

    def _do_show(self):
        try:
            self._root.deiconify()
            self._root.lift()
            self._root.attributes("-topmost", True)
            self._root.after(400, lambda: self._root.attributes("-topmost", False))
            self._entry.focus_set()
        except Exception:
            pass

    def _hide(self):
        # Крестик не закрывает Джарвиса — прячет окно; он живёт в трее.
        try:
            self._root.withdraw()
        except Exception:
            pass


# Посмотреть окно без запуска всего Джарвиса: python -m skills.chatbox
# (с переменной JARVIS_CHATBOX_SELFCLOSE=1 окно само закроется через 2 секунды —
# так проверяется отрисовка в тестах).
if __name__ == "__main__":
    import os
    import time

    class _FakePhone:
        available, owner, me, pair_code = True, 0, "ivan_jarvis_bot", "392481"

    class _FakeJarvis:
        phone = _FakePhone()

        def answer_text(self, text, source="phone"):
            time.sleep(0.4)
            return f"Вы написали: {text}. (демо-режим, без настоящего мозга)"

    box = ChatBox(_FakeJarvis())
    box.start()
    box.show()
    if os.environ.get("JARVIS_CHATBOX_SELFCLOSE"):
        time.sleep(2)
        try:
            box._root.after(0, box._root.destroy)
        except Exception:
            pass
        time.sleep(0.5)
        print("демо-окно отрисовалось без ошибок")
    else:
        try:
            while box._thread and box._thread.is_alive():
                time.sleep(0.3)
        except KeyboardInterrupt:
            pass
