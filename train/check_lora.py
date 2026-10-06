# -*- coding: utf-8 -*-
"""Вторая половина обучения без обучения: упаковка надстройки и её загрузка.

В Colab надстройку LoRA упаковывает в GGUF скрипт llama.cpp, а у хозяина её
накладывает на модель llama-server. Если имена слоёв или размеры не сойдутся,
это выяснится только после часа обучения. Поэтому здесь собирается надстройка
той же формы, что сохранит Unsloth (те же слои и размеры, веса — шум), и
проходит весь путь: convert_lora_to_gguf.py той же сборки → llama-server
с --lora → короткий ответ.

Имена проверяются в двух видах: Unsloth может загрузить Qwen3.5 целиком
(model.language_model.layers…, как в файле модели) или только текстовую часть
(model.layers…). Пройти должны оба.

Запуск (окружение — см. check_template.py; torch берётся из окружения Джарвиса):
  llm\\nbtest\\venv\\Scripts\\python train\\check_lora.py
"""
import json
import os
import re
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LLM = ROOT / "llm"
WORK = LLM / "nbtest" / "lora"
LLAMA_SRC = LLM / "nbtest" / "llama.cpp"        # git clone --branch b11398
JARVIS_SITE = ROOT / ".venv" / "Lib" / "site-packages"   # отсюда только torch
os.environ.setdefault("HF_HOME", str(LLM / "nbtest" / "hf"))
sys.path.append(str(JARVIS_SITE))      # в конец: своё окружение важнее, оттуда берём только torch
BASE = "unsloth/Qwen3.5-2B"
MODEL = LLM / "models" / "Qwen3.5-2B-Q4_K_M.gguf"
TARGETS = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")
RANK = 16
PORT = 8091
NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def weight_shapes():
    """Имена и размеры весов модели — из заголовка safetensors, без скачивания."""
    import requests
    base = f"https://huggingface.co/{BASE}/resolve/main"
    # Имя файла весов — из индекса: у этой модели он не model.safetensors
    index = requests.get(f"{base}/model.safetensors.index.json", timeout=30)
    files = sorted(set(index.json()["weight_map"].values())) if index.ok else ["model.safetensors"]
    shapes = {}
    for f in files:
        url = f"{base}/{f}"
        # CDN может отдать кусок больше запрошенного — берём ровно нужные байты
        n = struct.unpack("<Q", requests.get(url, headers={"Range": "bytes=0-7"}, timeout=30).content[:8])[0]
        head = json.loads(requests.get(url, headers={"Range": f"bytes=8-{7 + n}"}, timeout=60).content[:n])
        shapes.update({k: v["shape"] for k, v in head.items() if k != "__metadata__"})
    return shapes


def make_adapter(shapes, out_dir: Path, text_only: bool):
    """Надстройка, как её сохраняет PEFT: base_model.model.<модуль>.lora_A/B.weight."""
    import torch
    from safetensors.torch import save_file
    pick = re.compile(r"^model\.language_model\.layers\.\d+\.(self_attn|mlp)\.(%s)\.weight$"
                      % "|".join(TARGETS))
    gen = torch.Generator().manual_seed(13)
    tensors = {}
    for name, (rows, cols) in ((k, v) for k, v in shapes.items() if pick.match(k)):
        module = name[:-len(".weight")]
        if text_only:
            module = module.replace("model.language_model.", "model.", 1)
        tensors[f"base_model.model.{module}.lora_A.weight"] = torch.randn(RANK, cols, generator=gen) * 0.01
        tensors[f"base_model.model.{module}.lora_B.weight"] = torch.randn(rows, RANK, generator=gen) * 0.001
    out_dir.mkdir(parents=True, exist_ok=True)
    save_file(tensors, str(out_dir / "adapter_model.safetensors"))
    (out_dir / "adapter_config.json").write_text(json.dumps({
        "peft_type": "LORA", "task_type": "CAUSAL_LM", "base_model_name_or_path": BASE,
        "r": RANK, "lora_alpha": RANK, "lora_dropout": 0.0, "bias": "none",
        "target_modules": list(TARGETS), "fan_in_fan_out": False, "inference_mode": True,
        "use_rslora": False, "use_dora": False, "modules_to_save": None}, indent=1), encoding="utf-8")
    return len(tensors) // 2


