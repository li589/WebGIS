$ErrorActionPreference = "Stop"

$LocalConfig = Join-Path $PSScriptRoot "dev.env.ps1"

$QueueNames = "download-realtime,download-standard"
$Concurrency = 1
$WorkerName = "download-worker"

if (Test-Path $LocalConfig) {
    . $LocalConfig
}

if (-not [string]::IsNullOrWhiteSpace($env:BACKEND_WORKER_DOWNLOAD_QUEUES)) {
    $QueueNames = $env:BACKEND_WORKER_DOWNLOAD_QUEUES
}
if (-not [string]::IsNullOrWhiteSpace($env:BACKEND_WORKER_DOWNLOAD_CONCURRENCY)) {
    $Concurrency = [int]$env:BACKEND_WORKER_DOWNLOAD_CONCURRENCY
}
if (-not [string]::IsNullOrWhiteSpace($env:BACKEND_WORKER_DOWNLOAD_NAME)) {
    $WorkerName = $env:BACKEND_WORKER_DOWNLOAD_NAME
}

$WorkerScript = Join-Path $PSScriptRoot "worker.ps1"
if (-not (Test-Path $WorkerScript)) {
    throw "Worker script not found: $WorkerScript"
}

& $WorkerScript -QueueNames $QueueNames -Concurrency $Concurrency -WorkerName $WorkerName
