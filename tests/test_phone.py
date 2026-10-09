# -*- coding: utf-8 -*-
"""Связь с телефоном: тот же мозг, но ответ в чат — и только хозяину.

Telegram не дёргаем: транспорт подменён, запросы записываются. Проверяется то,
что важно по существу — чужому не отвечаем, вслух в пустую комнату не говорим,
опасное действие подтверждается там же, где спрошено.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

OWNER = 111222333
STRANGER = 999


class FakePhone:
    """Телефон с подменённым транспортом: ничего не уходит в сеть."""

    def __init__(self, phone):
        self.phone = phone
        self.sent = []
        phone._call = self._call

    def _call(self, method, _wait=20, _files=None, **params):
        self.sent.append((method, params.get("text", ""), bool(_files)))
        return []

    def texts(self):
        return [t for m, t, _ in self.sent if m == "sendMessage"]

    def voices(self):
        return [1 for m, _, f in self.sent if m == "sendVoice" and f]

    def clear(self):
        self.sent.clear()


def main():
    config.setup_console()
    import jarvis as J
    from core.phone import Phone
    from skills import cleanup as CL

    j = J.Jarvis(voice_mode=False)
    spoken = []
    j.voice.say = lambda text: spoken.append(text)        # вслух ничего не играем
    CL.clean = lambda dry_run=False: ("Могу освободить примерно 0.5 ГБ." if dry_run
                                      else "Освободил 0.5 ГБ (заглушка теста).")

    phone = Phone(j)
    phone.token, phone.owner = "тест", OWNER
    phone.pinned = False        # сводка проверяется отдельно, в разделе 7
    phone.STATE = Path("D:/pytmp/test_phone_main_state.json")    # настоящий закреп не трогаем
    fake = FakePhone(phone)
    j.phone = phone
    errors = 0

    # 1. Обычная просьба с телефона: ответ в чат, в комнате тишина
    phone._handle({"chat": {"id": OWNER}, "text": "сколько будет двести плюс сорок"})
    answers = fake.texts()
    ok = answers and "240" in answers[0] and not spoken
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} просьба с телефона → «{answers[0] if answers else '—'}»")
    print(f"    вслух сказано: {spoken or 'ничего, как и должно быть'}")

    # 2. Чужой чат: ничего не выполняем, подсказываем, как стать хозяином
    fake.clear()
    phone._handle({"chat": {"id": STRANGER}, "text": "удали все файлы"})
    answers = fake.texts()
    ok = len(answers) == 1 and "только хозяину" in answers[0]
    errors += not ok
    print(f"\n{'ok ' if ok else 'НЕТ'} чужому отказ: «{(answers[0] if answers else '—')[:60]}…»")

    # 3. Голосовой ответ, когда и спросили голосовым
    fake.clear()
    phone.voice_replies = "always"
    phone._to_ogg = lambda text: b"ogg"                   # синтез не гоняем
    phone._handle({"chat": {"id": OWNER}, "text": "который час"})
    ok = len(fake.voices()) == 1
    errors += not ok
    print(f"\n{'ok ' if ok else 'НЕТ'} голосовой ответ отправлен: {len(fake.voices())} (ожидаю 1)")
    phone.voice_replies = "auto"

    # 4. Опасное действие: спросили с телефона — голосом не подтвердить
    fake.clear()
    phone._handle({"chat": {"id": OWNER}, "text": "почисти диск от мусора"})
    asked = fake.texts()
    ok = bool(j.pending) and j.pending_from == "phone"
    errors += not ok
    print(f"\n{'ok ' if ok else 'НЕТ'} с телефона спросил подтверждение: «{(asked[-1] if asked else '—')[:50]}…»")

    spoken.clear()
    import time as _t
    j.awake_until = _t.time() + 30          # как будто разговор голосом уже открыт,
    j.process("да", from_voice=True)        # иначе «да» без имени отбрасывается раньше
    ok = bool(j.pending) and spoken and "подтверди там же" in spoken[-1]
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} голосом не подтверждается: «{(spoken[-1] if spoken else '—')[:60]}»")

    fake.clear()
    phone._handle({"chat": {"id": OWNER}, "text": "да"})
    done = fake.texts()
    ok = not j.pending and done and "0.5" in done[-1]
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} с телефона подтвердилось: «{(done[-1] if done else '—')[:50]}»")

    # 5. Обратное направление: спросили голосом — с телефона не подтвердить
    spoken.clear()
    j.process("почисти диск от мусора", from_voice=False)
    ok = bool(j.pending) and j.pending_from == "voice"
    fake.clear()
    phone._handle({"chat": {"id": OWNER}, "text": "да"})
    answers = fake.texts()
    ok = ok and bool(j.pending) and answers and "подтверди там же" in answers[-1]
    errors += not ok
    print(f"\n{'ok ' if ok else 'НЕТ'} спрошенное голосом с телефона не подтвердить")
    j.pending, j.pending_from = None, ""

    # 6. Напоминание уходит и в телефон
    fake.clear()
    spoken.clear()
    j.notify("Напоминаю: заказать рамстры.")
    ok = any("рамстры" in t for t in fake.texts()) and any("рамстры" in s for s in spoken)
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} напоминание пришло и в телефон, и вслух")

    # Напоминание прозвенело, пока Джарвис отвечает телефону: вслух, а не в чужой ответ
    fake.clear()
    spoken.clear()
    j._quiet, j._answer = True, []
    try:
        j.notify("Напоминаю: полить цветы.")
    finally:
        stolen, j._quiet, j._answer = j._answer, False, []
    ok = (any("цветы" in s for s in spoken) and not stolen
          and sum("цветы" in t for t in fake.texts()) == 1)
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} напоминание во время ответа телефону: вслух и одно в чат, "
          f"в ответ не прилипло ({stolen or 'пусто'})")

    # Связь с Telegram пропала (VPN выключен): напоминание не теряется, а уходит,
    # когда связь вернулась, с честным временем. В журнал — по строке, а не 781
    net = {"up": False}
    delivered = []

    def flaky(method, _wait=20, _files=None, **p):
        if not net["up"]:
            phone.last_error = "SSLError"
            return None
        delivered.append(p.get("text", ""))
        return {"message_id": 1}
    phone._call = flaky
    phone._went_down()
    j.notify("Напоминаю: ученик — 20:00.", {"id": 5, "text": "ученик"})
    queued = len(phone._outbox) == 1 and not delivered
    net["up"] = True
    phone._back_online()
    ok = (queued and not phone._outbox and phone.down_since == 0 and len(delivered) == 1
          and delivered[0].startswith("Напоминаю: ученик — 20:00.") and "не дошло вовремя" in delivered[0])
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} без связи напоминание ждёт и уходит при связи: "
          f"«{delivered[0].splitlines()[-1] if delivered else '—'}»")
    phone._call = fake._call

    # 7. Закреплённая сводка: одно сообщение, правится на месте, только при изменениях
    from core import memory
    phone.pinned = True
    phone.STATE = Path("D:/pytmp/test_phone_digest.json")
    phone.STATE.unlink(missing_ok=True)
    body = ["Дела:\n• завтра в 10:00 — позвонить маме"]
    real_digest = memory.digest
    memory.digest = lambda limit=3800: body[0]
    calls, edit_ok, next_id = [], [True], [77]

    def call(method, _wait=20, _files=None, **p):
        calls.append((method, p))
        if method == "sendMessage":
            next_id[0] += 1
            return {"message_id": next_id[0]}
        if method == "editMessageText":
            return {"message_id": p["message_id"]} if edit_ok[0] else None
        return True
    phone._call = call

    def names():
        out = [m for m, _ in calls]
        calls.clear()
        return out

    try:
        phone.sync_digest()
        first = calls[0][1].get("text", "") if calls else ""
        step1 = names()
        phone.sync_digest()
        step2 = names()
        body[0] += "\n• в пятницу в 18:00 — урок"
        phone.sync_digest()
        step3 = names()
        edit_ok[0] = False                  # хозяин удалил закреп
        body[0] += "\nЗаметки:\n• 07.10 купить фильтр"
        phone.sync_digest()
        step4 = names()
        phone._handle({"chat": {"id": OWNER}, "text": "/notes"})
        step5 = calls[:]
        names()
    finally:
        memory.digest = real_digest
        phone.STATE.unlink(missing_ok=True)

    checks = [
        ("первый раз — прислал и закрепил", step1 == ["sendMessage", "pinChatMessage"]
         and "📌" in first and "обновлено" in first and "позвонить маме" in first),
        ("ничего не поменялось — тишина", step2 == []),
        ("поменялось — правит то же сообщение", step3 == ["editMessageText"]),
        ("сообщение удалили — новое и закреп", step4 == ["editMessageText", "sendMessage", "pinChatMessage"]),
        ("/notes — свежий закреп и ответ", [m for m, _ in step5] == ["sendMessage", "pinChatMessage", "sendMessage"]
         and "без интернета" in step5[-1][1].get("text", "")),
    ]
    for name, ok in checks:
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} сводка: {name}")

    # 8. Привязка по коду: хозяином становится тот, кто прислал код с компьютера
    import json
    settings = Path("D:/pytmp/test_settings.json")
    settings.write_text(json.dumps({"phone": {"owner_id": 0}, "name": "Джарвис"}), encoding="utf-8")
    real_file = config.CONFIG_FILE
    config.CONFIG_FILE = settings
    j.cfg.setdefault("phone", {})["owner_id"] = 0
    try:
        fresh = Phone(j)
        fresh.token, fresh.STATE = "тест", Path("D:/pytmp/test_phone_digest.json")
        pf = FakePhone(fresh)
        code = fresh.pair_code
        import core.phone as phone_module
        phone_module.CURRENT = fresh
        ctx_before = memory.context_for_llm(dialog=True)
        wrong = "000000" if code != "000000" else "111111"
        fresh._handle({"chat": {"id": OWNER}, "text": wrong})
        step_wrong = (fresh.owner == 0 and pf.texts() and "отправь код" in pf.texts()[-1])
        pf.clear()
        fresh._handle({"chat": {"id": OWNER}, "text": " ".join(code)})       # с пробелами, как продиктован
        saved = json.loads(settings.read_text(encoding="utf-8"))
        step_ok = (fresh.owner == OWNER and not fresh.pair_code and pf.texts()
                   and "слушаюсь только тебя" in pf.texts()[0]
                   and saved == {"phone": {"owner_id": OWNER}, "name": "Джарвис"})
        ctx_after = memory.context_for_llm(dialog=True)
        step_ctx = (" ".join(code) in ctx_before and "отправить" in ctx_before
                    and " ".join(code) not in ctx_after)
        pf.clear()
        fresh._handle({"chat": {"id": STRANGER}, "text": code})
        step_reuse = fresh.owner == OWNER and pf.texts() and "только хозяину" in pf.texts()[-1]

        j.cfg["phone"]["owner_id"] = 0          # привязка выше записала хозяина в общие настройки
        brute = Phone(j)
        brute.token = "тест"
        bf = FakePhone(brute)
        for i in range(7):
            brute._handle({"chat": {"id": STRANGER}, "text": f"{i:06d}" if f"{i:06d}" != brute.pair_code else "x"})
        replies = len(bf.texts())
        brute._handle({"chat": {"id": STRANGER}, "text": brute.pair_code})
        step_brute = replies == 5 and brute.owner == 0
    finally:
        config.CONFIG_FILE = real_file
        settings.unlink(missing_ok=True)
    # 9–11. Джарвис и бот — одно целое (живой разговор 07.10.2026: «добавь мне в
    # телеграм» ушло в личный Telegram, Джарвис сказал, что телефона нет)
    from core import brain as B
    import core.phone as phone_module
    real_tasks, real_dialog = memory.TASKS, memory.DIALOG
    memory.TASKS, memory.DIALOG = Path("D:/pytmp/test_tasks.json"), Path("D:/pytmp/test_dialog.json")
    for p in (memory.TASKS, memory.DIALOG):
        p.unlink(missing_ok=True)
    j.cfg["phone"]["owner_id"] = OWNER
    paired = Phone(j)
    paired.token, paired.owner, paired.me = "тест", OWNER, "JarvisforrArtembot"
    paired.STATE = Path("D:/pytmp/test_phone_state.json")
    paired.STATE.unlink(missing_ok=True)
    pp = FakePhone(paired)
    try:
        class Bx:
            phone = paired
        said = B._t_tg_send(Bx(), "@me", "Ученик сегодня в 20:00")
        step_me = pp.texts() == ["Ученик сегодня в 20:00"] and said.startswith("Отправил хозяину")
        Bx.phone = None
        said_none = B._t_tg_send(Bx(), "мне", "тест")
        step_honest = said_none.startswith("НЕ ОТПРАВЛЕНО")

        phone_module.CURRENT = paired
        ctx = memory.context_for_llm(dialog=True)
        step_aware = ("Телефон хозяина подключён" in ctx and "chat='me'" in ctx
                      and "Телефон" not in memory.context_for_llm())     # своей модели — без него

        pp.clear()
        paired.announce_new_tasks()                         # первый раз: старое не объявляем
        memory.add_task("позвонить маме", "сегодня в 23:59")
        n_new = paired.announce_new_tasks()
        announced = [t for t in pp.texts() if t.startswith("📌 Записал")]
        again = paired.announce_new_tasks()
        step_announce = n_new == 1 and len(announced) == 1 and "позвонить маме" in announced[0] and again == 0

        j.phone = paired
        paired._handle({"chat": {"id": OWNER}, "text": "напомни завтра в 10 купить хлеб"})
        pp.clear()
        step_no_dup = paired.announce_new_tasks() == 0 and not pp.texts()

        # Утренний план: раз в день, с brief_at до полудня, только если что-то есть
        from datetime import datetime, timedelta
        day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        memory._save(memory.TASKS, [{"id": 1, "text": "ученик", "when": f"{day:%Y-%m-%d}T20:00",
                                     "done": False, "created": ""}])
        pp.clear()
        early = paired.morning_brief(now=day.replace(hour=7, minute=30))
        sent_morning = paired.morning_brief(now=day.replace(hour=8, minute=30))
        morning = pp.texts()[-1] if pp.texts() else ""
        twice = paired.morning_brief(now=day.replace(hour=9))
        step_brief = (not early and sent_morning and twice is False and len(pp.texts()) == 1
                      and morning.startswith("Доброе утро") and "• 20:00 — ученик" in morning)
        memory._save(memory.TASKS, [])
        next_day = day + timedelta(days=1)
        step_quiet = paired.morning_brief(now=next_day.replace(hour=8, minute=5)) is False \
            and len(pp.texts()) == 1                        # пустой день — ничего не шлёт

        # Файлы с телефона — на компьютер; имена не затираются, «открой его» знает, что открыть
        import shutil
        from skills import files as F
        paired.inbox = Path("D:/pytmp/test_inbox")
        shutil.rmtree(paired.inbox, ignore_errors=True)
        paired._download = lambda file_id: b"%PDF-1.4 test"
        pp.clear()
        paired._handle({"chat": {"id": OWNER}, "document": {"file_id": "x", "file_name": "договор.pdf",
                                                            "file_size": 13}})
        paired._handle({"chat": {"id": OWNER}, "document": {"file_id": "y", "file_name": "договор.pdf",
                                                            "file_size": 13}})
        paired._handle({"chat": {"id": OWNER}, "photo": [{"file_id": "s", "file_size": 5},
                                                         {"file_id": "b", "file_size": 9}]})
        paired._handle({"chat": {"id": OWNER}, "document": {"file_id": "z", "file_name": "фильм.mkv",
                                                            "file_size": 900 * 2**20}})
        saved = sorted(p.name for p in paired.inbox.iterdir())
        replies = pp.texts()
        step_files = (saved[:2] == ["договор (2).pdf", "договор.pdf"] and saved[2].startswith("фото_")
                      and len(saved) == 3 and "Сохранил на компьютер" in replies[0]
                      and "до 20 МБ" in replies[-1] and F.last(1) and F.last(1).endswith(".jpg"))
        shutil.rmtree(paired.inbox, ignore_errors=True)

        sent_cmds = []
        paired._call = lambda method, _wait=20, _files=None, **p: sent_cmds.append((method, p)) or True
        paired.register_commands()
        step_menu = (sent_cmds and sent_cmds[0][0] == "setMyCommands"
                     and '"notes"' in sent_cmds[0][1]["commands"])
        paired._call = pp._call

        # Кнопки под напоминанием: «Сделано» и «отложить» — по номеру задачи и только хозяину
        btn, markup_ok = [], [True]

        def bcall(method, _wait=20, _files=None, **p):
            btn.append((method, p))
            if method == "sendMessage" and "reply_markup" in p and not markup_ok[0]:
                return None
            return {"message_id": 5} if method == "sendMessage" else True
        paired._call, paired.pinned = bcall, False
        memory._save(memory.TASKS, [{"id": 7, "text": "ученик", "when": "2026-10-07T20:00",
                                     "done": False, "fired": True, "created": ""}])
        paired.notify("Напоминаю: ученик — 20:00.", {"id": 7, "text": "ученик"})
        markup = json.loads(btn[0][1].get("reply_markup", "{}")) if btn else {}
        datas = [b["callback_data"] for b in (markup.get("inline_keyboard") or [[]])[0]]
        step_btn_sent = datas == ["done:7", "snooze:7:15", "snooze:7:60"]
        btn.clear()
        paired.notify("Время вышло.", {"id": 8, "text": "таймер", "timer": True})
        markup_ok[0] = False
        paired.notify("Напоминаю: ученик — 20:00.", {"id": 7, "text": "ученик"})
        step_btn_plain = ([("reply_markup" in p) for m, p in btn] == [False, True, False]
                          and btn[-1][1]["text"] == "Напоминаю: ученик — 20:00.")

        msg = {"message_id": 5, "chat": {"id": OWNER}, "text": "Напоминаю: ученик — 20:00."}
        btn.clear()
        paired._handle_button({"id": "q0", "from": {"id": STRANGER}, "data": "done:7",
                               "message": {"message_id": 5, "chat": {"id": STRANGER}}})
        step_btn_stranger = (not memory._load(memory.TASKS, [])[0]["done"]
                             and [m for m, _ in btn] == ["answerCallbackQuery"])
        btn.clear()
        before = datetime.now()
        paired._handle_button({"id": "q1", "from": {"id": OWNER}, "message": msg, "data": "snooze:7:15"})
        t = memory._load(memory.TASKS, [])[0]
        later = (datetime.fromisoformat(t["when"]) - before).total_seconds()
        edits = [p for m, p in btn if m == "editMessageText"]
        step_btn_snooze = (not t.get("fired") and 14 * 60 <= later <= 16 * 60 and len(edits) == 1
                           and "⏰ Отложил: ученик — напомню в" in edits[0]["text"]
                           and "reply_markup" not in edits[0])                 # кнопки убраны
        btn.clear()
        paired._handle_button({"id": "q2", "from": {"id": OWNER}, "message": msg, "data": "done:7"})
        answer = [p.get("text", "") for m, p in btn if m == "answerCallbackQuery"]
        btn.clear()
        paired._handle_button({"id": "q3", "from": {"id": OWNER}, "message": msg, "data": "done:7"})
        again = [p.get("text", "") for m, p in btn if m == "answerCallbackQuery"]
        step_btn_done = (memory._load(memory.TASKS, [])[0]["done"]
                         and answer == ["Отметил выполненным: ученик."] and again == ["Это напоминание уже закрыто."])
        paired._call, paired.pinned = pp._call, True

        j.process("какие у меня задачи", from_voice=False)  # голосом (не из телефона)
        talk = memory.recent_talk()
        step_talk = ("Telegram] хозяин: напомни завтра в 10 купить хлеб" in talk
                     and "голос] хозяин: какие у меня задачи" in talk
                     and "один разговор" in memory.context_for_llm(dialog=True)
                     and "один разговор" not in memory.context_for_llm())
    finally:
        memory.TASKS, memory.DIALOG = real_tasks, real_dialog
        for p in (Path("D:/pytmp/test_tasks.json"), Path("D:/pytmp/test_dialog.json"), paired.STATE,
                  phone.STATE):
            p.unlink(missing_ok=True)
        phone_module.CURRENT = None
    for name, ok in (("«напиши мне» — через бота, сразу", step_me),
                     ("без телефона — честное «не отправлено»", step_honest),
                     ("модель знает, что телефон подключён", step_aware),
                     ("новое дело — «Записал … Напомню здесь», один раз", step_announce),
                     ("записанное с телефона не дублируется", step_no_dup),
                     ("утренний план: в 8:30 один раз, в 7:30 рано", step_brief),
                     ("пустой день — утром тишина", step_quiet),
                     ("файлы с телефона: сохранены, не затёрты, больше 20 МБ — честно", step_files),
                     ("меню команд бота", step_menu),
                     ("под напоминанием кнопки «Сделано», «+15 мин», «+1 час»", step_btn_sent),
                     ("таймер без кнопок; кнопки не прошли — напоминание всё равно дошло", step_btn_plain),
                     ("чужая кнопка ничего не делает", step_btn_stranger),
                     ("«+15 мин»: позвонит снова через 15 минут, кнопки убраны", step_btn_snooze),
                     ("«Сделано»: отмечено, повторное нажатие — «уже закрыто»", step_btn_done),
                     ("разговор общий: голос и Telegram с метками, своей модели — без него", step_talk)):
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} вместе: {name}")

    for name, ok in (("неверный код — просит код, хозяина нет", step_wrong),
                     ("верный код — хозяин, в настройках только owner_id", step_ok),
                     ("тот же код из другого чата уже не работает", step_reuse),
                     ("модель знает код, пока не привязан, и забывает после", step_ctx),
                     ("подбор: 5 ответов, потом тишина, и код уже не принят", step_brute)):
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} привязка: {name}")

    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
