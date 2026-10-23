#!/bin/sh
# Старт api: миграции → базовый seed (идемпотентный) → uvicorn.
set -eu
alembic upgrade head
python -m app.seed
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
