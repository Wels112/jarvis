# -*- coding: utf-8 -*-
"""Своя модель на своей видеокарте: справляется ли она с задачами Джарвиса.

Те же 14 фраз хозяина с показа, на которых Gemini выбрал верный инструмент
14 из 14 за 0,85 с (tests/probe_tool_choice.py). Модель работает локально через
llama.cpp, без интернета и без ключей. Мерится то же самое: попала ли в
инструмент, сколько думала, и разумны ли аргументы.

Модель и сервер лежат в D:\\jarvis\\llm (в репозиторий не попадают).
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

LLM = config.ROOT / "llm"
PORT = 8090
URL = f"http://127.0.0.1:{PORT}"


def openai_tools(tools):
    """Описания инструментов Джарвиса в формате, который понимает llama.cpp."""
    return [{"type": "function", "function": {
        "name": t["name"], "description": t.get("description", ""),
        "parameters": t.get("parameters") or {"type": "object", "properties": {}}}}
        for t in tools]


def vram_used() -> str:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total",
                              "--format=csv,noheader"], capture_output=True, text=True,
                             timeout=10).stdout.strip()
        return out
    except Exception:
        return "?"


def start_server(model: Path, ctx: int, gpu_layers: int):
    exe = LLM / "bin" / "llama-server.exe"
    args = [str(exe), "-m", str(model), "-c", str(ctx), "-ngl", str(gpu_layers),
            "--jinja", "--host", "127.0.0.1", "--port", str(PORT), "-np", "1"]
    log = open(LLM / "server.log", "w", encoding="utf-8")
    proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    local = requests.Session()
    local.trust_env = False               # мимо системного прокси: сервер у нас же
    t0 = time.monotonic()
    while time.monotonic() - t0 < 180:
        if proc.poll() is not None:
            raise RuntimeError("сервер упал при запуске, смотри llm/server.log")
        try:
            if local.get(f"{URL}/health", timeout=2).status_code == 200:
                return proc, local, time.monotonic() - t0
        except Exception:
            pass
        time.sleep(0.5)
    proc.kill()
    raise RuntimeError("сервер не поднялся за 3 минуты")


def ask(local, system: str, tools, phrase: str):
    payload = {
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": phrase}],
        "tools": tools, "tool_choice": "auto",
        "temperature": 0, "max_tokens": 200,
        # Без рассуждений вслух: для выбора инструмента они только тратят время
        "chat_template_kwargs": {"enable_thinking": False},
    }
    t0 = time.monotonic()
    r = local.post(f"{URL}/v1/chat/completions", json=payload, timeout=180)
    took = time.monotonic() - t0
    r.raise_for_status()
    msg = r.json()["choices"][0]["message"]
    calls = [(c["function"]["name"], c["function"].get("arguments", ""))
             for c in msg.get("tool_calls") or []]
    return calls, (msg.get("content") or "").strip(), took


def main():
    config.setup_console()
    from core import brain as B
    from tests.probe_tool_choice import CASES

    model = next((LLM / "models").glob(sys.argv[1] if len(sys.argv) > 1 else "*.gguf"))
    print(f"модель: {model.name} ({model.stat().st_size / 1e9:.2f} ГБ)")
    print(f"видеопамять до запуска: {vram_used()}")

    proc, local, boot = start_server(model, ctx=12288, gpu_layers=99)
    try:
        print(f"сервер поднялся за {boot:.1f} c · видеопамять: {vram_used()}\n")
        br = B.Brain(config.CFG)
        system = br._system_block()["parts"][0]["text"]
        tools = openai_tools(B.TOOLS)

        # Первый запрос отдельно: он платит за разбор всех описаний инструментов,
        # следующие берут это начало из кэша
        calls, text, cold = ask(local, system, tools, "который час")
        print(f"первый запрос (разбор 55 инструментов): {cold:.1f} c → {calls or text[:40]}\n")

        hits, times, wrong = 0, [], []
        for phrase, want in CASES:
            calls, text, took = ask(local, system, tools, phrase)
            times.append(took)
            names = {c[0] for c in calls}
            ok = bool(names & want)
            hits += ok
            args = calls[0][1][:60] if calls else ""
            print(f"{'ok ' if ok else 'мимо'} {took:4.1f} c «{phrase[:38]:38}» → "
                  f"{', '.join(names) or 'словами: ' + text[:30]} {args}")
            if not ok:
                wrong.append(phrase)

        print(f"\nверный инструмент: {hits}/{len(CASES)} · в среднем {sum(times)/len(times):.2f} c, "
              f"худшее {max(times):.2f} c")
        print("для сравнения Gemini flash-lite: 14/14, в среднем 0.85 c")
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    main()
