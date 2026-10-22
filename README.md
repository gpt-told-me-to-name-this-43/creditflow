# CreditFlow

MVP кредитного конвейера с AI-assist для хакатона «Умный кредитный кабинет предпринимателя».

**CreditFlow** — веб-продукт из двух кабинетов, клиента и менеджера. Заявка действующего клиента банка проходит в нём весь путь: от свободного текста предпринимателя через решение менеджера до подписания договора и смоделированной выдачи. Сценарий один, сквозной, на синтетических данных.

Роли разделены: LLM с открытыми весами помогает распознать потребность и объяснить риски, детерминированный скоринг на Python считает DSCR, балл и лимит, решение принимает кредитный менеджер. Инвариант: `LLM ≠ скоринг ≠ кредитное решение`. Подробно — [docs/design.md](docs/design.md).

> **Черновик.** Сейчас в репозитории каркас платформы: стек в Docker, симулятор внешних систем `ext-sim`, `api` с health-проверкой и страница-заглушка `web`. Кабинеты клиента и менеджера, скоринг и AI-assist появятся в следующих задачах.

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
