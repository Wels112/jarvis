# -*- coding: utf-8 -*-
"""Конфигурация Джарвиса. Всё в одном месте."""
import json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BRAIN = DATA / "brain"          # второй мозг: заметки
LOGS = DATA / "logs"
MODELS = ROOT / "models"
CONFIG_FILE = ROOT / "config" / "settings.json"
ENV_FILE = ROOT / "config" / ".env"

for d in (DATA, BRAIN, LOGS, MODELS, ROOT / "config"):
    d.mkdir(parents=True, exist_ok=True)

DEFAULTS = {
    "name": "Джарвис",
    "wake_words": ["джарвис", "жарвис", "джарвес", "дарвис", "джорвис"],
    "owner": "хозяин",              # как обращаться — спрашивает установщик
    # Где искать: Яндекс лучше знает города России, места и организации —
    # хозяин попросил его прямо (07.10.2026). «Ищи через гугл» — переключит
    "search_engine": "yandex",
    "voice": {
        "engine": "sapi",           # sapi | silero
        "sapi_voice": "Irina",
        "rate": 1,                  # -10..10, скорость речи
        "volume": 100,
    },
    "ears": {
        "input_device": None,       # None = системный по умолчанию
        "model": "small",           # tiny | base | small | medium
        "device": "cpu",            # cpu | cuda
        "language": "ru",
        "vad_aggressiveness": 2,
        "silence_ms": 900,          # тишина, после которой фраза считается законченной
        "max_phrase_s": 20,
    },
    "brain": {
        "provider": "gemini",
        "model": "gemini-2.0-flash",
        "max_history": 20,
    },
    "safety": {
        "confirm_destructive": True,   # переспрашивать перед удалением/отправкой/покупками
        "allow_shutdown": True,
    },
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    if CONFIG_FILE.exists():
        try:
            # utf-8-sig, а не utf-8: Блокнот и PowerShell 5.1 ставят в начало файла
            # невидимую метку BOM, и json на ней спотыкается. Проверка установки
            # 05.10.2026: настройки не прочитались, Джарвис взял значения по
            # умолчанию и заговорил механическим голосом вместо живого.
            cfg = _deep_merge(cfg, json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig")))
        except Exception as e:
            print(f"[config] settings.json битый ({e}), беру значения по умолчанию")
    return cfg


def save(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def update_setting(path: str, value) -> None:
    """Поменять одну настройку («phone.owner_id») — в памяти и в settings.json.

    Только её: save() записал бы в файл и все значения по умолчанию, и потом
    их уже не поменять обновлением кода.
    """
    keys = path.split(".")
    node = CFG
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    node[keys[-1]] = value
    raw = {}
    if CONFIG_FILE.exists():
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
        except ValueError:
            return                  # битый файл не перезаписываем — пусть разберётся человек
    node = raw
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    node[keys[-1]] = value
    CONFIG_FILE.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")


def env(key: str, default: str = "") -> str:
    """Ключи API: сначала переменные окружения, потом config/.env"""
    if os.environ.get(key):
        return os.environ[key]
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == key:
                # Хвостовой комментарий — не часть ключа: «KEY=abc  # зачем он»
                v = v.split("#", 1)[0] if "#" in v else v
                return v.strip().strip('"').strip("'")
    return default


def setup_console():
    """Windows-консоль по умолчанию не UTF-8 — русский превращается в кашу.

    Кодовую страницу переключаем прямо отсюда, а не только через chcp в батнике:
    так русский вывод и ввод работают, даже если Джарвиса запустили не через .bat.
    """
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


CFG = load()
