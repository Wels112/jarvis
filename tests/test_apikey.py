# -*- coding: utf-8 -*-
"""Ключ умного режима прямо в Telegram: заказчик шлёт «ключ …» — Джарвис

сам определяет сервис, пишет настройки и перезапускает мозг. Здесь проверяем
разбор без сети и без настоящего мозга: config перенаправлен втестовую папку,
reload_brain заглушён, ключ в ответ и в журнал попасть не должен.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import config, phone


class FakeJarvis:
    def __init__(self):
        self.cfg = config.CFG
        self.reloaded = 0

    def reload_brain(self):
        self.reloaded += 1
        return True


def main():
    config.setup_console()
    errors = 0

    def check(name, ok, detail=""):
        nonlocal errors
        errors += not ok
        print(f"{'ok ' if ok else 'НЕТ'} {name}{' — ' + str(detail)[:120] if detail else ''}")

    tmp = ROOT / "data" / "brain" / "test"
    tmp.mkdir(parents=True, exist_ok=True)
    config.ENV_FILE = tmp / ".env.apikey_test"
    config.CONFIG_FILE = tmp / "settings.apikey_test.json"
    config.ENV_FILE.unlink(missing_ok=True)
    config.CONFIG_FILE.unlink(missing_ok=True)
    config.CFG.setdefault("brain", {})
    config.CFG["brain"].pop("base_url", None)
    config.CFG["brain"]["provider"] = "gemini"

    j = FakeJarvis()
    p = phone.Phone(j)

    def env_has(key, piece):
        if not config.ENV_FILE.exists():
            return False
        return any(l.startswith(key + "=") and piece in l for l in config.ENV_FILE.read_text(encoding="utf-8").splitlines())

    # 1. Gemini
    gem = "AIza" + "B" * 35
    r = p._apply_api_key(f"ключ {gem}")
    check("Gemini: включён, ключ в .env, VPN упомянут",
          r and "Gemini" in r and "VPN" in r and env_has("GEMINI_API_KEY", gem)
          and config.CFG["brain"]["provider"] == "gemini", r)
    check("Gemini: ключа нет в ответе", gem not in (r or ""))
    check("Gemini: мозг перезапущен", j.reloaded == 1)

    # 2. sk с подсказкой сервиса
    sk = "sk-" + "a1B2" * 8
    r = p._apply_api_key(f"вот ключ {sk} это proxyapi")
    check("sk+proxyapi: openai-провайдер, адрес ProxyAPI, VPN не нужен",
          r and "ProxyAPI" in r and "не нужен" in r
          and config.CFG["brain"]["provider"] == "openai"
          and config.CFG["brain"]["base_url"] == "https://api.proxyapi.ru/openai/v1"
          and env_has("CLOUD_API_KEY", sk), r)
    check("sk: ключа нет в ответе", sk not in (r or ""))

    # 3. голый sk без подсказки при провайдере gemini → переспрос, затем имя сервиса
    config.CFG["brain"]["provider"] = "gemini"
    config.CFG["brain"].pop("base_url", None)
    sk2 = "sk-" + "Z9y8" * 8
    r = p._apply_api_key(f"ключ {sk2}")
    check("голый sk: переспрос сервиса, ключ отложен",
          r and "какого сервиса" in r.lower() and p._pending_key == sk2, r)
    r = p._apply_api_key("AITUNNEL")
    check("ответ «AITUNNEL»: дооформлен адрес AITUNNEL, ключ использован",
          r and "AITUNNEL" in r and config.CFG["brain"]["base_url"] == "https://api.aitunnel.ru/v1"
          and env_has("CLOUD_API_KEY", sk2) and not p._pending_key, r)

    # 4. обычный текст — не ключ
    check("обычное сообщение не перехватывается", p._apply_api_key("включи музыку") is None)
    check("число похожее, но не ключ", p._apply_api_key("напомни в 12:00") is None)

    config.ENV_FILE.unlink(missing_ok=True)
    config.CONFIG_FILE.unlink(missing_ok=True)
    print(f"\nошибок: {errors}")
    return errors == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
