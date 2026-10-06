# -*- coding: utf-8 -*-
"""Собирает ноутбук для дообучения своей модели Джарвиса — для Colab и Kaggle.

Ноутбук самодостаточный: ставит библиотеки, берёт учебник из репозитория на
GitHub, учит, проверяет на отложенных примерах и упаковывает дообучение в
маленький файл GGUF (надстройка LoRA, десятки мегабайт), который llama.cpp у
хозяина накладывает на уже скачанную модель при запуске.

Почему надстройка, а не целая модель: из бесплатного Colab полуторагигабайтный
файл выкачивается медленно и рвётся, а надстройка — за минуту. Целую модель
скачивать заново и не нужно: она уже лежит в D:\\jarvis\\llm\\models.

Почему Colab: Kaggle без подтверждённого телефона не даёт ноутбуку ни
видеокарту, ни интернет (проверено 05.10.2026 — прогон ушёл на процессор).
Colab хватает Google-аккаунта.

Установка и загрузка — по официальным ноутбукам Unsloth для Qwen3.5
(unslothai/notebooks: nb/Qwen3_5_(2B)_Vision.ipynb — бесплатная T4,
nb/Qwen3_5_MoE.ipynb — обучение на тексте). Первая версия ставила голый
`pip install unsloth` поверх уже загруженного torch и звала «процессор»
Qwen3.5 как токенизатор — на Colab это падало бы в первых ячейках.

Запуск:  .venv\\Scripts\\python.exe train\\build_notebook.py
"""
import json
from pathlib import Path

REPO_RAW = "https://raw.githubusercontent.com/Wels112/jarvis/main/train/data"
LLAMA_TAG = "b11398"        # та же сборка llama.cpp, что у хозяина: формат надстройки совпадёт
DATA = Path(__file__).resolve().parent / "data"
OUT = Path(__file__).resolve().parent / "jarvis_finetune.ipynb"
N_TOOLS = len(json.loads((DATA / "tools.json").read_text(encoding="utf-8")))

