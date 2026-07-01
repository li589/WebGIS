$ErrorActionPreference = "Stop"

$LocalConfig = Join-Path $PSScriptRoot "dev.env.ps1"

$QueueNames = "realtime,standard,heavy,batch"
$Concurrency = 1
$WorkerName = "analysis-worker"

if (Test-Path $LocalConfig) {
    . $LocalConfig
}

if (-not [string]::IsNullOrWhiteSpace($env:BACKEND_WORKER_ANALYSIS_QUEUES)) {
    $QueueNames = $env:BACKEND_WORKER_ANALYSIS_QUEUES
}
if (-not [string]::IsNullOrWhiteSpace($env:BACKEND_WORKER_ANALYSIS_CONCURRENCY)) {
    $Concurrency = [int]$env:BACKEND_WORKER_ANALYSIS_CONCURRENCY
}
if (-not [string]::IsNullOrWhiteSpace($env:BACKEND_WORKER_ANALYSIS_NAME)) {
    $WorkerName = $env:BACKEND_WORKER_ANALYSIS_NAME
}

$WorkerScript = Join-Path $PSScriptRoot "worker.ps1"
if (-not (Test-Path $WorkerScript)) {
    throw "Worker script not found: $WorkerScript"
}

& $WorkerScript -QueueNames $QueueNames -Concurrency $Concurrency -WorkerName $WorkerName
