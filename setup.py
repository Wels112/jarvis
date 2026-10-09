# -*- coding: utf-8 -*-
"""Настройка ключей и проверка готовности.

Запуск:  setup.bat
Ключи вводишь ты сам — они пишутся в config/.env и никуда не уходят.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import config

ENV = config.ROOT / "config" / ".env"

KEYS = [
    ("GEMINI_API_KEY", "Мозг (Gemini)", "https://aistudio.google.com/apikey",
     "Бесплатно, 1500 запросов в день. Без него работают только простые команды."),
    ("YOUTUBE_CHANNEL", "Твой канал на YouTube", "например @tvoy_kanal",
     "Чтобы «сколько у меня подписчиков» знал, о ком речь."),
    ("TELEGRAM_API_ID", "Telegram API ID", "https://my.telegram.org → API development tools",
     "Нужен для чтения и отправки сообщений."),
    ("TELEGRAM_API_HASH", "Telegram API Hash", "там же", ""),
]


def read_env() -> dict:
    data = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                data[k.strip()] = v.strip()
    return data


def write_env(data: dict):
    lines = [
        "# Ключи Джарвиса. Файл локальный, наружу не уходит.",
        "",
        "# --- Мозг: https://aistudio.google.com/apikey ---",
        f"GEMINI_API_KEY={data.get('GEMINI_API_KEY','')}",
        "",
        "# --- YouTube ---",
        f"YOUTUBE_API_KEY={data.get('YOUTUBE_API_KEY','')}",
        f"YOUTUBE_CHANNEL={data.get('YOUTUBE_CHANNEL','')}",
        "",
        "# --- Telegram: https://my.telegram.org ---",
        f"TELEGRAM_API_ID={data.get('TELEGRAM_API_ID','')}",
        f"TELEGRAM_API_HASH={data.get('TELEGRAM_API_HASH','')}",
        "",
    ]
    ENV.write_text("\n".join(lines), encoding="utf-8")


def main():
    config.setup_console()
    print("=" * 62)
    print("  НАСТРОЙКА ДЖАРВИСА".center(62))
    print("=" * 62)
    data = read_env()

    for key, title, where, why in KEYS:
        cur = data.get(key, "")
        shown = (cur[:8] + "…") if len(cur) > 8 else (cur or "пусто")
        print(f"\n{title}")
        if why:
            print(f"  {why}")
        print(f"  где взять: {where}")
        print(f"  сейчас: {shown}")
        val = input("  вставь значение (Enter — оставить как есть): ").strip()
        if val:
            data[key] = val

    write_env(data)
    print("\nСохранено в config/.env")

    print("\n" + "=" * 62)
    print("  ПРОВЕРКА".center(62))
    print("=" * 62)
    check()


def check():
    """Диагностика: что работает, что нет."""
    config.CFG = config.load()
    ok, bad = [], []

    try:
        import sounddevice as sd
        ins = [d for d in sd.query_devices() if d["max_input_channels"] > 0]
        (ok if ins else bad).append(f"микрофон — устройств: {len(ins)}")
    except Exception as e:
        bad.append(f"микрофон — {e}")

    try:
        vc = config.CFG.get("voice", {})
        engine = vc.get("engine", "edge")
        if engine == "edge":
            # Проверяем делом, а не импортом: голос есть, только если Microsoft ответил
            from core.voice import EdgeSynth
            pcm, rate = EdgeSynth(config.CFG).synth("Проверка.")
            names = {"DmitryNeural": "Дмитрий", "SvetlanaNeural": "Светлана", "DariyaNeural": "Дарья"}
            raw = vc.get("edge_voice", "ru-RU-DmitryNeural").replace("ru-RU-", "")
            voice = names.get(raw, raw)
            (ok if len(pcm) > rate // 4 else bad).append(f"голос — Microsoft {voice}, отвечает")
        elif engine == "gemini":
            from core.voice import GeminiSynth
            GeminiSynth(config.CFG).synth("Проверка.")
            ok.append(f"голос — Google {vc.get('gemini_voice', 'Charon')}, отвечает")
        else:
            from core.voice import Voice
            ok.append(f"голос — {Voice(config.CFG).kind}")
    except Exception as e:
        bad.append(f"голос — не отвечает ({str(e)[:60]}); без интернета заговорит локальный")

    model_dir = list(config.MODELS.rglob("model.bin"))
    (ok if model_dir else bad).append(
        f"распознавание речи — модель {'на месте' if model_dir else 'НЕ скачана'}")

    from skills import system as S
    n = len(S.build_app_index())
    ok.append(f"программы — проиндексировано {n}")

    if config.env("GEMINI_API_KEY"):
        try:
            from core.brain import Brain
            b = Brain(config.CFG)
            r = b.ask("Ответь одним словом: работает?")
            # Без VPN облако отвечает отказом, а не исключением — смотрим last_error
            (ok if b.last_error is None else bad).append(f"мозг Gemini — {r[:90]}")
        except Exception as e:
            bad.append(f"мозг Gemini — {e}")
    else:
        bad.append("мозг Gemini — нет ключа (умный режим выключен)")

    # Необязательное — отдельно: «не авторизован» и «нет ключа» среди поломок
    # пугали при проверке установки 09.10.2026, хотя без них всё работает
    optional = []
    if config.env("YOUTUBE_API_KEY"):
        from skills import youtube as YT
        r = YT.search_videos("test", 1)
        (ok if "не ответил" not in r else bad).append("YouTube — ключ рабочий")
    else:
        optional.append("ключ YouTube — без него видео включаются так же; нужен только для статистики канала")

    token = config.env("TELEGRAM_BOT_TOKEN")
    if token:
        try:
            import requests
            me = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15).json()
            (ok if me.get("ok") else bad).append(
                f"бот Telegram — @{me['result']['username']} на связи" if me.get("ok")
                else "бот Telegram — токен не подошёл, проверь его у @BotFather")
        except Exception:
            bad.append("бот Telegram — нет связи с Telegram (интернет, VPN)")
    else:
        optional.append("бот Telegram — нет токена: с телефона управлять нельзя (бот создаётся у @BotFather)")

    from skills import telegram as TG
    if TG.ready():
        ok.append("личный Telegram — подключён")
    else:
        optional.append("личный Telegram — не подключён: писать людям можно и через Telegram на компьютере")

    print()
    for line in ok:
        print(f"  [ok]  {line}")
    for line in bad:
        print(f"  [!!]  {line}")
    for line in optional:
        print(f"  [  ]  {line}")
    print()
    if any("Gemini" in b and "нет ключа" in b for b in bad):
        print("Джарвис заработает и так, но без свободного разговора.")
        print("Ключ Gemini берётся тут: https://aistudio.google.com/apikey")
    elif any("Gemini" in b for b in bad):
        print("Джарвис заработает и так, но умный режим — только с VPN: включи его и запусти проверку снова.")
    else:
        print("Всё готово. Запускай jarvis.bat")


if __name__ == "__main__":
    if "--check" in sys.argv:
        config.setup_console()
        check()
    else:
        main()
