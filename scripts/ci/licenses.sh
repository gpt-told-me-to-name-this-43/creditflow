#!/usr/bin/env bash
# docs/licenses/{api,ext-sim,web}.csv и THIRD_PARTY_NOTICES.md (#5): только runtime-зависимости.
# Python — pip-licenses по окружению `uv sync --no-dev`; web — license-checker по
# установке `--prod` с плоским node_modules (в обычном pnpm он видит только прямые
# зависимости). Установки — во временном каталоге, рабочие .venv и node_modules не трогаются.
set -euo pipefail

PIP_LICENSES="pip-licenses==5.5.5"
LICENSE_CHECKER="license-checker@25.0.1"

root=$(git rev-parse --show-toplevel)
out="$root/docs/licenses"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$out"

for svc in api ext-sim; do
  (cd "$root/$svc" && UV_PROJECT_ENVIRONMENT="$tmp/$svc" uv sync --locked --no-dev --quiet)
  uvx --quiet --from "$PIP_LICENSES" pip-licenses --python "$tmp/$svc/bin/python" \
    --from=mixed --format=csv --with-urls --order=name > "$out/$svc.csv"
done

mkdir "$tmp/web"
cp "$root/web/package.json" "$root/web/pnpm-lock.yaml" "$root/web/pnpm-workspace.yaml" "$tmp/web/"
(
  cd "$tmp/web"
  pnpm install --frozen-lockfile --prod --ignore-scripts --config.node-linker=hoisted --silent
  pnpm dlx "$LICENSE_CHECKER" --production --excludePrivatePackages --csv --out raw.csv >/dev/null
)
# Платформенные бинарные пакеты (`…-linux-x64-gnu`, `…-darwin-arm64`) ставятся только для
# текущей ОС: без фильтра CSV зависел бы от машины. Лицензия у них та же, что у основного.
grep -vE '^"[^"]*-(linux|darwin|win32|freebsd|android|openbsd|sunos)-[^"@]*@' "$tmp/web/raw.csv" \
  > "$out/web.csv"

python3 "$root/scripts/ci/licenses.py" notices "$out/api.csv" "$out/ext-sim.csv" "$out/web.csv" \
  > "$root/THIRD_PARTY_NOTICES.md"
