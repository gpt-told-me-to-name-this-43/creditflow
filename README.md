# CreditFlow

MVP кредитного конвейера с AI-assist для хакатона «Умный кредитный кабинет предпринимателя».

**CreditFlow** — веб-продукт из двух кабинетов, клиента и менеджера. Заявка действующего клиента банка проходит в нём весь путь: от свободного текста предпринимателя через решение менеджера до подписания договора и смоделированной выдачи. Сценарий один, сквозной, на синтетических данных.

Роли разделены: LLM с открытыми весами помогает распознать потребность и объяснить риски, детерминированный скоринг на Python считает DSCR, балл и лимит, решение принимает кредитный менеджер. Инвариант: `LLM ≠ скоринг ≠ кредитное решение`. Подробно — [docs/design.md](docs/design.md).

Реализованы backend-конвейер, кабинеты клиента и менеджера и необязательный AI-assist.
AI использует сохранённые ответы без сети; для новых контекстов доступны правила и шаблоны.

Все компании, ИНН, выписки, продукты и ставки — синтетические.

## Запуск

Нужен Docker с Compose v2. LLM-провайдер и ключи не нужны: по умолчанию `LLM_MODE=replay`.

```bash
git clone https://github.com/gpt-told-me-to-name-this-43/creditflow.git
cd creditflow
cp .env.example .env
docker compose up --build
```

Когда все сервисы станут `healthy`:

- <http://localhost:8080> — Веб-интерфейс
- <http://localhost:8080/api/docs> — Swagger API
- <http://localhost:8080/api/v1/health> — Health

Проверка из второго терминала:

```bash
curl http://localhost:8080/api/v1/health
```

Остановить — `Ctrl+C` в терминале с `docker compose up` или:

```bash
docker compose down
```

Наружу публикуется только порт `8080` сервиса `web`; `api`, `db` и `ext-sim` доступны только во внутренней сети compose. Порты для разработки открывает `make dev` — см. [CONTRIBUTING.md](CONTRIBUTING.md).

## Сервисы

- `web` — nginx: SPA и прокси `/api/` → `api` на одном origin
- `api` — FastAPI, модульный монолит; при старте применяет миграции и базовый seed
- `db` — PostgreSQL 16
- `ext-sim` — Симулятор ЕГРЮЛ, ЕГРИП, ФНС, БКИ и банковской выписки на фикстурах
- `ollama` — Необязательно: локальная LLM, профиль `llm`

## Стек

- **Фронтенд:** Vite + React + TypeScript (strict).
- **Бэкенд:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic.
- **Инфраструктура:** PostgreSQL, nginx, Docker Compose.
- **LLM:** любой OpenAI-совместимый API с моделью с открытыми весами; настройки — в [.env.example](.env.example).

Полный целевой стек — design.md §3.2.

## Документация

- [docs/design.md](docs/design.md) — замысел, сценарий, архитектура, финансовый конвейер, AI-assist, статусы, API, модель данных, безопасность
- [docs/architecture.md](docs/architecture.md) — контейнеры, компоненты `api`, последовательность Submit
- [docs/openapi.json](docs/openapi.json) — контракт API (генерируется `make openapi`)
- [docs/openapi-ext-sim.json](docs/openapi-ext-sim.json) — контракт симулятора внешних систем
- [docs/er.md](docs/er.md) — ER-диаграмма (генерируется `make er`)
- [ext-sim/fixtures/README.md](ext-sim/fixtures/README.md) — формат фикстур внешних систем
- [.env.example](.env.example) — все переменные окружения с комментариями
- [CONTRIBUTING.md](CONTRIBUTING.md) — разработка, проверки, правила веток и PR
- [docs/demo-script.md](docs/demo-script.md) — сценарий показа на 5–7 минут и запасные ответы

### API Contract v1 / frontend

Целевая спецификация — Design 2.5. Инструкция frontend: [docs/frontend-handoff.md](docs/frontend-handoff.md).
Маршруты #5/#7/#8 работают с БД во всех окружениях, JWT, роли и ownership проверяются.
`make openapi api-matrix` обновляет артефакты; `cd web && pnpm generate:api && pnpm typecheck && pnpm test`
проверяет типы и frontend. AI не меняет решение, расчёт или доступные действия.

### E2E

Сквозной путь в браузере — Playwright в `web/e2e/` (спеки s1–s12 и a11y на axe), против стека
с `LLM_MODE=replay` и `APP_ENV=test`. Все спеки делят одну БД: один worker, без ретраев.

```bash
make e2e-up TEST_RESET_TOKEN=<любой секрет>   # стек + docker-compose.e2e.yml
make e2e TEST_RESET_TOKEN=<тот же секрет>
```

Без токена прогон падает в `globalSetup` с объяснением. Отчёт — `web/playwright-report/`,
трейсы и видео упавших спек — `web/test-results/`. В CI — workflow `e2e.yml`.

## Подключить свою модель

По умолчанию `LLM_MODE=replay`: C1–C7 используют записанные ответы из `llm-replay/`,
остальные контексты получают правила/шаблон. В `disabled` всегда работают правила и
шаблонное заключение. Сеть и API-ключ в обоих режимах не нужны.

