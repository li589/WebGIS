$ErrorActionPreference = "Stop"

$LocalConfig = Join-Path $PSScriptRoot "dev.env.ps1"
$PythonHome = Join-Path (Split-Path -Parent $PSScriptRoot) "Python312"
$ActivateScript = Join-Path $PythonHome "activate-project-venv.ps1"
$InstallDepsScript = Join-Path $PythonHome "install-backend-deps.ps1"
$CommonScript = Join-Path (Split-Path -Parent $PSScriptRoot) "common\project-paths.ps1"

$BackendHost = "127.0.0.1"
$BackendPort = "8000"
$BackendReload = $true

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
    $env:BACKEND_HOST = $BackendHost
    $env:BACKEND_PORT = $BackendPort
    $env:BACKEND_RELOAD = $BackendReload.ToString().ToLower()

    Write-Host "Starting backend dev environment..."
    Write-Host "Directory: $BackendDir"
    Write-Host "URL: http://$BackendHost`:$BackendPort/"

    python -m uvicorn app.main:app --host $BackendHost --port $BackendPort --reload
    if ($LASTEXITCODE -ne 0) {
        throw "uvicorn startup failed."
    }
}
finally {
    Pop-Location
}
