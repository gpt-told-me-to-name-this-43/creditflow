"""Инструменты LLM-слоя: `python -m app.llm.cli --help`.

- `check` (`make llm-check`) — одно тестовое обращение: модель, латентность, поддержка
  `json_schema` и рекомендуемое `LLM_STRUCTURED_OUTPUT`; понятная ошибка при неверном ключе,
  несуществующей модели или недоступном endpoint. Код выхода 1 — конфигурация не работает.
- `eval-intent` (`make eval-intent`) — «только правила» против «правила + LLM» на
  `tests/eval/intent.jsonl`; `--models` сравнивает кандидатов, `--out` пишет markdown.
- `record` — дополнение replay: eval, C1–C7 и injection; нужна отдельная тестовая БД.
- `eval-injection` — тот же набор injection в replay/disabled или на модели проверяющего.

Конфигурация — переменные окружения и `.env` в корне репозитория, как у api. Ключ не
печатается; URL — только хост.
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import openai
import structlog
from pydantic import ValidationError

from app.core.config import LLMMode, Settings, StructuredOutput
from app.llm.base import LlmTask
from app.llm.client import (
    OpenAICompatibleClient,
    RecordingClient,
    ReplayClient,
    model_for,
    provider_name,
)
from app.llm.evaluation import (
    Report,
    category_table,
    evaluate,
    load_cases,
    misses_table,
    summary_table,
)
from app.llm.intent import interpret_text

REPO_ROOT = Path(__file__).resolve().parents[3]
API_DIR = REPO_ROOT / "api"
DEFAULT_DATASET = API_DIR / "tests" / "eval" / "intent.jsonl"
INJECTION_DATASET = API_DIR / "tests" / "eval" / "injection.jsonl"
# CLI не подписывает токены: ключ нужен только чтобы Settings прошли проверку (#5).
_PLACEHOLDER_SECRET = "llm-cli-placeholder-not-a-secret-0123456789"

_CHECK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer"],
    "properties": {"answer": {"type": "string", "enum": ["ok"]}},
}
_CHECK_MESSAGES = [
    {"role": "system", "content": 'Ответь JSON-объектом {"answer": "ok"} и ничем больше.'},
    {"role": "user", "content": "Проверка связи."},
]


def load_settings(**overrides: Any) -> Settings:
    env_file = REPO_ROOT / ".env"
    values: dict[str, Any] = {"app_secret_key": _PLACEHOLDER_SECRET, **overrides}
    return Settings(_env_file=env_file if env_file.exists() else None, **values)


def _redact(text: str, settings: Settings) -> str:
    if settings.llm_api_key:
        text = text.replace(settings.llm_api_key, "***")
    text = re.sub(r"(sk|pk|or)-[A-Za-z0-9_\-]{8,}", "***", text)
    return " ".join(text.split())[:300]


def _explain_status(exc: openai.APIStatusError, settings: Settings) -> str:
    code = exc.status_code
    # только текст ошибки провайдера: в теле бывают идентификаторы аккаунта
    detail = type(exc).__name__  # тело провайдера может содержать секреты и ПДн
    hints = {
        401: "ключ отклонён — проверьте LLM_API_KEY",
        403: "доступ запрещён — проверьте LLM_API_KEY и права ключа на модель",
        404: "endpoint или модель не найдены — проверьте LLM_BASE_URL (…/v1) и LLM_MODEL",
        429: "лимит запросов провайдера — повторите позже",
    }
    hint = hints.get(code)
    if hint is None and code in (400, 422) and re.search(r"model", detail, re.IGNORECASE):
        hint = "модель не найдена или недоступна — проверьте LLM_MODEL"
    if hint is None and code >= 500:
        hint = "сбой на стороне провайдера"
    return f"HTTP {code}: {hint or 'запрос отклонён'} ({detail})"


async def _probe(
    client: openai.AsyncOpenAI, settings: Settings, model: str, mode: StructuredOutput
) -> tuple[int, Any]:
    request: dict[str, Any] = {
        "model": model,
        "messages": _CHECK_MESSAGES,
        "temperature": settings.llm_temperature,
        "max_tokens": settings.llm_max_tokens,
    }
    if mode is StructuredOutput.JSON_SCHEMA:
        request["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "check", "strict": True, "schema": _CHECK_SCHEMA},
        }
    elif mode is StructuredOutput.JSON_OBJECT:
        request["response_format"] = {"type": "json_object"}
    if settings.llm_extra_body:
        request["extra_body"] = dict(settings.llm_extra_body)
    started = time.monotonic()
    response = await client.chat.completions.create(**request)
    return int((time.monotonic() - started) * 1000), response


def _answer_ok(response: Any) -> tuple[bool, bool]:
    """(ответ — валидный JSON {"answer": "ok"}, модель вернула рассуждения)."""
    from app.llm.parsing import final_content

    message = response.choices[0].message if response.choices else None
    content = (message.content or "") if message else ""
    extra = getattr(message, "model_extra", None) or {}
    reasoning = bool(extra.get("reasoning") or extra.get("reasoning_content")) or (
        "<think>" in content.lower()
    )
    try:
        data = json.loads(final_content(content))
    except ValueError:
        return False, reasoning
    return data == {"answer": "ok"}, reasoning


async def check(settings: Settings, probe_formats: bool = False) -> int:
    print(f"LLM_MODE={settings.llm_mode.value}")
    if settings.llm_mode is not LLMMode.OPENAI:
        print("Провайдер не используется: replay — записанные ответы, disabled — шаблоны.")
        print("Для проверки провайдера: LLM_MODE=openai, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL.")
        return 0
    if not settings.llm_base_url or not settings.llm_model:
        print("ОШИБКА: не заданы LLM_BASE_URL и/или LLM_MODEL.")
        return 1
    print(f"Провайдер: {provider_name(settings.llm_base_url)}")
    models = {model_for(settings, t) for t in LlmTask}
    print(f"Модели: {', '.join(sorted(m for m in models if m))}")
    print(f"LLM_STRUCTURED_OUTPUT={settings.llm_structured_output.value}")
    client = OpenAICompatibleClient(settings)._client  # тот же SDK-клиент, что у api
    model = settings.llm_model
    supported: list[StructuredOutput] = []
    reasoning_seen = False
    exit_code = 1
    modes = list(StructuredOutput) if probe_formats else [settings.llm_structured_output]
    try:
        for mode in modes:
            try:
                latency, response = await _probe(client, settings, model, mode)
            except openai.APIStatusError as exc:
                print(f"  {mode.value:12} → {_explain_status(exc, settings)}")
                if exc.status_code in (401, 403, 404) or (
                    exc.status_code in (400, 422) and "модель" in _explain_status(exc, settings)
                ):
                    break  # дальше режимы не помогут: проблема в ключе, модели или URL
                continue
            except openai.APITimeoutError:
                print(f"  {mode.value:12} → таймаут {settings.llm_timeout_seconds:.0f} с")
                continue
            except openai.APIConnectionError:
                print(
                    f"  {mode.value:12} → нет соединения с {provider_name(settings.llm_base_url)}"
                )
                break
            ok, reasoning = _answer_ok(response)
            reasoning_seen |= reasoning
            usage = getattr(response, "usage", None)
            tokens = getattr(usage, "total_tokens", "?") if usage else "?"
            print(
                f"  {mode.value:12} → {'OK' if ok else 'ответ не прошёл проверку'}, "
                f"модель {getattr(response, 'model', model)}, {latency} мс, токенов {tokens}"
            )
            if ok:
                supported.append(mode)
                if mode is settings.llm_structured_output:
                    exit_code = 0
    finally:
        await client.close()
    if supported:
        schema_ok = StructuredOutput.JSON_SCHEMA in supported
        schema_status = "поддерживается" if schema_ok else "не проверена или не поддерживается"
        print(f"json_schema: {schema_status}")
        print(f"Рекомендуется: LLM_STRUCTURED_OUTPUT={supported[0].value}")
    if reasoning_seen:
        print(
            "Модель возвращает рассуждения: они учитываются в таймауте; отключить можно через "
            'LLM_EXTRA_BODY (OpenRouter: {"reasoning": {"enabled": false}}).'
        )
    if exit_code:
        print("ИТОГ: конфигурация LLM не работает — api продолжит на правилах и шаблонах.")
    return exit_code


def _report_markdown(reports: list[Report], dataset: Path, settings: Settings) -> str:
    rules = reports[0]
    lines = [
        f"Датасет: `{dataset}`, {len(rules.results)} фраз. "
        f"Провайдер: {provider_name(settings.llm_base_url)}; "
        f"LLM_STRUCTURED_OUTPUT={settings.llm_structured_output.value}; "
        f"дата: {time.strftime('%Y-%m-%d')}.",
        "",
        summary_table(reports),
        "",
        "По категориям (фраза целиком):",
        "",
        category_table(reports),
    ]
    for report in reports:
        lines += ["", f"Промахи — {report.label}:", "", misses_table(report)]
    return "\n".join(lines) + "\n"


async def eval_intent(
    settings: Settings, dataset: Path, models: list[str], out: Path | None, rules_only: bool
) -> int:
    cases = load_cases(dataset)
    reports = [await evaluate(cases, None, "только правила")]
    if not rules_only:
        if settings.llm_mode is LLMMode.REPLAY:
            reports.append(
                await evaluate(cases, ReplayClient(settings.llm_replay_dir), "правила + replay")
            )
        elif settings.llm_mode is LLMMode.OPENAI and settings.llm_base_url and settings.llm_model:
            for model in models or [settings.llm_model]:
                live = settings.model_copy(update={"llm_model": model, "llm_model_intent": None})
                client = OpenAICompatibleClient(live)
                try:
                    reports.append(
                        await evaluate(
                            cases, client, f"правила + {model}", live.llm_timeout_seconds
                        )
                    )
                finally:
                    await client.aclose()
        elif settings.llm_mode is not LLMMode.DISABLED:
            print("ОШИБКА: нужны LLM_BASE_URL и LLM_MODEL")
            return 1
    text = _report_markdown(reports, dataset, settings)
    print(text)
    if out is not None:
        await asyncio.to_thread(out.write_text, text, encoding="utf-8")
        print(f"записано: {out}")
    if any(r.failures for r in reports):
        print("ОШИБКА: часть вызовов LLM не выполнена; таблица включает fallback правил.")
        return 1
    rules = reports[0]
    if min(rules.accuracy("requested_amount_rub"), rules.accuracy("term_months")) < 0.85:
        print("ОШИБКА: точность правил по сумме/сроку ниже 85%")
        return 1
    return 0


async def record_intent(settings: Settings) -> int:
    if settings.llm_mode is not LLMMode.OPENAI:
        print("record-intent: нужен LLM_MODE=openai (запись идёт с настоящего провайдера)")
        return 1
    client = RecordingClient(OpenAICompatibleClient(settings), settings.llm_replay_dir)
    texts = [c.text for c in load_cases(DEFAULT_DATASET)]
    texts += [
        json.loads(line)["text"]
        for line in INJECTION_DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    try:
        for text in texts:
            await interpret_text(text, client, settings.llm_timeout_seconds)
    finally:
        await client.inner.aclose()
    if client.failed:
        print(f"ОШИБКА: не удалось записать вызовов: {client.failed}")
        return 1
    print(f"записано фикстур extract_intent: {len(client.recorded)}")
    return 0


async def scenarios(settings: Settings, *, record: bool = False) -> int:
    """Те же интеграционные сценарии, что в CI, без второго тестового раннера."""
    if not os.environ.get("TEST_DATABASE_URL"):
        print("ОШИБКА: задайте TEST_DATABASE_URL отдельной тестовой БД; сценарии очищают её.")
        return 1
    env = dict(os.environ)
    for key, value in settings.model_dump(mode="json").items():
        if key.startswith("llm_"):
            env[key.upper()] = (
                json.dumps(value)
                if isinstance(value, dict)
                else str(value)
                if value is not None
                else ""
            )
    env.pop("LLM_LIVE", None)
    env.pop("LLM_RECORD", None)
    paths = ["tests/applications/test_ai_injection.py"]
    if record:
        env["LLM_RECORD"] = "1"
        paths.insert(0, "tests/applications/test_ai_replay.py")
    elif settings.llm_mode is LLMMode.OPENAI:
        env["LLM_LIVE"] = "1"
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pytest", "-q", *paths, cwd=API_DIR, env=env
    )
    return await process.wait()


async def record(settings: Settings) -> int:
    if os.environ.get("LLM_RECORD") != "1" or settings.llm_mode is not LLMMode.OPENAI:
        print("ОШИБКА: запись требует явных LLM_RECORD=1 и LLM_MODE=openai.")
        return 1
    if not os.environ.get("TEST_DATABASE_URL"):
        print("ОШИБКА: задайте TEST_DATABASE_URL отдельной тестовой БД (она очищается).")
        return 1
    code = await record_intent(settings)
    return code if code else await scenarios(settings, record=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.llm.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    probe = sub.add_parser("check", help="проверка провайдера (make llm-check)")
    probe.add_argument(
        "--probe-formats", action="store_true", help="проверить все три формата (три вызова)"
    )
    ev = sub.add_parser("eval-intent", help="eval распознавания (make eval-intent)")
    ev.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    ev.add_argument("--models", default="", help="кандидаты через запятую")
    ev.add_argument("--out", type=Path, default=None, help="markdown с результатом")
    ev.add_argument("--rules-only", action="store_true", help="без провайдера (как в CI)")
    sub.add_parser("record", help="дополнить replay: intent, C1–C7, injection (LLM_RECORD=1)")
    sub.add_parser("eval-injection", help="injection: replay/disabled/live; нужна тестовая БД")
    args = parser.parse_args(argv)
    # вывод CLI — отчёт; события вызовов (info) не нужны, предупреждения и ошибки — да
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(30))
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        settings = load_settings()
        if args.command == "check":
            return asyncio.run(check(settings, args.probe_formats))
        if args.command == "eval-intent":
            models = [m.strip() for m in args.models.split(",") if m.strip()]
            return asyncio.run(
                eval_intent(settings, args.dataset, models, args.out, args.rules_only)
            )
        if args.command == "eval-injection":
            return asyncio.run(scenarios(settings))
        return asyncio.run(record(settings))
    except (ValidationError, OSError, ValueError):
        print(
            "ОШИБКА: проверьте конфигурацию LLM, формат JSON и доступность файлов.", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