Для внешнего OpenAI-compatible Chat Completions endpoint измените `.env`:

```dotenv
LLM_MODE=openai
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=<свой ключ>
LLM_MODEL=meta-llama/llama-3.3-70b-instruct
LLM_STRUCTURED_OUTPUT=json_schema
LLM_EXTRA_BODY={"reasoning":{"enabled":false}}
```

Применить: `docker compose up -d --force-recreate api`. `restart` не перечитывает environment.
Ключ хранится только в локальном `.env`; не помещайте его в командную строку или git.
Для CLI установите Python 3.12 и uv, выполните `cd api && uv sync --locked`.
Из корня `make llm-check` проверяет выбранный формат одним запросом и показывает модель,
латентность и usage. `make llm-check LLM_ARGS=--probe-formats` явно проверяет все три
формата (три запроса), затем рекомендует поддержанный. Ошибка ключа, модели, соединения
или выбранного формата возвращает ненулевой код. Replay/disabled просто показывают режим.
CLI читает `.env`; environment и `make LLM_MODE=…` имеют приоритет.

Для локального Ollama запустите `make up-llm`, отдельно скачайте выбранную модель
(`docker compose exec ollama ollama pull <модель>`), затем укажите:

```dotenv
LLM_MODE=openai
LLM_BASE_URL=http://ollama:11434/v1
LLM_API_KEY=
LLM_MODEL=<имя из ollama list>
LLM_STRUCTURED_OUTPUT=json_object
LLM_EXTRA_BODY=
```

Если runtime работает на хосте, для контейнера API используйте
`http://host.docker.internal:11434/v1`, а для CLI на том же хосте —
`LLM_BASE_URL=http://localhost:11434/v1 make llm-check`.
Для vLLM — `http://host.docker.internal:8000/v1` и имя модели, с которым запущен сервер.
При Qwen3 vLLM выключение reasoning задаётся
`LLM_EXTRA_BODY={"chat_template_kwargs":{"enable_thinking":false}}`.
Поддержка `json_schema` зависит от runtime: проверьте `llm-check`, при необходимости
выберите `json_object` или `prompt`; в обоих случаях схема передаётся в инструкции,
а ответ проходит те же backend-валидаторы. Локальный runtime в текущем финальном проходе
не был доступен для проверки на реальных весах.

`LLM_EXTRA_BODY` — JSON-объект дополнительных параметров вашего провайдера.
`LLM_MODEL_INTENT`/`LLM_MODEL_EXPLAIN` переопределяют модель конкретной задачи;
`llm-check` проверяет базовую модель, task overrides нужно проверять отдельно.
`LLM_TIMEOUT_SECONDS=20`, `LLM_REPORT_DEADLINE_SECONDS=60`, concurrency=4;
breaker после пяти сбоев даёт шаблоны на 60 с. Все повторы отчёта входят в общий бюджет.
Reasoning из ответа отбрасывается, но его токены/время всё равно расходуют бюджет.

При недоступности провайдера interpret возвращает правила; заключение становится
FALLBACK. `health.status` остаётся `ok`, если БД и ext-sim исправны; `health.llm` показывает
конфигурацию/breaker (`ok`, `degraded`, `not_configured`, `replay`, `disabled`) без запроса
к модели. PENDING после остановки API восстанавливается шаблоном через budget+15 с и
очередной проход recovery (15 с). GET отчёта никогда не генерирует его заново.

### Eval и replay

| Режим | Цель | Сумма | Срок | Вся фраза | p95, мс |
|---|---|---|---|---|---|
| Только правила | 92% | 92% | 92% | 78% | 0 |
| + Qwen3-32B | 95% | 100% | 100% | 95% | 4038 |
| + Llama 3.3 70B | 98% | 100% | 100% | 98% | 4561 |
| + gpt-oss-120b | 95% | 95% | 98% | 88% | 2931 |

Сохранённые измерения предыдущей сессии на 40 фразах, не независимая перепроверка.
Методика, токены, промахи и ограничения — [docs/ai-eval.md](docs/ai-eval.md),
решение — [ADR](docs/adr/0001-openai-compatible-ai-assist.md),
лицензии — [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

```bash
make help
make llm-check LLM_MODE=replay
make eval-intent LLM_MODE=replay
make eval-intent LLM_ARGS=--rules-only
# Данные этой отдельной тестовой БД будут очищены:
TEST_DATABASE_URL=postgresql+psycopg://test:test@localhost:55432/cf8test make eval-injection LLM_MODE=replay
# Новые платные ответы; старые файлы сохраняются:
LLM_RECORD=1 TEST_DATABASE_URL=<отдельная-тестовая-БД> make llm-record LLM_MODE=openai
```

`eval-injection` в openai вызывает настроенную модель; в replay/disabled работает без
внешней сети. `llm-record` дополняет eval intent, C1–C7 и десять injection-кейсов.
Запись требует явных opt-in и БД; по умолчанию не перезаписывает ни одного существующего
файла. Для новой модели/эксперимента используйте новый `LLM_REPLAY_DIR=/tmp/my-replay`.
Replay-ответы валидируются так же, как live. В CI разрешены только replay и rules-only,
платные вызовы не выполняются.
