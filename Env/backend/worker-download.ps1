param()

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptDir "dev.env.ps1")

$workerScript = Join-Path $scriptDir "worker.ps1"

& $workerScript `
    -QueueNames $env:BACKEND_WORKER_DOWNLOAD_QUEUES `
    -Concurrency ([int]$env:BACKEND_WORKER_DOWNLOAD_CONCURRENCY) `
    -WorkerName $env:BACKEND_WORKER_DOWNLOAD_NAME
