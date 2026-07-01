$ErrorActionPreference = "Stop"

$LocalConfig = Join-Path $PSScriptRoot "dev.env.ps1"
$PythonHome = Join-Path (Split-Path -Parent $PSScriptRoot) "Python312"
$ActivateScript = Join-Path $PythonHome "activate-project-venv.ps1"
$InstallDepsScript = Join-Path $PythonHome "install-backend-deps.ps1"
$CommonScript = Join-Path (Split-Path -Parent $PSScriptRoot) "common\project-paths.ps1"

$BackendHost = "127.0.0.1"
$BackendPort = "8000"
$BackendReload = $true
$RedisUrl = "redis://127.0.0.1:6379/0"

if (-not (Test-Path $CommonScript)) {
    throw "Project path resolver not found: $CommonScript"
}

. $CommonScript

if (Test-Path $LocalConfig) {
    . $LocalConfig
}

if (-not (Test-Path $BackendDir)) {
    throw "Backend directory not found: $BackendDir"
}

. $InstallDepsScript
. $ActivateScript

Push-Location $BackendDir

try {
    $env:PROJECT_ROOT = $ProjectRoot
    $env:PROJECT_CODE_DIR = $CodeRoot
    $env:PROJECT_BACKEND_DIR = $BackendDir
    $env:PROJECT_ALGORITHMS_DIR = $AlgorithmsDir
    $env:PROJECT_SHARED_DIR = $SharedDir
    $env:BACKEND_HOST = $BackendHost
    $env:BACKEND_PORT = $BackendPort
    $env:BACKEND_RELOAD = $BackendReload.ToString().ToLower()
    $env:BACKEND_WORKFLOW_EXECUTOR = "celery"
    $env:BACKEND_REDIS_URL = $RedisUrl
    $env:BACKEND_CELERY_BROKER_URL = $RedisUrl
    $env:BACKEND_CELERY_RESULT_BACKEND = $RedisUrl

    Write-Host "Starting backend dev environment with Celery..."
    Write-Host "Directory: $BackendDir"
    Write-Host "URL: http://$BackendHost`:$BackendPort/"
    Write-Host "Redis: $RedisUrl"

    python -m uvicorn app.main:app --host $BackendHost --port $BackendPort --reload
    if ($LASTEXITCODE -ne 0) {
        throw "uvicorn startup failed."
    }
}
finally {
    Pop-Location
}
