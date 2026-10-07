# -*- coding: utf-8 -*-
"""Telegram: читать чаты, отвечать, слать сообщения — голосом.

Работает через Telethon от твоего личного аккаунта (не бот), поэтому видит все
обычные чаты, как настоящий помощник, а не отдельный робот в углу.

Граница безопасности проходит здесь жёстко: читать Джарвис может свободно,
но **любая отправка наружу возвращается как отложенное действие** и уходит
только после устного «да». Ошибка распознавания не должна отправлять твоей маме
случайную фразу.

Первый запуск — авторизация: python -m skills.telegram login
"""
import asyncio
import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

SESSION = str(config.ROOT / "config" / "tg_session")

# Ответ модели, когда API не подключён. Жёсткий неспроста: на живом тесте модель,
# получив «не подключён», стала печатать в окно Telegram нажатиями клавиш — и
# отправила текст не туда. Прямо запрещаем этот путь и говорим, что делать.
NOT_CONNECTED = ("Telegram не подключён к Джарвису. Не пытайся писать, переключать чаты или "
                 "открывать их нажатием клавиш, через PowerShell или type_text — текст уйдёт "
                 "не в тот чат. Скажи хозяину, что для этого Telegram нужно подключить "
                 "через setup.bat, это пара минут.")


async def _find_dialog(c, name: str):
    """Чат по имени, сказанному голосом: «Хомяк тупс» должен найти «Хомяк Туп».

    Сначала точное совпадение, потом вхождение, потом похожее по написанию —
    распознавание речи коверкает имена чатов так же, как имена людей.
    """
    want = name.strip().lower()
    dialogs = [d async for d in c.iter_dialogs(limit=300)]
    for d in dialogs:
        if (d.name or "").strip().lower() == want:
            return d
    for d in dialogs:
        if want and want in (d.name or "").lower():
            return d
    titles = [(d.name or "").lower() for d in dialogs]
    close = difflib.get_close_matches(want, titles, n=1, cutoff=0.72)
    if close:
        return dialogs[titles.index(close[0])]
    return None


def _creds():
    return config.env("TELEGRAM_API_ID"), config.env("TELEGRAM_API_HASH")


def ready() -> bool:
    api_id, api_hash = _creds()
    return bool(api_id and api_hash and Path(SESSION + ".session").exists())


def _client():
    from telethon import TelegramClient
    api_id, api_hash = _creds()
    if not api_id or not api_hash:
        raise RuntimeError("нет TELEGRAM_API_ID / TELEGRAM_API_HASH в config/.env")
    return TelegramClient(SESSION, int(api_id), api_hash)


def _run(coro):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        try:
            loop.close()
        except Exception:
            pass


# ---------------- чтение ----------------
async def _unread(limit: int):
    c = _client()
    await c.connect()
    if not await c.is_user_authorized():
        return "Telegram не авторизован. Запусти один раз: python -m skills.telegram login"
    out = []
    async for d in c.iter_dialogs(limit=40):
        if d.unread_count and not d.is_channel:
            out.append(f"{d.name} — {d.unread_count}")
        if len(out) >= limit:
            break
    await c.disconnect()
    if not out:
        return "Непрочитанных сообщений нет."
    return f"Непрочитано в {len(out)} чатах: " + "; ".join(out) + "."


def unread(limit: int = 6) -> str:
    if not ready():
        return NOT_CONNECTED
    try:
        return _run(_unread(limit))
    except Exception as e:
        return f"Telegram не ответил: {e}"


async def _read_chat(name: str, n: int):
    c = _client()
    await c.connect()
    try:
        if not await c.is_user_authorized():
            return NOT_CONNECTED
        d = await _find_dialog(c, name)
        if d is None:
            return f"Чат «{name}» не нашёл."
        msgs = []
        async for m in c.iter_messages(d.entity, limit=n):
            if m.text:
                who = "ты" if m.out else (getattr(m.sender, "first_name", None) or d.name)
                msgs.append(f"{who}: {m.text[:160]}")
        if not msgs:
            return f"В чате «{d.name}» пусто."
        return f"Чат «{d.name}»: " + " | ".join(reversed(msgs))
    finally:
        await c.disconnect()


def read_chat(name: str, n: int = 5) -> str:
    if not ready():
        return NOT_CONNECTED
    try:
        return _run(_read_chat(name, n))
    except Exception as e:
        return f"Telegram не ответил: {e}"


