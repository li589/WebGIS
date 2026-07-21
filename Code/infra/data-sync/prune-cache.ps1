# Prune app-side weather tile/JSON cache only (not Open-Meteo Docker volume).
$ErrorActionPreference = "Stop"
$Cache = Join-Path $PSScriptRoot "..\..\backend\.data\cache\weatherengine"
if (Test-Path $Cache) {
  Remove-Item -Recurse -Force $Cache
  Write-Host "Removed $Cache"
} else {
  Write-Host "No cache at $Cache"
}
Write-Host "Open-Meteo named volume untouched. Wipe sync data: docker volume rm backend_open-meteo-data"
