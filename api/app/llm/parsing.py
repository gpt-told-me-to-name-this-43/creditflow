"""Финальный контент ответа модели → JSON-объект.

Reasoning-модели могут вернуть рассуждения в `<think>…</think>` внутри `content`
(Qwen3, DeepSeek-R1 у части провайдеров) или в отдельном поле `reasoning`/`reasoning_content`.
Отдельное поле клиент не читает вовсе; блоки `<think>` вырезаются здесь.
"""

import json
import re
from typing import Any

from app.llm.base import LlmInvalidOutput

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)


def final_content(content: str) -> str:
    text = _THINK.sub("", content)
    # незакрытый <think> в начале (обрезанный вывод) или только закрывающий тег
    if "</think>" in text.lower():
        text = text[text.lower().rindex("</think>") + len("</think>") :]
    elif text.lstrip().lower().startswith("<think>"):
        return ""
    text = text.strip()
    fence = _FENCE.match(text)
    return fence.group(1).strip() if fence else text


def parse_json_object(content: str) -> dict[str, Any]:
    text = final_content(content)
    candidates = [text]
    start, end = text.find("{"), text.rfind("}")
    if start > 0 or (start >= 0 and end != len(text) - 1):
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise LlmInvalidOutput("ответ модели — не JSON-объект")
