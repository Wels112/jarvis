# -*- coding: utf-8 -*-
"""Облачный мозг через OpenAI-совместимый API — чтобы заказчик выбрал провайдера сам.

Джарвис изначально ходил только в Gemini (Google), а из России он без VPN не
работает. Заказчик (17.10.2026) может купить ключ у любого провайдера, который
ему подходит: российский посредник с оплатой в рублях и без VPN, сам OpenAI,
DeepSeek, GigaChat-совместимый шлюз или свой сервер. Почти все они говорят на
одном формате — OpenAI Chat Completions. Здесь этот формат и реализован.

Меняется только транспорт: как собрать запрос и разобрать ответ. Инструменты
(те же 60+), характер, закон честности, одно опасное «да» за раз, короткая
память и переключение на свою модель без интернета — всё унаследовано от Brain.

В настройках (settings.json → brain):
  "provider": "openai"           — включает этот мозг вместо Gemini
  "base_url": "https://…/v1"     — адрес провайдера (у OpenAI — https://api.openai.com/v1)
  "model": "gpt-4o-mini"         — имя модели у этого провайдера
  "fallback_models": [...]       — запасные, если основная перегружена
Ключ — в config/.env: CLOUD_API_KEY (или OPENAI_API_KEY).
"""
import json
import re

import requests

from core import config, log, memory
from core.brain import (Brain, PERSONA, TOOLS, RETRYABLE, cloud_error_phrase)
from core.local_brain import _openai_tools


class OpenAIBrain(Brain):
    def __init__(self, cfg: dict):
        super().__init__(cfg)
        b = cfg.get("brain", {})
        self.base_url = (b.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        model = b.get("model", "")
        # Если провайдера переключили на openai, а модель осталась от Gemini —
        # на чужом сервере её нет; берём безопасную по умолчанию
        self.model = model if model and not model.lower().startswith("gemini") else "gpt-4o-mini"
        self.fallbacks = [m for m in b.get("fallback_models", []) if m != self.model
                          and not m.lower().startswith("gemini")]
        self.key = config.env("CLOUD_API_KEY") or config.env("OPENAI_API_KEY") or config.env("GEMINI_API_KEY")
        self.last_error = None
        self._tools = None
        self.session = requests.Session()

    @property
    def ready(self) -> bool:
        return bool(self.key and self.base_url)

    def _tool_schema(self):
        if self._tools is None:
            self._tools = _openai_tools(TOOLS)
        return self._tools

    def _post(self, payload: dict, timeout: int = 45):
        """Запрос к провайдеру, при перегрузке — запасные модели по очереди."""
        errors = []
        for model in [self.model] + self.fallbacks:
            try:
                r = self.session.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
                    json=dict(payload, model=model), timeout=timeout)
            except requests.RequestException as e:
                errors.append(f"{model}: сеть ({e.__class__.__name__})")
                continue
            if r.status_code == 200:
                self.last_model = model
                return r.json()
            errors.append(f"{model}: {r.status_code}")
            bad_model = r.status_code in (400, 404) and "model" in r.text.lower()
            if r.status_code not in RETRYABLE and not bad_model:
                raise RuntimeError(f"{r.status_code}: {r.text[:300]}")
        raise RuntimeError("все модели недоступны — " + "; ".join(errors))

    def _system(self) -> str:
        ctx = memory.context_for_llm(dialog=True)
        return PERSONA + (("\n\nПамять:\n" + ctx) if ctx else "")

    def ask(self, user_text: str, image_path: str = None) -> str:
        self.last_error = None
        if not self.ready:
            return "Умный режим не подключён — нет ключа. Простые команды я всё равно выполняю."

        self.history.append({"role": "user", "content": user_text})
        self._trim()
        turn_start = len(self.history) - 1

        from core.honesty import failed, false_claim, unbacked_claim
        failures, nudged, tools_called = [], False, 0
        system = self._system()
        for _ in range(10):
            payload = {"messages": [{"role": "system", "content": system}] + self.history,
                       "tools": self._tool_schema(), "tool_choice": "auto",
                       "temperature": 0.7, "max_tokens": 400}
            try:
                data = self._post(payload)
            except Exception as e:
                self.last_error = e
                del self.history[turn_start:]
                one_line = re.sub(r"\s+", " ", str(e))[:160]
                log.write("error", f"[мозг] {one_line}")
                return cloud_error_phrase(e)

            msg = (data.get("choices") or [{}])[0].get("message", {}) or {}
            calls = msg.get("tool_calls") or []
            entry = {"role": "assistant", "content": msg.get("content") or ""}
            if calls:
                entry["tool_calls"] = calls
            self.history.append(entry)

            if not calls:
                text = (msg.get("content") or "").strip()
                correction = false_claim(text, failures) or unbacked_claim(text, tools_called)
                if correction and not nudged:
                    nudged = True
                    self.history.append({"role": "user", "content": correction})
                    continue
                if not text:
                    return f"Не получилось: {failures[-1][1]}" if failures else "Готово."
                return text

            tools_called += len(calls)
            for call in calls:
                fn = call.get("function", {}) or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except (ValueError, TypeError):
                    args = {}
                result = self._run_tool(fn.get("name", ""), args if isinstance(args, dict) else {})
                if failed(result):
                    failures.append((fn.get("name", ""), result[:160]))
                self.history.append({"role": "tool",
                                     "tool_call_id": call.get("id") or fn.get("name", ""),
                                     "content": result})
        return "Слишком много шагов, остановился."

    def vision(self, prompt: str, image_b64: str) -> str:
        """Рассмотреть картинку — формат OpenAI (image_url с data:-ссылкой).
        Провайдер без поддержки картинок ответит ошибкой — тогда сработает
        запасной «что открыто в окне» (screen_without_vision)."""
        payload = {"messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
        ]}], "temperature": 0.2, "max_tokens": 200}
        data = self._post(payload)
        return (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()

    def _trim(self):
        """Укоротить историю, не разрывая пару «вызов инструмента — его ответ».

        OpenAI требует, чтобы за assistant с tool_calls шли ответы с ролью tool.
        Режем только до обычного вопроса хозяина, как и Gemini-мозг."""
        def plain_user(turn):
            return turn.get("role") == "user"

        while len(self.history) > self.max_history:
            del self.history[0]
            while self.history and not plain_user(self.history[0]):
                del self.history[0]