CELLS = [
    ("md", f"""# Джарвис: дообучение своей модели

Учим **Qwen3.5-2B** выбирать инструменты Джарвиса так же, как это делает Gemini.
Учебник собран Gemini-учителем: живые фразы под каждый из {N_TOOLS} инструментов,
ответы учителя с настоящими инструментами и примеры честного ответа на ошибку.

**Colab:** меню *Среда выполнения → Сменить среду выполнения → T4 GPU*, потом
*Среда выполнения → Выполнить все*. Не закрывай вкладку: час-полтора.
В конце браузер сам скачает `jarvis-lora.gguf` — это и есть результат.

**Kaggle:** справа *Accelerator — GPU T4 x2*, *Internet — On*, потом *Run All*.
Результат — во вкладке *Output*."""),

    ("code", """# Есть ли видеокарта. Спрашиваем nvidia-smi, а не torch: установка ниже
# меняет версию torch, а уже загруженный в память остался бы старым
import os, shutil, subprocess
smi = shutil.which("nvidia-smi")
gpu = subprocess.run([smi, "--query-gpu=name,memory.total", "--format=csv,noheader"],
                     capture_output=True, text=True).stdout.strip() if smi else ""
assert gpu, ("Видеокарты нет. Colab: Среда выполнения → Сменить среду выполнения → T4 GPU. "
             "Kaggle: Accelerator → GPU T4 x2 (нужен подтверждённый телефон).")
print("видеокарта:", gpu)
IN_COLAB = "COLAB_" in "".join(os.environ.keys())
WORK = "/kaggle/working" if os.path.isdir("/kaggle/working") else "/content/jarvis_out"
os.makedirs(WORK, exist_ok=True)"""),

    ("code", """# Библиотеки — рецепт из официального ноутбука Unsloth для Qwen3.5-2B на
# бесплатной T4: версии torch, transformers и trl там подобраны под эту модель.
# Голый «pip install unsloth» тянет другие, и Qwen3.5 не загружается. Минуты три
import os, importlib.util
!pip install --upgrade -qqq uv
if importlib.util.find_spec("torch") is None or "COLAB_" in "".join(os.environ.keys()):
    try: import numpy, PIL; _numpy = f"numpy=={numpy.__version__}"; _pil = f"pillow=={PIL.__version__}"
    except: _numpy = "numpy"; _pil = "pillow"
    !uv pip install -qqq \\
        "torch==2.8.0" "triton>=3.3.0" {_numpy} {_pil} torchvision bitsandbytes xformers==0.0.32.post2 \\
        "unsloth_zoo[base] @ git+https://github.com/unslothai/unsloth-zoo" \\
        "unsloth[base] @ git+https://github.com/unslothai/unsloth"
    !uv pip install -qqq --no-deps "torchcodec==0.7.0"
elif importlib.util.find_spec("unsloth") is None:
    !uv pip install -qqq unsloth
!uv pip install --upgrade --no-deps "tokenizers>=0.22.0,<=0.23.0" trl==0.22.2 unsloth unsloth_zoo
!uv pip install -qqq transformers==5.2.0
# Ядра линейного внимания Qwen3.5 Unsloth везёт свои; отдельный fla их бы заслонил
!uv pip uninstall -qqq flash-linear-attention fla-core
# Готовый causal_conv1d под этот torch, если есть; иначе — запасной путь transformers
import sys, torch; _t = ".".join(torch.__version__.split(".")[:2]); _cu = (torch.version.cuda or "0").split(".")[0]; _py = f"cp{sys.version_info[0]}{sys.version_info[1]}"; _abi = str(torch.compiled_with_cxx11_abi()).upper()
!uv pip install -qqq "https://github.com/Dao-AILab/causal-conv1d/releases/download/v1.7.0/causal_conv1d-1.7.0+cu{_cu}torch{_t}cxx11abi{_abi}-{_py}-{_py}-linux_x86_64.whl" || echo "causal_conv1d без готовой сборки — обойдёмся"
!uv pip install -qqq --no-deps --upgrade "torchao>=0.16.0"
print("torch", torch.__version__, "· CUDA", torch.cuda.is_available())"""),

    ("code", f"""# Учебник из репозитория: системный текст и инструменты — ровно те,
# что Джарвис подаёт своей модели у хозяина, иначе выучит не то
import json, random, urllib.request
RAW = "{REPO_RAW}"
def get(name):
    return urllib.request.urlopen(f"{{RAW}}/{{name}}").read().decode("utf-8")

SYSTEM = get("system.txt")
TOOLS = [{{"type": "function", "function": t}} for t in json.loads(get("tools.json"))]
train = [json.loads(l) for l in get("train.jsonl").splitlines() if l.strip()]
test = [json.loads(l) for l in get("test.jsonl").splitlines() if l.strip()]
print(f"учебных {{len(train)}}, проверочных {{len(test)}}, инструментов {{len(TOOLS)}}")"""),

    ("code", """from unsloth import FastLanguageModel
import torch

BASE = "unsloth/Qwen3.5-2B"
MAX_LEN = 8192          # пример — 5,5–5,6 тысячи токенов (почти всё — описания инструментов)
# В 16 битах, как в официальном рецепте для T4: 2B-модель занимает около 5 ГБ из 15
model, processor = FastLanguageModel.from_pretrained(
    BASE, max_seq_length=MAX_LEN, load_in_4bit=False)
# Qwen3.5 понимает и картинки, поэтому загрузчик отдаёт «процессор». Текст режет
# его токенизатор; сам процессор принял бы строку за картинку
tokenizer = getattr(processor, "tokenizer", processor)
# Учим только языковую часть: внимание шести слоёв полного внимания и MLP всех
# 24 слоёв. У зрения (visual: qkv, proj, linear_fc) и линейного внимания
# (linear_attn: in_proj_*, out_proj) имена другие, их надстройка не трогает —
# веса линейного внимания упаковщик llama.cpp вдобавок переставляет по-особому
model = FastLanguageModel.get_peft_model(
    model, r=16, lora_alpha=16, lora_dropout=0,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
    use_gradient_checkpointing="unsloth", random_state=13)
lora = [n for n, _ in model.named_parameters() if "lora_A" in n]
stray = [n for n in lora if "visual" in n or "mtp" in n or "linear_attn" in n]
print(f"матриц надстройки: {len(lora)}")
assert lora and not stray, f"надстройка задела не те слои: {stray[:3]}\""""),

    ("code", """# Пример в виде текста — так, как его увидит модель. Рассуждения вслух
# выключены: у хозяина они тоже выключены
def render(item):
    msgs = [{"role": "system", "content": SYSTEM}] + item["messages"]
    return tokenizer.apply_chat_template(msgs, tools=TOOLS, tokenize=False,
                                         enable_thinking=False)

sample = render(train[0])
print(sample[-700:])
assert '<|im_start|>assistant' in sample, 'шаблон чата не тот, что ожидался'
# Длина каждого примера: слишком длинный обрезался бы с конца — вместе с ответом,
# которому и учим. Такие выбрасываем, а не учим на обрубке
texts = [render(i) for i in train]
lens = [len(tokenizer(t, add_special_tokens=False)["input_ids"]) for t in texts]
keep = [t for t, n in zip(texts, lens) if n <= MAX_LEN]
print(f"\\nтокенов в примере: от {min(lens)} до {max(lens)}, в среднем {sum(lens) // len(lens)}; "
      f"длиннее {MAX_LEN}: {len(texts) - len(keep)}")
assert len(keep) > 0.95 * len(texts), 'много примеров длиннее контекста — подними MAX_LEN'"""),

    ("code", """import inspect
from datasets import Dataset
from trl import SFTTrainer, SFTConfig
from unsloth.chat_templates import train_on_responses_only

# Один проход по учебнику: час-полтора на T4. Бесплатный Colab длинные сессии
# обрывает, а полутора тысяч примеров на один проход для надстройки LoRA хватает
EPOCHS = 1
ds = Dataset.from_list([{"text": t} for t in keep])
# Имена параметров у trl менялись от версии к версии (max_seq_length → max_length,
# tokenizer → processing_class). Берём то, что есть в установленной версии
cfg = dict(dataset_text_field="text",
           per_device_train_batch_size=1, gradient_accumulation_steps=8,
           num_train_epochs=EPOCHS, learning_rate=2e-4, lr_scheduler_type="cosine",
           warmup_ratio=0.03, logging_steps=10, save_strategy="no",
           fp16=not torch.cuda.is_bf16_supported(), bf16=torch.cuda.is_bf16_supported(),
           optim="adamw_8bit", seed=13, output_dir="out", report_to="none")
cfg["max_length" if "max_length" in inspect.signature(SFTConfig).parameters
    else "max_seq_length"] = MAX_LEN
tok_arg = ("processing_class" if "processing_class" in inspect.signature(SFTTrainer.__init__).parameters
           else "tokenizer")
trainer = SFTTrainer(model=model, train_dataset=ds, args=SFTConfig(**cfg), **{tok_arg: tokenizer})
# Учим только ответам Джарвиса. Вопросы хозяина и результаты инструментов
# модель видит, но подражать им не должна
trainer = train_on_responses_only(trainer,
    instruction_part="<|im_start|>user\\n", response_part="<|im_start|>assistant\\n")
stats = trainer.train()
print(f"готово за {stats.metrics['train_runtime'] / 60:.0f} мин, потеря {stats.metrics['train_loss']:.3f}")"""),

    ("code", """# Сохраняем надстройку сразу — до проверки и упаковки: если дальше что-то
# упадёт, час обучения не пропадёт
LORA_DIR = f"{WORK}/jarvis-lora"
model.save_pretrained(LORA_DIR)
tokenizer.save_pretrained(LORA_DIR)
print(sorted(os.listdir(LORA_DIR)))"""),

    ("code", """# Проверка на отложенных фразах: на них модель не училась
import re
FastLanguageModel.for_inference(model)

def tool_of(text):
    m = re.search(r'"name":\\s*"([a-z_]+)"', text) or re.search(r"<function=([a-z_]+)", text)
    return m.group(1) if m else None

hits = total = 0
for item in random.Random(1).sample(test, min(60, len(test))):
    want = item["messages"][1].get("tool_calls")
    want = want[0]["function"]["name"] if want else None
    prompt = tokenizer.apply_chat_template(
        [{"role": "system", "content": SYSTEM}, item["messages"][0]], tools=TOOLS,
        tokenize=False, add_generation_prompt=True, enable_thinking=False)
    ids = tokenizer(prompt, return_tensors="pt", add_special_tokens=False).to("cuda")
    out = model.generate(**ids, max_new_tokens=120, do_sample=False)
    got = tool_of(tokenizer.decode(out[0][ids["input_ids"].shape[1]:]))
    ok = (got == want) if want else got is None
    hits += ok; total += 1
print(f"верных на отложенных: {hits}/{total}")"""),

    ("code", f"""# Упаковка надстройки в GGUF той же сборкой llama.cpp, что у хозяина
# ({LLAMA_TAG}): тогда формат файла гарантированно совпадёт. Если упаковка
# не выйдет, отдаём саму надстройку архивом — упакуем у хозяина на компьютере
import sys
OUT_GGUF = f"{{WORK}}/jarvis-lora.gguf"
try:
    subprocess.run(["git", "clone", "-q", "--depth", "1", "--branch", "{LLAMA_TAG}",
                    "https://github.com/ggml-org/llama.cpp", "/tmp/llama.cpp"], check=True)
    # Только библиотека gguf из той же сборки и пара мелочей. Общий список
    # зависимостей конвертера не ставим: он тянет torch для процессора и
    # заменил бы им torch с видеокартой
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "/tmp/llama.cpp/gguf-py",
                    "sentencepiece", "protobuf"], check=True)
    subprocess.run([sys.executable, "/tmp/llama.cpp/convert_lora_to_gguf.py", LORA_DIR,
                    "--base-model-id", BASE, "--outtype", "f16", "--outfile", OUT_GGUF], check=True)
    RESULT = OUT_GGUF
    print(f"надстройка: {{os.path.getsize(OUT_GGUF) / 1e6:.0f}} МБ")
except Exception as e:
    RESULT = shutil.make_archive(f"{{WORK}}/jarvis-lora", "zip", LORA_DIR)
    print(f"упаковать в GGUF не вышло ({{e}}) — забираем надстройку архивом: {{RESULT}}")"""),

    ("code", """# Забрать результат. В Colab браузер скачает файл сам — в папку «Загрузки»
if IN_COLAB:
    from google.colab import files
    files.download(RESULT)
else:
    print("Kaggle: файл во вкладке Output —", RESULT)"""),
]


