#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
JOB="${1:-open-meteo-sync}"
exec "$ROOT/_compose.sh" --profile sync run --rm "$JOB"
