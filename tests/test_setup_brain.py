# -*- coding: utf-8 -*-
"""«Настройка мозга» для заказчика: выбор провайдера без правки файлов руками.

Диалог (input) подменяется, настоящие config/.env и settings.json не трогаются —
пишем во временные. Проверяется: российский посредник без VPN и Gemini.
"""
import builtins
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import config


def run(answers):
    """Прогнать setup_brain с заданными ответами; вернуть (settings, env)."""
    import webbrowser
    from skills import setup_brain
    it = iter(answers)
    real_input = builtins.input
    real_open = webbrowser.open
    builtins.input = lambda prompt="": next(it)
    webbrowser.open = lambda *a, **k: None       # не открываем настоящие вкладки в тесте
    tmp = Path(tempfile.mkdtemp())
    real = (config.CONFIG_FILE, config.ENV_FILE)
    config.CONFIG_FILE = tmp / "settings.json"
    config.ENV_FILE = tmp / ".env"
    config.CONFIG_FILE.write_text(json.dumps({"brain": {"provider": "gemini"}}), encoding="utf-8")
    try:
        setup_brain.main()
        settings = json.loads(config.CONFIG_FILE.read_text(encoding="utf-8"))
        env = {}
        if config.ENV_FILE.exists():
            for line in config.ENV_FILE.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip()
        return settings, env
    finally:
        builtins.input = real_input
        webbrowser.open = real_open
        config.CONFIG_FILE, config.ENV_FILE = real


def main():
    config.setup_console()
    errors = 0

    def check(name, ok, detail=""):
        nonlocal errors
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} {name}{' — ' + str(detail)[:110] if detail else ''}")

    # 1. ProxyAPI (без VPN): выбор 1, модель по умолчанию (Enter), ключ
    s, e = run(["1", "", "proxy-key"])
    check("ProxyAPI: provider=openai, base_url и модель записаны",
          s["brain"]["provider"] == "openai" and "proxyapi" in s["brain"]["base_url"]
          and s["brain"]["model"] == "gpt-4o-mini" and e.get("CLOUD_API_KEY") == "proxy-key", s["brain"])

    # 2. Другой сервис (выбор 4): свой адрес и модель
    s, e = run(["4", "https://my.gateway/v1/", "deepseek-chat", "my-key"])
    check("свой сервис: адрес без хвостового слэша, своя модель",
          s["brain"]["base_url"] == "https://my.gateway/v1" and s["brain"]["model"] == "deepseek-chat"
          and e.get("CLOUD_API_KEY") == "my-key", s["brain"])

    # 3. Gemini (выбор 5): provider=gemini, ключ в GEMINI_API_KEY
    s, e = run(["5", "AIzaTEST"])
    check("Gemini: provider=gemini, ключ в GEMINI_API_KEY",
          s["brain"]["provider"] == "gemini" and e.get("GEMINI_API_KEY") == "AIzaTEST", s["brain"])

    # 4. Отмена (0): ничего не меняется
    s, e = run(["0"])
    check("отмена — provider остался gemini, ключей нет", s["brain"]["provider"] == "gemini" and not e)

    # 5. Пустой ключ — не записываем провайдера
    s, e = run(["1", "", ""])
    check("пустой ключ — не трогаем настройки", s["brain"]["provider"] == "gemini" and not e.get("CLOUD_API_KEY"))

    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