def _python_only(src):
    """Код ячейки без команд Jupyter (%pip, !uv …) — для проверки синтаксиса.

    Команда превращается в pass с тем же отступом (внутри if она — тело блока),
    продолжения строк через обратный слэш выбрасываются вместе с ней.
    """
    out, cont = [], False
    for line in src.splitlines():
        if cont:
            cont = line.rstrip().endswith("\\")
            continue
        body = line.lstrip()
        if body.startswith(("%", "!")):
            out.append(line[:len(line) - len(body)] + "pass")
            cont = line.rstrip().endswith("\\")
        else:
            out.append(line)
    return "\n".join(out)


def main():
    nb = {"cells": [], "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
        "accelerator": "GPU",
        "colab": {"provenance": [], "gpuType": "T4"},
        "kaggle": {"accelerator": "nvidiaTeslaT4", "isInternetEnabled": True,
                   "isGpuEnabled": True}},
        "nbformat": 4, "nbformat_minor": 5}
    for i, (kind, src) in enumerate(CELLS):
        cell = {"cell_type": "markdown" if kind == "md" else "code", "id": f"c{i}",
                "metadata": {}, "source": src}
        if kind == "code":
            cell.update(execution_count=None, outputs=[])
        nb["cells"].append(cell)
    OUT.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    import ast
    for kind, src in CELLS:
        if kind == "code":
            ast.parse(_python_only(src))
    print(f"ноутбук собран: {OUT.name}, ячеек {len(CELLS)}, синтаксис чист")


if __name__ == "__main__":
    main()
