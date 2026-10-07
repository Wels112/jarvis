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

    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