# ---------------- открыть чат в приложении ----------------
async def _chat_link(name: str):
    c = _client()
    await c.connect()
    try:
        if not await c.is_user_authorized():
            return None, NOT_CONNECTED
        d = await _find_dialog(c, name)
        if d is None:
            return None, f"Чат «{name}» не нашёл."
        ent = d.entity
        username = getattr(ent, "username", None)
        if not username and getattr(ent, "usernames", None):
            username = ent.usernames[0].username
        if username:
            return f"tg://resolve?domain={username}", d.name
        if getattr(ent, "phone", None):
            return f"tg://resolve?phone={ent.phone}", d.name
        if d.is_channel and d.message:                    # каналы и большие группы
            return f"tg://privatepost?channel={ent.id}&post={d.message.id}", d.name
        return None, (f"Нашёл «{d.name}», но у этого чата нет ни имени пользователя, ни "
                      "номера — открыть его ссылкой нельзя. Могу прочитать или написать туда.")
    finally:
        await c.disconnect()


def open_chat(name: str) -> str:
    """Открыть чат в Telegram Desktop ссылкой tg:// — без единого нажатия клавиш.

    Живой тест показал, почему не клавишами: Ctrl+K в поле сообщения — это
    «вставить ссылку», и текст для поиска чата уходил сообщением в открытый чат.
    """
    import os
    if not ready():
        return NOT_CONNECTED
    try:
        link, title = _run(_chat_link(name))
    except Exception as e:
        return f"Telegram не ответил: {e}"
    if not link:
        return title
    try:
        os.startfile(link)
        return f"Открыл чат «{title}»."
    except Exception as e:
        return f"Не смог открыть Telegram: {e}"


# ---------------- отправка (только через подтверждение) ----------------
async def _resolve(name: str):
    c = _client()
    await c.connect()
    try:
        if not await c.is_user_authorized():
            return None
        d = await _find_dialog(c, name)
        return (d.name, d.id) if d else None
    finally:
        await c.disconnect()


async def _send(peer_id: int, text: str):
    c = _client()
    await c.connect()
    try:
        await c.send_message(peer_id, text)
    finally:
        await c.disconnect()


def send_message_confirmed(peer_id: int, title: str, text: str) -> str:
    """Реальная отправка. Дёргается ТОЛЬКО из подтверждённого действия."""
    if not ready():
        return NOT_CONNECTED
    try:
        _run(_send(peer_id, text))
        return f"Отправил в «{title}»."
    except Exception as e:
        return f"Не отправилось: {e}"


def prepare_send(name: str, text: str):
    """(описание, действие) для подтверждения голосом — или (None, почему нельзя).

    Получатель ищется ДО вопроса, и в вопросе звучит его настоящее имя. Иначе
    хозяин подтвердил бы «Маме», а сообщение по вхождению слова ушло бы в
    «Мамин клуб» — подтверждение должно относиться ровно к тому, что случится.
    """
    if not ready():
        # Без входа в личный Telegram — через приложение на компьютере, только в открытый чат
        from skills import tg_desktop
        return tg_desktop.prepare(name, text)
    try:
        found = _run(_resolve(name))
    except Exception as e:
        return None, f"Telegram не ответил: {e}"
    if not found:
        return None, f"Чат «{name}» не нашёл. Уточни у хозяина, как он называется."
    title, peer_id = found
    desc = f"отправить в чат «{title}» сообщение: «{text}»"
    return desc, (lambda: send_message_confirmed(peer_id, title, text))


# ---------------- авторизация ----------------
async def _login():
    c = _client()
    print("\nСейчас Telegram спросит номер телефона и код из приложения.")
    print("Код вводишь ТЫ сам — Джарвис его не видит и не сохраняет.\n")
    await c.start()
    me = await c.get_me()
    print(f"\nГотово. Вошёл как {me.first_name} (@{me.username}).")
    await c.disconnect()


if __name__ == "__main__":
    config.setup_console()
    if len(sys.argv) > 1 and sys.argv[1] == "login":
        api_id, api_hash = _creds()
        if not api_id or not api_hash:
            print("Сначала впиши TELEGRAM_API_ID и TELEGRAM_API_HASH в D:\\jarvis\\config\\.env")
            print("Получить: https://my.telegram.org → API development tools")
            sys.exit(1)
        _run(_login())
    else:
        print("подключён:", "да" if ready() else "нет — нужен вход")
        if ready():
            print(unread())
