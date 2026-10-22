#!/usr/bin/env bash
# Ждёт, пока api после (пере)запуска:
#   1) отвечает через nginx на /api/v1/health ожидаемыми HTTP-кодом и status;
#   2) прошёл healthcheck Docker, начатый ПОСЛЕ текущего старта контейнера.
# Статус `healthy` сразу после `docker compose restart` остаётся от прошлого
# запуска, поэтому одному State.Health.Status верить нельзя.
#
# usage: scripts/ci/wait-api.sh <status: ok|degraded|unavailable> <http-code> [timeout-s]
set -euo pipefail

want_status=$1
want_code=$2
timeout=${3:-120}
url=http://localhost:8080/api/v1/health
id=$(docker compose ps -q api)

# Код выхода последней проверки healthcheck, начатой после старта контейнера; "none" — ещё не было.
last_probe() {
  docker inspect "$id" | jq -r '
    def epoch: sub("\\.[0-9]+"; "") | sub("\\+00:00$"; "Z") | fromdate;
    .[0].State as $s
    | [($s.Health.Log // [])[] | select((.Start | epoch) > ($s.StartedAt | epoch))]
    | if length == 0 then "none" else (last.ExitCode | tostring) end'
}

deadline=$((SECONDS + timeout))
code="" probe=""
while ((SECONDS < deadline)); do
  code=$(curl -s -o health.json -w '%{http_code}' "$url" || true)
  probe=$(last_probe)
  if [[ $code == "$want_code" && $probe == 0 ]] &&
    jq -e --arg s "$want_status" '.status == $s' health.json >/dev/null 2>&1; then
    echo "api: HTTP $code, healthcheck после старта: exit $probe"
    cat health.json
    echo
    exit 0
  fi
  sleep 2
done

echo "::error::api не дошёл до HTTP $want_code / status=$want_status за ${timeout}s (HTTP $code, healthcheck: $probe)"
cat health.json 2>/dev/null || true
echo
exit 1
