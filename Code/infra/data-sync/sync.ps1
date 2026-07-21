param(
  [Parameter(Position = 0)]
  [string]$Job = "open-meteo-sync"
)
$ErrorActionPreference = "Stop"
& "$PSScriptRoot\_compose.ps1" --profile sync run --rm $Job
