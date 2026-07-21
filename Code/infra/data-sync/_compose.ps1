# Cross-platform helper for data-sync compose (Windows PowerShell).
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root
if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  Write-Host "Created .env from .env.example"
}
# Ensure shared volume exists (created by backend compose, or create empty).
$vol = "backend_open-meteo-data"
if (Test-Path ".env") {
  $line = Get-Content ".env" | Where-Object { $_ -match '^\s*OPEN_METEO_DATA_VOLUME\s*=' } | Select-Object -First 1
  if ($line) { $vol = ($line -split '=', 2)[1].Trim() }
}
docker volume inspect $vol 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Creating named volume $vol (API should normally create this via backend compose)"
  docker volume create $vol | Out-Null
}
docker compose -p data-sync --env-file .env @args
