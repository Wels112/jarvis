# -*- coding: utf-8 -*-
"""Иконка в трее: Джарвис живёт рядом с часами, а не окном консоли.

Иконка рисуется кодом, а не тащится файлом — по её цвету сразу видно состояние:
бирюзовая точка — слушает, янтарная — думает, серая — на паузе. Это единственный
индикатор у ассистента, который всё остальное время невидим.

Трей необязателен: если pystray не установлен, Джарвис работает как раньше,
просто без иконки.
"""
import threading

try:
    import pystray
    from PIL import Image, ImageDraw
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

# Цвета состояний — те же, что в справочнике команд
COLORS = {
    "listen": (87, 179, 168),     # бирюза — слушает
    "think":  (226, 160, 68),     # янтарь — думает или говорит
    "pause":  (139, 146, 153),    # серый — на паузе
}


def _make_icon(state: str = "listen"):
    """Микрофон: капсула на ножке, с цветной точкой состояния."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = COLORS.get(state, COLORS["listen"])

    d.rounded_rectangle([25, 12, 39, 38], radius=7, fill=c)          # капсула
    d.arc([18, 26, 46, 48], start=0, end=180, fill=c, width=4)       # дужка
    d.line([32, 46, 32, 53], fill=c, width=4)                        # ножка
    d.line([25, 54, 39, 54], fill=c, width=4)                        # подставка
    return img


class Tray:
    def __init__(self, jarvis):
        self.j = jarvis
        self.icon = None
        self._state = "listen"

    def _title(self):
        return {
            "listen": "Джарвис — слушает",
            "think": "Джарвис — думает",
            "pause": "Джарвис — на паузе",
        }.get(self._state, "Джарвис")

    def set_state(self, state: str):
        if not self.icon or state == self._state:
            return
        self._state = state
        try:
            self.icon.icon = _make_icon(state)
            self.icon.title = self._title()
        except Exception:
            pass

    # ---------- пункты меню ----------
    def _toggle_pause(self, icon=None, item=None):
        self.j.paused = not self.j.paused
        if self.j.paused:
            self.set_state("pause")
            self.j.say("Ухожу на паузу. Разбуди через иконку.")
        else:
            self.set_state("listen")
            self.j.say("Снова слушаю.")

    def _say_tasks(self, icon=None, item=None):
        from core import memory
        self.j.say(memory.list_tasks("today"))

    def _say_status(self, icon=None, item=None):
        from skills import system as S
        self.j.say(S.system_info())

    def _quit(self, icon=None, item=None):
        self.j.say("До связи.")
        self.j.voice.wait()
        self.j.running = False
        try:
            self.icon.stop()
        except Exception:
            pass

    def start(self):
        """Поднимает иконку в отдельном потоке. Возвращает False, если трея нет."""
        if not AVAILABLE:
            return False
        menu = pystray.Menu(
            pystray.MenuItem(lambda i: "Продолжить" if self.j.paused else "Пауза",
                             self._toggle_pause, default=True),
            pystray.MenuItem("Задачи на сегодня", self._say_tasks),
            pystray.MenuItem("Статус системы", self._say_status),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выход", self._quit),
        )
        self.icon = pystray.Icon("jarvis", _make_icon("listen"), self._title(), menu)
        threading.Thread(target=self.icon.run, daemon=True).start()
        return True

    def stop(self):
        try:
            if self.icon:
                self.icon.stop()
        except Exception:
            pass


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core import config
    config.setup_console()

    print("pystray доступен:", AVAILABLE)
    if AVAILABLE:
        for st in ("listen", "think", "pause"):
            _make_icon(st).save(config.DATA / f"icon_{st}.png")
        print("иконки нарисованы в data/")
