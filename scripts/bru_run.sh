#!/usr/bin/env bash
# bru run всей коллекции docs/api-collection (issue #7).
#
# 1) POST /_test/reset?mode=clean — чистая БД с базовым seed;
# 2) токены демо-учёток и привязка компаний — scripts/dev_token.py (до #5 вход — стаб);
# 3) bru run --env local с токенами в --env-var.
#
# Переменные: API_URL (по умолчанию http://localhost:8080/api/v1), TEST_RESET_TOKEN,
# DATABASE_URL и APP_SECRET_KEY — те же, что у api. `make bru` берёт их из .env.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API_URL="${API_URL:-http://localhost:8080/api/v1}"
BRU_VERSION="2.15.1"

curl -fsS -X POST "$API_URL/_test/reset?mode=clean" -H "X-Test-Reset-Token: ${TEST_RESET_TOKEN:?нужен TEST_RESET_TOKEN}" >/dev/null

token() {
  (cd "$ROOT/api" && uv run --quiet python ../scripts/dev_token.py "$@")
}

args=(--env local --env-var "baseUrl=$API_URL")
args+=(--env-var "c1Token=$(token director.techservice@creditflow.demo --bind 0099010012)")
args+=(--env-var "c2Token=$(token director.bakery@creditflow.demo --bind 0099020010)")
args+=(--env-var "c3Token=$(token ip.sokolova@creditflow.demo --bind 009903001040)")
args+=(--env-var "c4Token=$(token director.newstart@creditflow.demo --bind 0099040017)")
args+=(--env-var "c5Token=$(token director.vector@creditflow.demo --bind 0099050015)")
args+=(--env-var "c6Token=$(token director.sklad@creditflow.demo --bind 0099060013)")
args+=(--env-var "c7Token=$(token ip.orlov@creditflow.demo --bind 009907001027)")
# T1 (сбой БКИ) — только для теста отказа провайдера; учётка бухгалтера, у неё своей компании нет
args+=(--env-var "t1Token=$(token accountant.bakery@creditflow.demo --bind 0099990019)")
args+=(--env-var "managerToken=$(token manager.anna@creditflow.demo)")

cd "$ROOT/docs/api-collection"
npx --yes "@usebruno/cli@$BRU_VERSION" run "${args[@]}" "$@"
