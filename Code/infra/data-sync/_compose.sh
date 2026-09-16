#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi
vol=backend_open-meteo-data
if [[ -f .env ]]; then
  line="$(grep -E '^\s*OPEN_METEO_DATA_VOLUME\s*=' .env | head -n1 || true)"
  if [[ -n "$line" ]]; then
    vol="$(echo "$line" | cut -d= -f2- | tr -d '[:space:]')"
  fi
fi
if ! docker volume inspect "$vol" >/dev/null 2>&1; then
  echo "Creating named volume $vol (API should normally create this via backend compose)"
  docker volume create "$vol" >/dev/null
fi
exec docker compose -p data-sync --env-file .env "$@"
