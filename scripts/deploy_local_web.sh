#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="$root_dir/docker-compose.web.yml"
project_name="${TRADINGAGENTS_WEB_PROJECT:-trading-agents-web-local}"
port="${TRADINGAGENTS_WEB_PORT:-8080}"

if [[ ! "$port" =~ ^[0-9]+$ ]] || (( port < 1 || port > 65535 )); then
  printf 'TRADINGAGENTS_WEB_PORT must be an integer between 1 and 65535\n' >&2
  exit 2
fi
if ! command -v docker >/dev/null 2>&1; then
  printf 'Docker is required for local web deployment\n' >&2
  exit 3
fi
if ! command -v curl >/dev/null 2>&1; then
  printf 'curl is required to verify local web deployment\n' >&2
  exit 3
fi

if docker compose version >/dev/null 2>&1; then
  compose=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  compose=(docker-compose)
else
  printf 'Docker Compose is required for local web deployment\n' >&2
  exit 3
fi

export TRADINGAGENTS_WEB_PORT="$port"
"${compose[@]}" \
  --project-name "$project_name" \
  --file "$compose_file" \
  up --build --detach web

base_url="http://127.0.0.1:$port"
curl --fail --silent --show-error \
  --retry 20 --retry-delay 1 --retry-connrefused \
  "$base_url/healthz" >/dev/null

actual_page="$(curl --fail --silent --show-error "$base_url/")"
expected_page="$(<"$root_dir/web/index.html")"
if [[ "$actual_page" != "$expected_page" ]]; then
  printf 'deployed web page does not match web/index.html\n' >&2
  exit 4
fi

printf 'local web deployment is ready at %s/\n' "$base_url"
