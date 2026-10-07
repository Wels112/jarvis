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
        ctx_before = memory.context_for_llm()
        wrong = "000000" if code != "000000" else "111111"
        fresh._handle({"chat": {"id": OWNER}, "text": wrong})
        step_wrong = (fresh.owner == 0 and pf.texts() and "отправь код" in pf.texts()[-1])
        pf.clear()
        fresh._handle({"chat": {"id": OWNER}, "text": " ".join(code)})       # с пробелами, как продиктован
        saved = json.loads(settings.read_text(encoding="utf-8"))
        step_ok = (fresh.owner == OWNER and not fresh.pair_code and pf.texts()
                   and "слушаюсь только тебя" in pf.texts()[0]
                   and saved == {"phone": {"owner_id": OWNER}, "name": "Джарвис"})
        ctx_after = memory.context_for_llm()
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
