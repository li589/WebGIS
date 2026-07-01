param(
    [string]$QueueNames = "",
    [int]$Concurrency = 1,
    [string]$WorkerName = "backend-worker"
)

$ErrorActionPreference = "Stop"

$LocalConfig = Join-Path $PSScriptRoot "dev.env.ps1"
$PythonHome = Join-Path (Split-Path -Parent $PSScriptRoot) "Python312"
$ActivateScript = Join-Path $PythonHome "activate-project-venv.ps1"
$InstallDepsScript = Join-Path $PythonHome "install-backend-deps.ps1"
$CommonScript = Join-Path (Split-Path -Parent $PSScriptRoot) "common\project-paths.ps1"

$CeleryLogLevel = "info"
$RedisUrl = "redis://127.0.0.1:6379/0"
$InstallDependencies = $false

if (-not (Test-Path $CommonScript)) {
    throw "Project path resolver not found: $CommonScript"
}

. $CommonScript

if (Test-Path $LocalConfig) {
    . $LocalConfig
}

if (-not [string]::IsNullOrWhiteSpace($env:BACKEND_WORKER_INSTALL_DEPS)) {
    $InstallDependencies = $env:BACKEND_WORKER_INSTALL_DEPS.ToLower() -eq "true"
}

if (-not (Test-Path $BackendDir)) {
    throw "Backend directory not found: $BackendDir"
}

. $ActivateScript

if (-not $InstallDependencies) {
    # Keep worker startup fast when the venv is already ready, but auto-heal if key deps are missing.
    python -c "import fastapi, celery, redis, minio" *> $null
    if ($LASTEXITCODE -ne 0) {
        $InstallDependencies = $true
        Write-Host "Worker dependencies are missing. Installing backend dependencies before startup..."
    }
}

if ($InstallDependencies) {
    . $InstallDepsScript
    . $ActivateScript
}

Push-Location $BackendDir

try {
    $env:PROJECT_ROOT = $ProjectRoot
    $env:PROJECT_CODE_DIR = $CodeRoot
    $env:PROJECT_BACKEND_DIR = $BackendDir
    $env:PROJECT_ALGORITHMS_DIR = $AlgorithmsDir
    $env:PROJECT_SHARED_DIR = $SharedDir
    $env:BACKEND_WORKFLOW_EXECUTOR = "celery"
    $env:BACKEND_REDIS_URL = $RedisUrl
    $env:BACKEND_CELERY_BROKER_URL = $RedisUrl
    $env:BACKEND_CELERY_RESULT_BACKEND = $RedisUrl

    Write-Host "Starting Celery worker..."
    Write-Host "Directory: $BackendDir"
    Write-Host "Redis: $RedisUrl"
    if (-not [string]::IsNullOrWhiteSpace($QueueNames)) {
        Write-Host "Queues: $QueueNames"
    }
    Write-Host "Concurrency: $Concurrency"
    Write-Host "Worker name: $WorkerName"
    Write-Host "Install deps: $InstallDependencies"

    $Arguments = @(
        "-m", "celery",
        "-A", "app.core.celery_app:celery_app",
        "worker",
        "--loglevel", $CeleryLogLevel,
        "--pool", "solo",
        "--concurrency", $Concurrency,
        "--hostname", "$WorkerName@%h"
    )
    if (-not [string]::IsNullOrWhiteSpace($QueueNames)) {
        $Arguments += @("--queues", $QueueNames)
    }

    python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "celery worker startup failed."
    }
}
finally {
    Pop-Location
}
