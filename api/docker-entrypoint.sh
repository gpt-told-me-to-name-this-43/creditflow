#!/bin/sh
# РЎС‚Р°СЂС‚ api: РјРёРіСЂР°С†РёРё в†’ Р±Р°Р·РѕРІС‹Р№ seed (РёРґРµРјРїРѕС‚РµРЅС‚РЅС‹Р№) в†’ uvicorn.
set -eu
alembic upgrade head
python -m app.seed
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
