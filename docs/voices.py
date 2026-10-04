# -*- coding: utf-8 -*-
"""Прослушать все голоса и выбрать нравящийся.

Проговаривает одну и ту же фразу каждым голосом подряд, затем записывает выбор
в настройки. Выбирать голос по названию вслепую бессмысленно — надо слышать.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config

SPEAKERS = [
    ("aidar", "мужской, ровный — стоит сейчас"),
    ("eugene", "мужской, мягче"),
    ("baya", "женский, спокойный"),
    ("kseniya", "женский, тёплый"),
    ("xenia", "женский, звонкий"),
]

PHRASE = ("Здравствуйте. Джарвис на связи. "
          "На сегодня две задачи, а на улице плюс восемнадцать.")


def main():
    config.setup_console()
    import torch
    import sounddevice as sd

    torch.hub.set_dir(str(config.MODELS / "torch" / "hub"))
    torch.set_num_threads(4)
    print("поднимаю голосовую модель...\n")
    model, _ = torch.hub.load(repo_or_dir="snakers4/silero-models", model="silero_tts",
                              language="ru", speaker="v4_ru", trust_repo=True)
    model.to("cpu")

    for i, (name, desc) in enumerate(SPEAKERS, 1):
        print(f"{i}. {name} — {desc}")
        try:
            audio = model.apply_tts(text=PHRASE, speaker=name, sample_rate=48000)
            sd.play(audio.numpy(), 48000)
            sd.wait()
        except Exception as e:
            print(f"   не вышло: {e}")
        time.sleep(0.4)

    print()
    choice = input("Какой оставить? Введи номер (Enter — не менять): ").strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(SPEAKERS):
        print("Оставил как было.")
        return

    name = SPEAKERS[int(choice) - 1][0]
    cfg = config.load()
    cfg.setdefault("voice", {})["silero_speaker"] = name
    cfg["voice"]["engine"] = "silero"
    config.save(cfg)
    print(f"\nГотово — теперь говорит голосом {name}.")


if __name__ == "__main__":
    main()
