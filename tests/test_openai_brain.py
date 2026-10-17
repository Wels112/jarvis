# -*- coding: utf-8 -*-
"""Облачный мозг через OpenAI-совместимый API: формат запроса, вызов инструментов,
честность, зрение. Провайдер (сеть) подменён — настоящий ключ не нужен.

Так заказчик вписывает ключ любой нейросети (российский посредник без VPN,
OpenAI, DeepSeek). Инструменты и сторожа честности — те же, что у Gemini-мозга.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import config


def msg(content=None, tool_calls=None):
    """Ответ провайдера в формате OpenAI."""
    m = {"role": "assistant", "content": content or ""}
    if tool_calls:
        m["tool_calls"] = tool_calls
    return {"choices": [{"message": m}]}


def tool_call(name, args, cid="c1"):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}


def main():
    config.setup_console()
    from core.brain import make_cloud_brain
    from core.openai_brain import OpenAIBrain
    errors = 0

    def check(name, ok, detail=""):
        nonlocal errors
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} {name}{' — ' + str(detail)[:120] if detail else ''}")

    cfg = dict(config.CFG)
    cfg["brain"] = dict(config.CFG["brain"], provider="openai",
                        base_url="https://proxy.example/v1", model="gpt-4o-mini")

    # фабрика выбирает OpenAIBrain по provider
    check("provider=openai → OpenAIBrain", isinstance(make_cloud_brain(cfg), OpenAIBrain))
    cfg_g = dict(config.CFG); cfg_g["brain"] = dict(config.CFG["brain"], provider="gemini")
    from core.brain import Brain
    check("provider=gemini → обычный Brain", type(make_cloud_brain(cfg_g)) is Brain)

    # 1. Простой ответ: один запрос, никаких инструментов
    b = OpenAIBrain(cfg)
    b.key = "test"
    sent = []
    b._post = lambda payload, timeout=45: (sent.append(payload), msg("Два плюс два — четыре."))[1]
    answer = b.ask("сколько будет два плюс два")
    first = sent[0]
    check("простой ответ", answer == "Два плюс два — четыре." and b.last_error is None, answer)
    check("системный промпт первым, формат messages", first["messages"][0]["role"] == "system"
          and first["messages"][1] == {"role": "user", "content": "сколько будет два плюс два"})
    check("инструменты в формате OpenAI", first["tools"][0]["type"] == "function"
          and "name" in first["tools"][0]["function"])

    # 2. Вызов инструмента: провайдер просит timer, получает результат, отвечает
    b = OpenAIBrain(cfg); b.key = "test"
    ran = []
    b._run_tool = lambda name, args: ran.append((name, args)) or "Таймер на 5 минут."
    replies = iter([msg(tool_calls=[tool_call("timer", {"minutes": 5})]), msg("Поставил на пять минут.")])
    captured = []
    b._post = lambda payload, timeout=45: (captured.append(payload), next(replies))[1]
    answer = b.ask("поставь таймер на пять минут")
    last = captured[-1]["messages"]
    check("инструмент вызван с аргументами", ran == [("timer", {"minutes": 5})], ran)
    check("ответ инструмента ушёл ролью tool", any(m.get("role") == "tool" and m["content"] == "Таймер на 5 минут."
                                                    for m in last))
    check("assistant с tool_calls в истории", any(m.get("role") == "assistant" and m.get("tool_calls") for m in last))
    check("итог хозяину", answer == "Поставил на пять минут.", answer)

    # 3. Честность: инструмент отказал, модель сказала «отправил» — один раз переспрашиваем
    b = OpenAIBrain(cfg); b.key = "test"
    b._run_tool = lambda name, args: "НЕ ОТПРАВЛЕНО: телефон не подключён."
    replies = iter([msg(tool_calls=[tool_call("telegram_send", {"chat": "мне", "text": "привет"})]),
                    msg("Отправил."),                         # ложь вопреки отказу
                    msg("Не получилось: телефон не подключён.")])
    nudges = []
    def post3(payload, timeout=45):
        nudges.append([m for m in payload["messages"] if m.get("role") == "user"
                       and str(m.get("content", "")).startswith("(Система")])
        return next(replies)
    b._post = post3
    answer = b.ask("напиши мне привет")
    asked = sum(1 for turn in nudges for _ in turn)
    check("ложь об успехе → переспросил себя один раз, ответил честно",
          answer.startswith("Не получилось") and asked == 1, f"{answer} / переспросов {asked}")

    # 4. Зрение: формат OpenAI image_url
    b = OpenAIBrain(cfg); b.key = "test"
    seen = []
    b._post = lambda payload, timeout=45: (seen.append(payload), msg("На экране браузер."))[1]
    said = b.vision("что на экране", "AAAA")
    content = seen[0]["messages"][0]["content"]
    check("зрение: image_url с data-ссылкой", said == "На экране браузер."
          and content[1]["type"] == "image_url" and content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,AAAA"))

    # 5. Сбой сети → человеческая фраза, ход из истории убран
    b = OpenAIBrain(cfg); b.key = "test"
    b._post = lambda payload, timeout=45: (_ for _ in ()).throw(RuntimeError("429: RESOURCE_EXHAUSTED"))
    answer = b.ask("как дела")
    check("перегрузка → про лимит, история чистая", "лимит" in answer.lower() and b.history == [] and b.last_error is not None, answer)

    # 6. Имя модели от Gemini при openai — заменяется на безопасное
    cfg_bad = dict(config.CFG); cfg_bad["brain"] = dict(config.CFG["brain"], provider="openai", model="gemini-3.5-flash-lite")
    check("gemini-модель на openai → gpt-4o-mini", OpenAIBrain(cfg_bad).model == "gpt-4o-mini")

    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
