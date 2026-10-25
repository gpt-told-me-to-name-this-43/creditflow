# CreditFlow: команды разработки. Список целей — `make help`.

.DEFAULT_GOAL := help

COMPOSE := docker compose
COMPOSE_DEV := docker compose -f docker-compose.yml -f docker-compose.dev.yml

# Тестам api нужен живой PostgreSQL: по умолчанию — db из `make dev` на localhost:5432.
-include .env
POSTGRES_DB ?= creditflow
POSTGRES_USER ?= creditflow
POSTGRES_PASSWORD ?= creditflow
TEST_DATABASE_URL ?= postgresql+psycopg://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@localhost:5432/$(POSTGRES_DB)
# API для make demo-reset / clean-reset / bru: web (nginx) из make up или make dev.
API_URL ?= http://localhost:8080/api/v1

.PHONY: help up down dev up-llm \
	test test-api test-ext-sim test-web lint lint-api lint-ext-sim lint-web \
	fmt fmt-api fmt-ext-sim fmt-web migrate seed openapi api-matrix er state-machine demo-accounts bru-export demo-data \
	dev-token demo-reset clean-reset bru llm-check llm-record eval-intent eval-injection e2e load

help: ## Список целей
	@grep -hE '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'

## --- Стек ---

up: ## Собрать и поднять стек, дождаться healthy (наружу только web :8080)
	$(COMPOSE) up --build -d --wait

down: ## Остановить стек (данные БД сохраняются в volume pgdata)
	$(COMPOSE) down

dev: ## Стек с портами api :8000 и db :5432 на localhost
	$(COMPOSE_DEV) up --build

up-llm: ## Стек + локальная Ollama (профиль llm)
	$(COMPOSE) --profile llm up --build -d --wait

migrate: ## alembic upgrade head в запущенном api
	$(COMPOSE) exec api alembic upgrade head

seed: ## Базовый seed в запущенном api (идемпотентный)
	$(COMPOSE) exec api python -m app.seed

dev-token: ## JWT демо-учётки для ручной проверки: make -s dev-token EMAIL=… [INN=…] (до #5)
	@cd api && DATABASE_URL='$(TEST_DATABASE_URL)' APP_SECRET_KEY='$(APP_SECRET_KEY)' \
		uv run python ../scripts/dev_token.py '$(EMAIL)' $(if $(INN),--bind '$(INN)')

## --- Проверки ---

test: test-api test-ext-sim test-web ## Все тесты

test-api: ## Тесты api (нужен PostgreSQL, см. TEST_DATABASE_URL)
	cd api && TEST_DATABASE_URL='$(TEST_DATABASE_URL)' uv run pytest

test-ext-sim: ## Тесты ext-sim
	cd ext-sim && uv run pytest

test-web: ## Тесты web
	cd web && pnpm test

lint: lint-api lint-ext-sim lint-web ## Все линтеры и проверка типов

lint-api:
	cd api && uv run ruff check . ../scripts && uv run ruff format --check . ../scripts && uv run mypy app tests alembic contract ../scripts

lint-ext-sim:
	cd ext-sim && uv run ruff check . && uv run ruff format --check . && uv run mypy app tests

lint-web:
	cd web && pnpm lint && pnpm typecheck

fmt: fmt-api fmt-ext-sim fmt-web ## Автоформатирование

fmt-api:
	cd api && uv run ruff check --fix . ../scripts && uv run ruff format . ../scripts

fmt-ext-sim:
	cd ext-sim && uv run ruff check --fix . && uv run ruff format .

fmt-web:
	cd web && pnpm fmt

## --- Контракты ---

# Экспорт OpenAPI создаёт приложение, а оно без APP_SECRET_KEY ≥ 32 байт не стартует (#5).
# Ключ здесь — заглушка только для экспорта: токены им не подписываются.
OPENAPI_EXPORT_ENV := APP_ENV=local APP_SECRET_KEY=openapi-export-placeholder-not-a-secret

openapi: ## docs/openapi.json и docs/openapi-ext-sim.json
	cd api && $(OPENAPI_EXPORT_ENV) uv run python ../scripts/export_openapi.py app.main:app ../docs/openapi.json
	cd ext-sim && uv run python ../scripts/export_openapi.py app.main:app ../docs/openapi-ext-sim.json

api-matrix: ## docs/api-matrix.md из независимого api/contract/http_matrix.yaml
	cd api && uv run python ../scripts/gen_api_matrix.py

demo-accounts: ## Таблица демо-учёток в docs/demo-data.md (= GET /auth/demo-accounts)
	cd api && uv run python ../scripts/gen_demo_accounts.py

bru-export: ## docs/api-collection.json из Bruno-коллекции docs/api-collection
	python3 scripts/export_bruno.py

state-machine: ## docs/state-machine.md из таблицы переходов FSM
	cd api && uv run python ../scripts/gen_state_machine.py

er: ## docs/er.md из метаданных SQLAlchemy
	# app.db.models:Base — тот же Base, но импорт модуля регистрирует все таблицы в metadata
	cd api && uv run python ../scripts/gen_er.py app.db.models:Base ../docs/er.md

demo-data: ## Перегенерировать фикстуры ext-sim (реестр, ФНС, БКИ, выписки) — детерминированно
	python3 scripts/gen_registry_ids.py
	python3 scripts/gen_statements.py

## --- Демо и тестовый контур ---

demo-reset: ## Демо-состояние (#7): POST /_test/reset?mode=demo; в .env TEST_RESET_ENABLED=true и токен
	@curl -fsS -X POST '$(API_URL)/_test/reset?mode=demo' -H 'X-Test-Reset-Token: $(TEST_RESET_TOKEN)' && echo

clean-reset: ## Чистая БД с базовым seed: POST /_test/reset?mode=clean (для bru run и e2e)
	@curl -fsS -X POST '$(API_URL)/_test/reset?mode=clean' -H 'X-Test-Reset-Token: $(TEST_RESET_TOKEN)' && echo

bru: ## bru run всей Bruno-коллекции docs/api-collection (сначала reset clean)
	@API_URL='$(API_URL)' TEST_RESET_TOKEN='$(TEST_RESET_TOKEN)' DATABASE_URL='$(TEST_DATABASE_URL)' \
		APP_SECRET_KEY='$(APP_SECRET_KEY)' scripts/bru_run.sh

## --- Ещё не реализовано: цели падают, чтобы не создавать видимость работы ---

llm-check: ## Проверка LLM-провайдера (#8)
	@echo "make llm-check: не реализовано, см. #8" >&2; exit 1

llm-record: ## Запись ответов LLM для replay (#8)
	@echo "make llm-record: не реализовано, см. #8" >&2; exit 1

eval-intent: ## Eval распознавания потребности (#8)
	@echo "make eval-intent: не реализовано, см. #8" >&2; exit 1

eval-injection: ## Prompt-injection кейсы (#8)
	@echo "make eval-injection: не реализовано, см. #8" >&2; exit 1

e2e: ## Playwright E2E (#10)
	@echo "make e2e: не реализовано, см. #10" >&2; exit 1

load: ## Нагрузочный тест locust (#5)
	@echo "make load: не реализовано, см. #5" >&2; exit 1
