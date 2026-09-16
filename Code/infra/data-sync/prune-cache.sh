#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
CACHE="$ROOT/../../backend/.data/cache/weatherengine"
if [[ -d "$CACHE" ]]; then
  rm -rf "$CACHE"
  echo "Removed $CACHE"
else
  echo "No cache at $CACHE"
fi
echo "Open-Meteo named volume untouched. Wipe sync data: docker volume rm backend_open-meteo-data"
