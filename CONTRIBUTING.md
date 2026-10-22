# Как вносить изменения в CreditFlow

Замысел и требования — [docs/design.md](docs/design.md). Код следует ему; если код и документ расходятся, это обсуждается в PR, а не решается молча.

## Окружение

| Инструмент | Версия |
| --- | --- |
| Docker с Compose v2 | — |
| Python | 3.12 (`.python-version`) |
| [uv](https://docs.astral.sh/uv/) | для `api` и `ext-sim`, зависимости в `uv.lock` |
| Node.js | 22 LTS (`.nvmrc`) |
| pnpm | версия из `web/package.json` (`packageManager`), зависимости в `pnpm-lock.yaml` |
| GNU Make | — |

```bash
cp .env.example .env
make dev
```

`make dev` поднимает стек и дополнительно открывает на `127.0.0.1` порты `api` (`8000`) и `db` (`5432`) через `docker-compose.dev.yml`. Обычный `docker compose up` публикует только `web`. Файл `docker-compose.override.yml` не создавайте: Compose подключил бы его автоматически, CI это проверяет.

Фронтенд с горячей перезагрузкой — `cd web && pnpm install && pnpm dev`: Vite проксирует `/api` на `localhost:8000` из `make dev`.

## Проверки

| Команда | Что делает |
| --- | --- |
| `make test` | pytest для `api` и `ext-sim`, vitest для `web` |
| `make lint` | ruff, mypy, eslint, prettier, `tsc -b` |
| `make fmt` | автоисправление и форматирование |
| `make openapi er` | перегенерировать `docs/openapi*.json` и `docs/er.md` |

Тестам `api` нужен PostgreSQL: по умолчанию — `db` из `make dev`. Другой адрес задаётся `TEST_DATABASE_URL`.

Цели `demo-reset`, `llm-check`, `llm-record`, `eval-intent`, `eval-injection`, `e2e`, `load` пока не реализованы и завершаются ошибкой со ссылкой на задачу.

CI (`.github/workflows/ci.yml`) повторяет эти проверки и дополнительно падает, если:

- `uv.lock` или `pnpm-lock.yaml` не соответствуют манифестам;
- `docs/` отличается от результата `make openapi er`;
- образ не собирается, стек не поднимается или порты опубликованы у кого-то кроме `web`.

## Ветки и коммиты

- Ветка от свежего `master`: `feat/<номер issue>-<кратко>`, например `feat/6-risk-engine`.
- Сообщения коммитов — [Conventional Commits](https://www.conventionalcommits.org/ru/): `feat(ext-sim): …`, `fix(api): …`, `docs(design): …`, `ci: …`, `build: …`, `test: …`, `chore: …`.
- PR — до ~400 строк изменений без учёта фикстур и lock-файлов. Большую задачу делите на несколько PR.
- Описание PR — по шаблону `.github/PULL_REQUEST_TEMPLATE.md`, со ссылкой на issue.

## Контракт API

Изменение `docs/openapi.json` или `docs/openapi-ext-sim.json` — это изменение контракта. Такой PR принимается только с label `contract-change`. Файлы не правятся руками: меняется код, затем `make openapi`.

## Защита `master`

Правило для всех:

- в `master` — только через PR;
- CI зелёный;
- одно approve;
- без force-push.

Включает защиту в настройках GitHub владелец репозитория.

## Зависимости

Обновляются вручную, отдельным PR: правка `pyproject.toml` и `uv lock` для `api` и `ext-sim`, `pnpm add` или `pnpm update` для `web`. Lock-файлы коммитятся вместе с манифестами, иначе CI упадёт.

## Данные и секреты

- Только синтетические данные: никаких реальных ИНН, ФИО, выписок. Формат фикстур внешних систем — [ext-sim/fixtures/README.md](ext-sim/fixtures/README.md).
- `.env` не коммитится; в `.env.example` ключи провайдеров и токены всегда пустые.
- Пароли, токены, ключ LLM и тексты клиента не попадают в логи.
