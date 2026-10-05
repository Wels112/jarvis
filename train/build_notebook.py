# -*- coding: utf-8 -*-
"""Собирает ноутбук Kaggle для дообучения своей модели Джарвиса.

Ноутбук самодостаточный: сам ставит библиотеки, сам берёт учебник из
репозитория на GitHub, учит, проверяет на отложенных примерах и упаковывает
модель в GGUF — формат, который понимает llama.cpp у хозяина. Результат лежит
во вкладке Output, его остаётся скачать в D:\\jarvis\\llm\\models.

Запуск:  .venv\\Scripts\\python.exe train\\build_notebook.py
"""
import json
from pathlib import Path

REPO_RAW = "https://raw.githubusercontent.com/Wels112/jarvis/main/train/data"
OUT = Path(__file__).resolve().parent / "jarvis_finetune.ipynb"

CELLS = [
    ("md", """# Джарвис: дообучение своей модели

Учим **Qwen3.5-2B** выбирать инструменты Джарвиса так же, как это делает Gemini.
Учебник собран Gemini-учителем: живые фразы под каждый из 55 инструментов,
ответы учителя с настоящими инструментами и примеры честного ответа на ошибку.

**Перед запуском** справа в настройках: Accelerator — **GPU T4 x2**,
Internet — **On**. Потом *Run All*. Займёт около двух часов.

Результат — файл `jarvis-qwen3.5-2b-Q4_K_M.gguf` во вкладке **Output**."""),

    ("code", """# Библиотеки. Unsloth учит в 2 раза быстрее и в 4-битном режиме
# укладывает 2B-модель с длинным контекстом в 16 ГБ T4
%pip install -q unsloth
%pip install -q --no-deps --upgrade "trl>=0.23" "peft>=0.17"
import torch, json, os, random, urllib.request
print(torch.__version__, torch.cuda.get_device_name(0))"""),

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

MAX_LEN = 6144          # описания 55 инструментов — около 5 тысяч токенов
model, tokenizer = FastLanguageModel.from_pretrained(
    "unsloth/Qwen3.5-2B", max_seq_length=MAX_LEN, load_in_4bit=True)
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

    ("code", """from datasets import Dataset
from trl import SFTTrainer, SFTConfig
from unsloth.chat_templates import train_on_responses_only

ds = Dataset.from_list([{"text": render(i)} for i in train])
trainer = SFTTrainer(
    model=model, tokenizer=tokenizer, train_dataset=ds,
    args=SFTConfig(
        dataset_text_field="text", max_seq_length=MAX_LEN,
        per_device_train_batch_size=1, gradient_accumulation_steps=8,
        num_train_epochs=2, learning_rate=2e-4, lr_scheduler_type="cosine",
        warmup_ratio=0.03, logging_steps=10, save_strategy="no",
        fp16=not torch.cuda.is_bf16_supported(), bf16=torch.cuda.is_bf16_supported(),
        optim="adamw_8bit", seed=13, output_dir="out", report_to="none"))
# Учим только ответам Джарвиса. Вопросы хозяина и результаты инструментов
# модель видит, но подражать им не должна
trainer = train_on_responses_only(trainer,
    instruction_part="<|im_start|>user\\n", response_part="<|im_start|>assistant\\n")
stats = trainer.train()
print(f"готово за {stats.metrics['train_runtime'] / 60:.0f} мин, потеря {stats.metrics['train_loss']:.3f}")"""),

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

    ("code", """# Упаковка в GGUF для llama.cpp у хозяина. Q4_K_M — как у исходной модели:
# 1,4 ГБ, целиком влезает в 3 ГБ видеопамяти GTX 1060
model.save_pretrained_gguf("jarvis-qwen3.5-2b", tokenizer, quantization_method="q4_k_m")
model.save_pretrained("jarvis-lora")           # сам адаптер — маленький, на будущее
import glob, shutil
for f in glob.glob("jarvis-qwen3.5-2b*/*.gguf") + glob.glob("*.gguf"):
    if "Q4_K_M" in f.upper() or "q4_k_m" in f:
        shutil.copy(f, "/kaggle/working/jarvis-qwen3.5-2b-Q4_K_M.gguf")
print(sorted(os.listdir("/kaggle/working")))"""),
]


def main():
    nb = {"cells": [], "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
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
