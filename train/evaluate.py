# -*- coding: utf-8 -*-
"""Исходная модель против дообученной — на фразах, которых ученица не видела.

Две проверки сразу:
  • 14 фраз с живого показа (в учебник не попали намеренно);
  • отложенная десятая часть сгенерированного учебника (train/data/test.jsonl).

Считается не только попадание в инструмент, но и враньё: ответ словами
«закрываю», «готово», «погода такая-то» без вызова инструмента. Именно это
сильнее всего мешало на замере, и дообучение должно это лечить.

Запуск:  .venv\\Scripts\\python.exe train\\evaluate.py Qwen3.5-2B-Q4_K_M.gguf jarvis-qwen3.5-2b-Q4_K_M.gguf
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

DATA = Path(__file__).resolve().parent / "data"


def cases():
    from tests.probe_tool_choice import CASES
    out = [(p, w, "показ") for p, w in CASES]
    path = DATA / "test.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            ans = item["messages"][1]
            want = {c["function"]["name"] for c in ans.get("tool_calls") or []}
            out.append((item["messages"][0]["content"], want or {None}, item["intent"]))
    return out


def run(spec: str, items):
    """spec — «модель.gguf» или «модель.gguf+надстройка.gguf»."""
    from core.local_brain import CLAIMS, _openai_tools
    from tests.probe_local_brain import start_server
    from core.brain import TOOLS

    models = config.ROOT / "llm" / "models"
    model_name, _, lora_name = spec.partition("+")
    proc, local, boot = start_server(models / model_name, ctx=12288, gpu_layers=99,
                                     lora=(models / lora_name) if lora_name else None)
    system = (DATA / "system.txt").read_text(encoding="utf-8")
    tools = _openai_tools(TOOLS)
    hits = lies = 0
    times, by_kind = [], {}
    try:
        for phrase, want, kind in items:
            payload = {"messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": phrase}],
                       "tools": tools, "tool_choice": "auto", "temperature": 0,
                       "max_tokens": 200, "chat_template_kwargs": {"enable_thinking": False}}
            t0 = time.monotonic()
            msg = local.post("http://127.0.0.1:8090/v1/chat/completions", json=payload,
                             timeout=180).json()["choices"][0]["message"]
            times.append(time.monotonic() - t0)
            got = {c["function"]["name"] for c in msg.get("tool_calls") or []}
            text = msg.get("content") or ""
            ok = bool(got & want) if want != {None} else not got
            # Враньё: просили действие, а модель ответила словами о сделанном
            lied = want != {None} and not got and bool(CLAIMS.search(text))
            hits += ok
            lies += lied
            k = by_kind.setdefault("показ" if kind == "показ" else "отложенные", [0, 0])
            k[0] += ok
            k[1] += 1
    finally:
        proc.terminate()
        proc.wait(15)
    times = sorted(times[1:]) or [0]             # первый запрос платит за разбор инструментов
    return {"hits": hits, "total": len(items), "lies": lies, "by_kind": by_kind,
            "median": times[len(times) // 2], "boot": boot}


def main():
    config.setup_console()
    models = sys.argv[1:] or ["Qwen3.5-2B-Q4_K_M.gguf"]
    items = cases()
    print(f"проверочных фраз: {len(items)} (с показа {sum(1 for i in items if i[2] == 'показ')})\n")
    for m in models:
        missing = [p for p in m.split("+") if not (config.ROOT / "llm" / "models" / p).exists()]
        if missing:
            print(f"{m}: нет файла {missing[0]} — пропуск")
            continue
        r = run(m, items)
        parts = " · ".join(f"{k} {v[0]}/{v[1]}" for k, v in r["by_kind"].items())
        print(f"{m}\n   верно {r['hits']}/{r['total']} ({100 * r['hits'] / r['total']:.0f}%) · {parts}"
              f"\n   враньё без действия: {r['lies']} · медиана ответа {r['median']:.2f} c\n")


if __name__ == "__main__":
    main()
