# -*- coding: utf-8 -*-
"""Обрыв связи посреди живого разговора: переподключиться, а не выпадать.

Сеть не трогается: подключение и сам разговор подменены, проверяется только
решение — что считать обрывом и что делать дальше. Повод — показ 02.10.2026,
где «1011 Internal error» уводил Джарвиса на медленный путь на десять минут.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config


class Stub:
    def __init__(self):
        self.cfg = config.CFG
        self.ears = type("E", (), {"_noise": 0.006, "flush": lambda s: None})()
        self.running, self.paused = True, False


def main():
    config.setup_console()
    from core.live import LiveConversation
    from google.genai import errors as gerrors
    import ssl

    live = LiveConversation(Stub())
    errors = 0

    # 1. Что считать обрывом, а что отказом сервиса
    cases = [
        (gerrors.APIError(1011, {}, None), True, "1011 внутренняя ошибка"),
        (ConnectionResetError("разорвано"), True, "соединение сброшено"),
        (ssl.SSLError("[SSL: DECRYPTION_FAILED_OR_BAD_RECORD_MAC] bad record mac"), True, "мусор в TLS"),
        (gerrors.APIError(429, {}, None), False, "кончилась квота"),
        (gerrors.APIError(400, {}, None), False, "плохой запрос"),
        (gerrors.APIError(403, {}, None), False, "отказ по ключу"),
        (ValueError("сломался разбор"), False, "ошибка в коде"),
    ]
    for err, want, label in cases:
        got = live._transport_broke(err)
        errors += got != want
        print(f"{'ok ' if got == want else 'НЕТ'} {label:26} → "
              f"{'переподключаюсь' if got else 'откат на старый путь'}")

    # 2. Обрыв на полуслове: новое подключение, фраза не отправляется заново,
    #    а недосказанное передаётся, чтобы модель договорила
    calls = []

    async def fake_connect():
        live._connect_s = 0.5
        return object(), object()

    async def fake_conversation(ctx, session, first_audio, reason, how, resume=None):
        calls.append({"audio": first_audio is not None, "how": how, "resume": resume})
        if len(calls) == 1:
            live.said_turn = "Солнце держит всё вокруг своей гравитацией, а дальше"
            live.turn_open = True
            raise gerrors.APIError(1011, {}, None)
        return "idle"

    live._connect, live._conversation = fake_connect, fake_conversation
    result = asyncio.run(live._with_reconnect(first_audio=[1, 2, 3], reason="name"))
    ok = (result == "idle" and len(calls) == 2 and calls[0]["audio"]
          and not calls[1]["audio"] and "договор" not in str(calls[0]["resume"] or "")
          and calls[1]["resume"] and "гравитацией" in calls[1]["resume"])
    errors += not ok
    print(f"\n{'ok ' if ok else 'НЕТ'} после обрыва: подключений {len(calls)}, итог «{result}»")
    print(f"    второй раз фраза заново не отправлена: {not calls[1]['audio']}")
    print(f"    модели передано недосказанное: «{(calls[1]['resume'] or '')[:50]}»")

    # 3. Отказ сервиса переподключением не лечится — должен дойти до хозяина
    calls.clear()

    async def quota(ctx, session, first_audio, reason, how, resume=None):
        calls.append(how)
        raise gerrors.APIError(429, {}, None)

    live._conversation = quota
    try:
        asyncio.run(live._with_reconnect(first_audio=None, reason="name"))
        passed = False
    except gerrors.APIError:
        passed = len(calls) == 1
    errors += not passed
    print(f"{'ok ' if passed else 'НЕТ'} нехватка квоты: попыток {len(calls)} (ожидаю 1), "
          f"ошибка отдана наверх")

    # 4. Три обрыва подряд — сдаёмся, иначе будем долбить сервер молча
    calls.clear()

    async def always_broken(ctx, session, first_audio, reason, how, resume=None):
        calls.append(how)
        live.turn_open = False
        raise gerrors.APIError(1011, {}, None)

    live._conversation = always_broken
    try:
        asyncio.run(live._with_reconnect(first_audio=None, reason="name"))
        passed = False
    except gerrors.APIError:
        passed = len(calls) == 3
    errors += not passed
    print(f"{'ok ' if passed else 'НЕТ'} связь не вернулась: попыток {len(calls)} (ожидаю 3), "
          f"дальше откат на старый путь")

    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
