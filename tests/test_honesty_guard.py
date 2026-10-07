# -*- coding: utf-8 -*-
"""Сторож честности живого разговора — на фразах из настоящего журнала.

07.10.2026 живая модель получила от инструмента «Telegram не подключён к
Джарвису» и сказала хозяину: «И в телегу продублировал, на этот раз точно
должно прийти». Сторож должен поймать такое и попросить поправиться — но не
трогать честный отказ и обычные удачные ответы. Сеть не нужна.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config


def main():
    config.setup_console()
    from core import live as L
    errors = 0
    tg_fail = ("telegram_send", "Telegram не подключён к Джарвису. Не пытайся писать, переключать чаты")

    cases = [
        ("врёт про Telegram (журнал 07.10)",
         "Всё, исправил на 8 вечера. Напомню сегодня в 20:00. И в телегу продублировал, "
         "на этот раз точно должно прийти.", [tg_fail], True),
        ("честный отказ (журнал 07.10)",
         "Слушай, не получилось отправить в Telegram. Похоже, телефон не подключён.", [tg_fail], False),
        ("успех без отказов", "Открываю ya.ru, сейчас будет Яндекс.", [], False),
        ("видео не остановилось, а сказал «остановил»", "Остановил видео.",
         [("video", "Видео не остановилось — звук всё ещё идёт")], True),
        ("ждёт «да», а сказал «отправил»", "Отправил Саше.",
         [("telegram_send", "ТРЕБУЕТСЯ ПОДТВЕРЖДЕНИЕ: написать Саше «буду поздно»")], True),
        ("спрашивает подтверждение — не ложь", "Отправить Саше «буду поздно»?",
         [("telegram_send", "ТРЕБУЕТСЯ ПОДТВЕРЖДЕНИЕ: написать Саше «буду поздно»")], False),
    ]
    for name, said, failures, want in cases:
        got = bool(L.false_claim(said, failures))
        errors += got != want
        print(f"{'ok ' if got == want else 'НЕТ'} {name}: {'поймал' if got else 'молчит'}")

    # Отказ распознаётся в настоящих ответах инструментов
    for result, want in (("НЕ ОТПРАВЛЕНО: телефон не подключён", True),
                         ("Telegram не подключён к Джарвису.", True),
                         ("Не нашёл программу «фотошоп» среди установленных.", True),
                         ("ошибка: timeout", True),
                         ("Записал: Ученик. Напомню 07.10 в 20:00.", False),
                         ("Задач нет, всё чисто.", False),
                         ("Отправил хозяину в Telegram: «привет».", False)):
        got = bool(L.TOOL_FAILED.search(result))
        errors += got != want
        print(f"{'ok ' if got == want else 'НЕТ'} отказ ли: «{result[:45]}» → {got}")

    # Весь путь: ход с отказом → фраза об успехе → просьба поправиться ушла в разговор
    conv = L.LiveConversation.__new__(L.LiveConversation)
    sent = []
    conv.inject = lambda text: sent.append(text) or True
    conv.turn_failures = [tg_fail]
    conv.said_turn = "И в телегу продублировал."
    conv._flush_said()
    ok = len(sent) == 1 and "Telegram не подключён" in sent[0] and conv.turn_failures == []
    conv.said_turn = "Ещё что-нибудь?"
    conv._flush_said()
    ok = ok and len(sent) == 1                   # следующий ход чистый — повторно не дёргаем
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} поправка ушла в разговор один раз")

    # Обычный мозг (сообщения из Telegram, голос без живого режима): модель
    # подменена, сеть не нужна
    from core import brain as B

    def scripted(*answers):
        replies = iter(answers)

        def post(payload):
            return {"candidates": [{"content": {"parts": [next(replies)]}}]}
        return post

    call = {"functionCall": {"name": "telegram_send", "args": {"chat": "Саша", "text": "буду поздно"}}}
    b = B.Brain(config.CFG)
    b._post = scripted(call, {"text": "Отправил Саше: буду поздно."},
                       {"text": "Не получилось: Telegram не подключён."})
    answer = b.ask("напиши Саше что буду поздно")
    nudges = [p["text"] for h in b.history if h["role"] == "user" for p in h["parts"]
              if "text" in p and p["text"].startswith("(Система")]
    ok = answer.startswith("Не получилось") and len(nudges) == 1
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} мозг переспросил себя и ответил честно: «{answer}»")

    b = B.Brain(config.CFG)
    b._post = scripted(call, {"text": "Не получилось отправить: Telegram не подключён."})
    answer = b.ask("напиши Саше что буду поздно")
    ok = answer.startswith("Не получилось отправить")
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} честный ответ не трогает: «{answer}»")

    # Действие на словах без единого инструмента: «Уже нажимаю» (проверка 07.10.2026)
    from core.honesty import unbacked_claim
    for said, tools, want in (("Уже нажимаю.", 0, True), ("Открываю YouTube.", 0, True),
                              ("Нажал.", 1, False), ("Не могу нажать — кнопки не вижу.", 0, False),
                              ("Привет! Чем помочь?", 0, False), ("Сейчас включу.", 0, False)):
        got = bool(unbacked_claim(said, tools))
        errors += got != want
        print(f"{'ok ' if got == want else 'НЕТ'} без инструмента «{said}» ({tools} вызовов): "
              f"{'поймал' if got else 'молчит'}")

    b = B.Brain(config.CFG)
    clicked = []
    b._run_tool = lambda name, args: clicked.append(name) or "Нажал «YouTube» в окне «Chrome»."
    b._post = scripted({"text": "Уже нажимаю."},
                       {"functionCall": {"name": "ui_click", "args": {"name": "YouTube"}}},
                       {"text": "Нажал."})
    answer = b.ask("Можешь моей мышкой нажать на YouTube?")
    ok = clicked == ["ui_click"] and answer == "Нажал."
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} мозг: «Уже нажимаю» без вызова → дожал до инструмента: {clicked} «{answer}»")

    # Живой режим: подозрение ждёт полторы секунды и снимается, если вызов пришёл
    conv = L.LiveConversation.__new__(L.LiveConversation)
    sent = []
    conv.inject = lambda text: sent.append(text) or True
    conv.turn_failures, conv.turn_tools, conv.unbacked = [], 0, None
    conv.said_turn = "Открываю YouTube."
    conv._flush_said()
    waits = conv.unbacked is not None and not sent and not conv._check_unbacked()
    conv.unbacked = (conv.unbacked[0], conv.unbacked[1] - 2)          # прошло 2 секунды
    fired = conv._check_unbacked() and len(sent) == 1 and "не вызвал ни одного" in sent[0]
    conv.said_turn = "Открываю YouTube."
    conv._flush_said()
    conv.unbacked = None                                            # пришёл вызов инструмента
    quiet = not conv._check_unbacked() and len(sent) == 1
    ok = waits and fired and quiet
    errors += not ok
    print(f"{'ok ' if ok else 'НЕТ'} живой режим: ждёт, потом просит; пришёл вызов — молчит")

    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
