"""Версионированные промпты: `app/llm/prompts/<task>/<version>/{system.md, user.jinja}`.

Новая версия промпта — новая папка; `prompt_version` входит в `context_hash`, поэтому
replay-фикстуры старой версии не подменяют новую. Текст клиента попадает только в
user-сообщение, в блок `<client_text_untrusted>`, и не может закрыть этот блок:
угловые скобки заменяются фильтром `untrusted`.
"""

import json
import unicodedata
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any

from jinja2 import FileSystemLoader, StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from app.core.config import StructuredOutput
from app.llm.base import LlmTask, canonical_json

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
REPAIR_KEY = "repair"


def untrusted(value: object) -> str:
    """Недоверенный текст: без управляющих символов и без `<`/`>` — блок не закрыть."""
    text = "" if value is None else str(value)
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    return text.replace("<", "‹").replace(">", "›")


@cache
def _env() -> SandboxedEnvironment:
    env = SandboxedEnvironment(
        loader=FileSystemLoader(PROMPTS_DIR),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=False,
    )
    env.filters["untrusted"] = untrusted
    env.filters["tojson_canonical"] = lambda v: json.dumps(v, ensure_ascii=False, indent=2)
    return env


def prompt_dir(task: LlmTask, version: str) -> Path:
    return PROMPTS_DIR / task.value / version


@cache
def system_prompt(task: LlmTask, version: str) -> str:
    return (prompt_dir(task, version) / "system.md").read_text(encoding="utf-8").strip()


def build_messages(
    task: LlmTask,
    version: str,
    context: Mapping[str, Any],
    mode: StructuredOutput,
    json_schema: Mapping[str, Any],
) -> list[dict[str, str]]:
    """system — только наш текст (+ схема для json_object/prompt); user — данные контекста."""
    system = system_prompt(task, version)
    if mode is not StructuredOutput.JSON_SCHEMA:
        system += (
            "\n\nФормат ответа — один JSON-объект строго по этой JSON Schema:\n"
            + canonical_json(dict(json_schema))
        )
    data = {k: v for k, v in context.items() if k != REPAIR_KEY}
    user = _env().get_template(f"{task.value}/{version}/user.jinja").render(**data).strip()
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    repair = context.get(REPAIR_KEY)
    if repair:
        messages.append(
            {
                "role": "user",
                "content": f"Предыдущий ответ отклонён проверкой: {repair} "
                "Верни исправленный JSON-объект по тем же правилам.",
            }
        )
    return messages
