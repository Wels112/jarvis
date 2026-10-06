# -*- coding: utf-8 -*-
"""Учебник глазами модели: совпадает ли текст в Colab с текстом у хозяина.

Модель учится на тексте, который строит шаблон чата Hugging Face (так в
ноутбуке), а работает на тексте от шаблона, зашитого в GGUF, — его строит
llama.cpp у хозяина. Разойдись они хоть в пробеле перед вызовом инструмента —
выученное не сработает, и узнали бы мы об этом только после часа обучения.

Проверяет:
  1. запросы проверочных фраз (system + вопрос + начало ответа) — посимвольно;
  2. учебные примеры целиком, вместе с вызовами инструментов и их результатами;
  3. длину каждого примера в токенах: влезает ли в контекст обучения и сколько
     всего токенов — от этого зависит время в Colab.

Нужен transformers той же версии, что в ноутбуке (5.2.0). В окружение Джарвиса
он не ставится — отдельное окружение:
  py -3.12 -m venv llm\\nbtest\\venv
  llm\\nbtest\\venv\\Scripts\\python -m pip install transformers==5.2.0
  llm\\nbtest\\venv\\Scripts\\python train\\check_template.py
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "train" / "data"
LLM = ROOT / "llm"
os.environ.setdefault("HF_HOME", str(LLM / "nbtest" / "hf"))   # не на забитый C:
BASE = "unsloth/Qwen3.5-2B"
MODEL = LLM / "models" / "Qwen3.5-2B-Q4_K_M.gguf"
PORT = 8091                 # не 8090: там может работать сам Джарвис
MAX_LEN = 8192              # как в ноутбуке

NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def post(path, body):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        return json.loads(NO_PROXY.open(req, timeout=60).read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"llama.cpp {e.code}: {e.read().decode('utf-8', 'replace')[:400]}") from None


def openai_format(messages):
    """Аргументы вызова — строкой JSON, как их шлёт клиент OpenAI-формата."""
    out = []
    for m in messages:
        m = dict(m)
        if m.get("tool_calls"):
            m["tool_calls"] = [{"type": "function", "function": {
                "name": c["function"]["name"],
                "arguments": json.dumps(c["function"]["arguments"], ensure_ascii=False)}}
                for c in m["tool_calls"]]
        out.append(m)
    return out


def first_diff(a, b):
    i = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]), min(len(a), len(b)))
    return i, a[max(0, i - 80):i + 80], b[max(0, i - 80):i + 80]


def main():
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(BASE)
    system = (DATA / "system.txt").read_text(encoding="utf-8")
    tools = [{"type": "function", "function": t}
             for t in json.loads((DATA / "tools.json").read_text(encoding="utf-8"))]
    train = [json.loads(l) for l in (DATA / "train.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    test = [json.loads(l) for l in (DATA / "test.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

    def hf(messages, gen):
        return tok.apply_chat_template([{"role": "system", "content": system}] + messages,
                                       tools=tools, tokenize=False, add_generation_prompt=gen,
                                       enable_thinking=False)

    # 3. Длины — без сервера
    lens = [len(tok(hf(i["messages"], False), add_special_tokens=False)["input_ids"]) for i in train]
    over = sum(n > MAX_LEN for n in lens)
    print(f"токенов в учебном примере: от {min(lens)} до {max(lens)}, в среднем "
          f"{sum(lens) // len(lens)}; длиннее {MAX_LEN}: {over}; всего {sum(lens) / 1e6:.1f} млн")

    server = subprocess.Popen(
        [str(LLM / "bin" / "llama-server.exe"), "-m", str(MODEL), "-c", "4096", "-ngl", "0",
         "--jinja", "-np", "1", "--host", "127.0.0.1", "--port", str(PORT)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    errors = 0
    try:
        for _ in range(240):
            try:
                if NO_PROXY.open(f"http://127.0.0.1:{PORT}/health", timeout=2).status == 200:
                    break
            except Exception:
                time.sleep(0.5)
        else:
            print("сервер llama.cpp не поднялся")
            return False

        def lcpp(messages):
            return post("/apply-template", {
                "messages": [{"role": "system", "content": system}] + openai_format(messages),
                "tools": tools, "chat_template_kwargs": {"enable_thinking": False}})["prompt"]

        # 1. Запрос, на который модель отвечает у хозяина
        same = 0
        for item in test:
            a, b = hf(item["messages"][:1], True), lcpp(item["messages"][:1])
            if a == b:
                same += 1
            elif same == 0 and errors == 0:
                i, x, y = first_diff(a, b)
                print(f"   расхождение в символе {i}:\n   HF:    {x!r}\n   llama: {y!r}")
            errors += a != b
        print(f"{'ok ' if same == len(test) else 'НЕТ'} запросы проверочных фраз: "
              f"совпали {same} из {len(test)}")

        # 2. Учебные примеры целиком. Последний ответ ассистента llama.cpp
        # показывать отказывается («нельзя продолжить ответ с вызовом
        # инструмента»), поэтому дописываем за ним результат инструмента —
        # тогда вызов, со всеми аргументами, виден посреди разговора
        same = 0
        shown = False

        def report(item, a, b):
            nonlocal shown
            if not shown:
                shown = True
                i, x, y = first_diff(a, b)
                print(f"   расхождение в символе {i} ({item.get('intent')}):\n"
                      f"   HF:    {x!r}\n   llama: {y!r}")

        for item in train:
            msgs = item["messages"]
            if not msgs[-1].get("tool_calls"):
                # Ответ словами: llama.cpp держит его открытым для продолжения
                # (без <|im_end|>), поэтому сверяем начало
                a, b = hf(msgs, False), lcpp(msgs)
                ok = a.rstrip() == b.rstrip() or a.startswith(b.rstrip())
                if not ok:
                    report(item, a, b)
                same += ok
                continue
            msgs = msgs + [{"role": "tool", "content": "Готово."}]
            a, b = hf(msgs, True), lcpp(msgs)
            ok = a == b
            if ok:
                # И сама цель обучения — то, что модель допишет после
                # «<think></think>», — должна быть тем же вызовом, что llama.cpp
                # ставит в разговор (и, значит, умеет разобрать в ответе)
                prompt = hf(item["messages"][:-1], True)
                target = hf(item["messages"], False)
                start = a.rindex("<|im_start|>assistant\n", 0, a.rindex("<tool_response>"))
                in_dialog = a[start + len("<|im_start|>assistant\n"):a.index("<|im_end|>", start)]
                # Пустые рассуждения Qwen3.5 ставит и перед вызовом посреди
                # разговора; в учебной цели они уже в запросе, сверяем вызов
                in_dialog = in_dialog.split("</think>\n\n", 1)[-1]
                ok = (target.startswith(prompt) and
                      target[len(prompt):].rstrip() == (in_dialog + "<|im_end|>").rstrip())
                if not ok:
                    report(item, target[len(prompt):], in_dialog + "<|im_end|>")
            else:
                report(item, a, b)
            same += ok
        print(f"{'ok ' if same == len(train) else 'НЕТ'} учебные примеры целиком: "
              f"совпали {same} из {len(train)}")
        errors += same != len(train)

        sample = next(i for i in train if i["messages"][-1].get("tool_calls"))
        print("\nхвост учебного примера (так модель учится звать инструмент):")
        print(hf(sample["messages"], False)[-260:])
    finally:
        server.terminate()
    return errors == 0 and over == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
