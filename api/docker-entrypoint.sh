#!/bin/sh
# Старт api: миграции → базовый seed (идемпотентный) → uvicorn.
# --no-proxy-headers: IP клиента для лимитов определяет api (X-Real-IP от доверенного
# прокси, app/core/security.py), а не X-Forwarded-For от любого отправителя.
# --no-access-log: access-лог в JSON пишет RequestContextMiddleware.
set -eu
alembic upgrade head
python -m app.seed
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers --no-access-log
