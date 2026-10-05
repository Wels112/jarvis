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

Запуск:  .venv\\Scripts\\python.exe train\\build_notebook.py
"""
import json
from pathlib import Path

REPO_RAW = "https://raw.githubusercontent.com/Wels112/jarvis/main/train/data"
LLAMA_TAG = "b11398"        # та же сборка llama.cpp, что у хозяина: формат надстройки совпадёт
OUT = Path(__file__).resolve().parent / "jarvis_finetune.ipynb"

CELLS = [
    ("md", """# Джарвис: дообучение своей модели

Учим **Qwen3.5-2B** выбирать инструменты Джарвиса так же, как это делает Gemini.
Учебник собран Gemini-учителем: живые фразы под каждый из 55 инструментов,
ответы учителя с настоящими инструментами и примеры честного ответа на ошибку.

**Colab:** меню *Среда выполнения → Сменить среду выполнения → T4 GPU*, потом
*Среда выполнения → Выполнить все*. Не закрывай вкладку: около часа.
В конце браузер сам скачает `jarvis-lora.gguf` — это и есть результат.

**Kaggle:** справа *Accelerator — GPU T4 x2*, *Internet — On*, потом *Run All*.
Результат — во вкладке *Output*."""),

    ("code", """# Видеокарта и библиотеки. Unsloth учит вдвое быстрее и в 4-битном режиме
# укладывает 2B-модель с длинным контекстом в 16 ГБ T4
import torch, json, os, random, subprocess, urllib.request
assert torch.cuda.is_available(), (
    "Видеокарты нет. Colab: Среда выполнения → Сменить среду выполнения → T4 GPU. "
    "Kaggle: Accelerator → GPU T4 x2 (нужен подтверждённый телефон).")
print("видеокарта:", torch.cuda.get_device_name(0))
IN_COLAB = "google.colab" in str(get_ipython())
WORK = "/kaggle/working" if os.path.isdir("/kaggle/working") else "/content/jarvis_out"
os.makedirs(WORK, exist_ok=True)
%pip install -q unsloth"""),

    ("code", f"""# Учебник из репозитория: системный текст и инструменты — ровно те,
# что Джарвис подаёт своей модели у хозяина, иначе выучит не то
RAW = "{REPO_RAW}"
def get(name):
    return urllib.request.urlopen(f"{{RAW}}/{{name}}").read().decode("utf-8")

SYSTEM = get("system.txt")
TOOLS = [{{"type": "function", "function": t}} for t in json.loads(get("tools.json"))]
train = [json.loads(l) for l in get("train.jsonl").splitlines() if l.strip()]
test = [json.loads(l) for l in get("test.jsonl").splitlines() if l.strip()]
print(f"учебных {{len(train)}}, проверочных {{len(test)}}, инструментов {{len(TOOLS)}}")"""),

    ("code", """from unsloth import FastLanguageModel

BASE = "unsloth/Qwen3.5-2B"
MAX_LEN = 6144          # описания 55 инструментов — около 5 тысяч токенов
model, tokenizer = FastLanguageModel.from_pretrained(
    BASE, max_seq_length=MAX_LEN, load_in_4bit=True)
model = FastLanguageModel.get_peft_model(
    model, r=16, lora_alpha=16, lora_dropout=0,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
    use_gradient_checkpointing="unsloth", random_state=13)"""),

    ("code", """# Пример в виде текста — так, как его увидит модель. Рассуждения вслух
# выключены: у хозяина они тоже выключены
def render(item):
    msgs = [{"role": "system", "content": SYSTEM}] + item["messages"]
    return tokenizer.apply_chat_template(msgs, tools=TOOLS, tokenize=False,
                                         enable_thinking=False)

sample = render(train[0])
print(sample[-700:])
n_tok = len(tokenizer(sample)["input_ids"])
print("\\nтокенов в примере:", n_tok)
assert n_tok < MAX_LEN, 'пример длиннее контекста — подними MAX_LEN'
assert '<|im_start|>assistant' in sample, 'шаблон чата не тот, что ожидался'
"""),

    ("code", """import inspect
from datasets import Dataset
from trl import SFTTrainer, SFTConfig
from unsloth.chat_templates import train_on_responses_only

# Один проход по учебнику: около часа на T4. Бесплатный Colab длинные сессии
# обрывает, а 1500 примеров на один проход для надстройки LoRA достаточно
EPOCHS = 1
ds = Dataset.from_list([{"text": render(i)} for i in train])
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
    ids = tokenizer(prompt, return_tensors="pt").to("cuda")
    out = model.generate(**ids, max_new_tokens=120, do_sample=False)
    got = tool_of(tokenizer.decode(out[0][ids["input_ids"].shape[1]:]))
    ok = (got == want) if want else got is None
    hits += ok; total += 1
print(f"верных на отложенных: {hits}/{total}")"""),

    ("code", f"""# Упаковка надстройки в GGUF той же сборкой llama.cpp, что у хозяина
# ({LLAMA_TAG}): тогда формат файла гарантированно совпадёт
subprocess.run(["git", "clone", "-q", "--depth", "1", "--branch", "{LLAMA_TAG}",
                "https://github.com/ggml-org/llama.cpp", "/tmp/llama.cpp"], check=True)
# Только библиотека gguf из той же сборки и пара мелочей. Общий список
# зависимостей конвертера не ставим: он тянет torch для процессора и
# заменил бы им torch с видеокартой
%pip install -q /tmp/llama.cpp/gguf-py sentencepiece protobuf
OUT_GGUF = f"{{WORK}}/jarvis-lora.gguf"
subprocess.run(["python", "/tmp/llama.cpp/convert_lora_to_gguf.py", LORA_DIR,
                "--base-model-id", BASE, "--outtype", "f16", "--outfile", OUT_GGUF], check=True)
print(f"надстройка: {{os.path.getsize(OUT_GGUF) / 1e6:.0f}} МБ")"""),

    ("code", """# Забрать результат. В Colab браузер скачает файл сам — в папку «Загрузки»
if IN_COLAB:
    from google.colab import files
    files.download(OUT_GGUF)
else:
    print("Kaggle: файл во вкладке Output —", OUT_GGUF)"""),
]


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
    # Каждую ячейку кода проверяем на синтаксис, убрав команды %pip
    import ast
    for kind, src in CELLS:
        if kind == "code":
            ast.parse("\n".join(l for l in src.splitlines() if not l.startswith("%")))
    print(f"ноутбук собран: {OUT.name}, ячеек {len(CELLS)}, синтаксис чист")


if __name__ == "__main__":
    main()