def convert(adapter_dir: Path, out: Path) -> tuple[bool, str]:
    """convert_lora_to_gguf.py той же сборки, что у хозяина; torch — из окружения Джарвиса."""
    runner = (f"import sys, runpy; sys.path.append({str(JARVIS_SITE)!r}); "
              f"sys.argv = ['convert_lora_to_gguf.py', {str(adapter_dir)!r}, '--base-model-id', {BASE!r}, "
              f"'--outtype', 'f16', '--outfile', {str(out)!r}]; "
              f"runpy.run_path({str(LLAMA_SRC / 'convert_lora_to_gguf.py')!r}, run_name='__main__')")
    p = subprocess.run([sys.executable, "-c", runner], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(LLAMA_SRC))
    tail = "\n".join((p.stdout + p.stderr).strip().splitlines()[-6:])
    return p.returncode == 0 and out.exists(), tail


def serve_with(lora: Path) -> tuple[bool, str]:
    """llama-server с моделью хозяина и надстройкой: загрузится ли и ответит ли."""
    log = WORK / f"{lora.stem}.server.log"
    with open(log, "w", encoding="utf-8") as f:
        proc = subprocess.Popen(
            [str(LLM / "bin" / "llama-server.exe"), "-m", str(MODEL), "--lora", str(lora),
             "-c", "2048", "-ngl", "0", "--jinja", "-np", "1",
             "--host", "127.0.0.1", "--port", str(PORT)],
            stdout=f, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        for _ in range(240):
            if proc.poll() is not None:
                break
            try:
                if NO_PROXY.open(f"http://127.0.0.1:{PORT}/health", timeout=2).status == 200:
                    break
            except Exception:
                time.sleep(0.5)
        if proc.poll() is not None:
            return False, "сервер упал: " + log.read_text(encoding="utf-8", errors="replace")[-600:]
        req = urllib.request.Request(
            f"http://127.0.0.1:{PORT}/v1/chat/completions",
            data=json.dumps({"messages": [{"role": "user", "content": "Скажи «привет»."}],
                             "max_tokens": 12, "chat_template_kwargs": {"enable_thinking": False}}).encode(),
            headers={"Content-Type": "application/json"})
        answer = json.loads(NO_PROXY.open(req, timeout=120).read())["choices"][0]["message"]["content"]
        # Наложена ли надстройка на самом деле, а не пропущена молча
        adapters = json.loads(NO_PROXY.open(f"http://127.0.0.1:{PORT}/lora-adapters", timeout=10).read())
        mine = [a for a in adapters if Path(a.get("path", "")).name == lora.name]
        ok = bool(mine) and mine[0].get("scale") == 1
        return ok, f"ответ «{answer.strip()[:40]}»; надстройка на сервере: {mine or adapters}"
    finally:
        proc.terminate()
        proc.wait(10)


def main():
    shapes = weight_shapes()
    errors = 0
    for text_only in (False, True):
        kind = "только текст (model.layers…)" if text_only else "целиком (model.language_model…)"
        d = WORK / ("text" if text_only else "full")
        n = make_adapter(shapes, d, text_only)
        out = d / "jarvis-lora.gguf"
        ok, tail = convert(d, out)
        if not ok:
            errors += 1
            print(f"НЕТ {kind}: упаковка упала\n{tail}")
            continue
        print(f"ok  {kind}: {n} слоёв с надстройкой → {out.stat().st_size / 1e6:.0f} МБ GGUF")
        ok, info = serve_with(out)
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'}   llama-server с надстройкой: {info}")
    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
