# -*- coding: utf-8 -*-
"""«Настройка мозга» для заказчика — выбрать нейросеть без правки файлов руками.

Заказчик далёк от IT, а умный режим (ответы на вопросы, свободный разговор)
требует ключа. Здесь — простой диалог в окне: выбрать провайдера, вставить ключ,
и всё само запишется в settings.json и config/.env. Запускается двойным кликом
по «настройка мозга.bat» (python -m skills.setup_brain).

Два пути:
  1) Без VPN — любой российский посредник с OpenAI-совместимым API и оплатой в
     рублях (ProxyAPI, AITUNNEL и др.): просто и всегда работает, но платно.
  2) Бесплатно — Gemini от Google, но из России нужен VPN.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import config

# Известные OpenAI-совместимые провайдеры: имя → (адрес, модель по умолчанию, где взять ключ)
PROVIDERS = {
    "1": ("ProxyAPI (без VPN, рубли)", "https://api.proxyapi.ru/openai/v1", "gpt-4o-mini", "proxyapi.ru"),
    "2": ("AITUNNEL (без VPN, рубли)", "https://api.aitunnel.ru/v1", "gpt-4o-mini", "aitunnel.ru"),
    "3": ("OpenAI напрямую (нужен зарубежный аккаунт)", "https://api.openai.com/v1", "gpt-4o-mini", "platform.openai.com"),
    "4": ("Другой (впишу адрес сам)", "", "gpt-4o-mini", ""),
}


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print("\nОтменено.")
        sys.exit(0)


def main():
    config.setup_console()
    print("=" * 60)
    print("  Настройка умного режима Джарвиса")
    print("=" * 60)
    print("""
  Умный режим — это ответы на вопросы и свободный разговор.
  Простые команды (открыть программу, громкость, напоминания)
  работают и без него.

  Выберите, как подключить умный режим:

    1  — Без VPN, через российский сервис ProxyAPI (платно, рубли)
    2  — Без VPN, через российский сервис AITUNNEL (платно, рубли)
    3  — OpenAI напрямую (нужен зарубежный аккаунт и карта)
    4  — Другой OpenAI-совместимый сервис
    5  — Бесплатно через Gemini от Google (нужен VPN)
    0  — Отмена
""")
    choice = _ask("  Ваш выбор [1-5, 0]: ")

    if choice == "0" or not choice:
        print("  Ничего не менял.")
        return

    if choice == "5":
        print("""
  Gemini (бесплатно, но нужен VPN):
    1. Включите VPN.
    2. Откройте aistudio.google.com/apikey, войдите в Google.
    3. Нажмите «Create API key», скопируйте ключ (начинается с AIza).
""")
        try:
            import webbrowser
            webbrowser.open("https://aistudio.google.com/apikey")
        except Exception:
            pass
        key = _ask("  Вставьте ключ Gemini: ")
        if not key:
            print("  Ключ пустой — ничего не менял.")
            return
        config.set_env("GEMINI_API_KEY", key)
        config.update_setting("brain.provider", "gemini")
        config.update_setting("brain.model", "gemini-3.5-flash-lite")
        print("\n  Готово. Умный режим — Gemini. Не забудьте включать VPN.")
        print("  Перезапустите Джарвиса (закройте и откройте ярлык).")
        return

    if choice not in PROVIDERS:
        print("  Не понял выбор — ничего не менял.")
        return

    name, base_url, model, site = PROVIDERS[choice]
    print(f"\n  {name}")
    if site:
        print(f"    Ключ берётся на сайте: {site}")
        print("    Зарегистрируйтесь там, пополните баланс и создайте ключ (API key).")
        try:
            import webbrowser
            webbrowser.open("https://" + site)
            print("    (сайт открыт в браузере)")
        except Exception:
            pass
    if not base_url:
        base_url = _ask("\n  Адрес сервиса (base_url, вид https://.../v1): ")
        if not base_url:
            print("  Адрес пустой — ничего не менял.")
            return
    m = _ask(f"\n  Название модели [{model}]: ")
    if m:
        model = m
    key = _ask("  Вставьте ключ от сервиса: ")
    if not key:
        print("  Ключ пустой — ничего не менял.")
        return

    config.set_env("CLOUD_API_KEY", key)
    config.update_setting("brain.provider", "openai")
    config.update_setting("brain.base_url", base_url.rstrip("/"))
    config.update_setting("brain.model", model)
    print(f"\n  Готово. Умный режим — {name}, модель {model}.")
    print("  VPN для него не нужен.")
    print("  Перезапустите Джарвиса (закройте и откройте ярлык).")


if __name__ == "__main__":
    main()
    try:
        input("\n  Нажмите Enter, чтобы закрыть окно.")
    except (EOFError, KeyboardInterrupt):
        pass
