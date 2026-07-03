param(
    [string]$QueueNames = "",
    [int]$Concurrency = 0,
    [string]$WorkerName = ""
)

$ErrorActionPreference = "Stop"

function Invoke-Python {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Args
    )

    if (Get-Command python -ErrorAction SilentlyContinue) {
        & python @Args
        return
    }

    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 @Args
        return
    }

    throw "未找到 python/py，请先安装 Python 3.12。"
}

function Ensure-BackendDependencies {
    param([string]$BackendDir)

    $installDeps = ($env:BACKEND_WORKER_INSTALL_DEPS -eq "true")
    if (-not $installDeps) {
        try {
            Invoke-Python -c "import celery, fastapi" | Out-Null
            return
        } catch {
            $installDeps = $true
        }
    }

    if ($installDeps) {
        $installer = [System.IO.Path]::GetFullPath((Join-Path $BackendDir "..\..\Env\Python312\install-backend-deps.ps1"))
        & $installer -BackendDir $BackendDir
    }
}

function Test-RedisBrokerReachable {
    param([string]$BrokerUrl)

    if ([string]::IsNullOrWhiteSpace($BrokerUrl) -or -not $BrokerUrl.StartsWith("redis://")) {
        return
    }

    $uri = [System.Uri]$BrokerUrl
    $hostName = $uri.Host
    $port = if ($uri.Port -gt 0) { $uri.Port } else { 6379 }

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connectTask = $client.ConnectAsync($hostName, $port)
        if (-not $connectTask.Wait(1500)) {
            throw "连接 Redis broker 超时：$BrokerUrl"
        }
    } catch {
        throw "无法连接 Redis broker：$BrokerUrl。请先启动 Redis，或改用 .\Env\backend\dev.ps1 走 sync 模式。"
    } finally {
        $client.Dispose()
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptDir "dev.env.ps1")

$backendDir = [System.IO.Path]::GetFullPath((Join-Path $scriptDir "..\..\Code\backend"))
$activateScript = Join-Path $backendDir ".venv\Scripts\Activate.ps1"
if (Test-Path $activateScript) {
    . $activateScript
}

Ensure-BackendDependencies -BackendDir $backendDir

$resolvedQueues = if ($QueueNames) { $QueueNames } else { $env:BACKEND_WORKER_ANALYSIS_QUEUES }
$resolvedConcurrency = if ($Concurrency -gt 0) { $Concurrency } else { [int]$env:BACKEND_WORKER_ANALYSIS_CONCURRENCY }
$resolvedWorkerName = if ($WorkerName) { $WorkerName } else { $env:BACKEND_WORKER_ANALYSIS_NAME }
$resolvedPool = if (-not [string]::IsNullOrWhiteSpace($env:BACKEND_WORKER_POOL)) {
    $env:BACKEND_WORKER_POOL
} elseif ($IsWindows) {
    "solo"
} else {
    ""
}

if ($resolvedPool -eq "solo" -and $resolvedConcurrency -gt 1) {
    Write-Host "[backend] worker pool=solo，自动将并发度调整为 1"
    $resolvedConcurrency = 1
}

$celeryArgs = @(
    "-m",
    "celery",
    "-A",
    "app.core.celery_app.celery_app",
    "worker",
    "-l",
    "info",
    "-Q",
    $resolvedQueues,
    "--concurrency",
    $resolvedConcurrency.ToString(),
    "-n",
    $resolvedWorkerName
)
if (-not [string]::IsNullOrWhiteSpace($resolvedPool)) {
    $celeryArgs += @("--pool", $resolvedPool)
}

Push-Location $backendDir
try {
    Test-RedisBrokerReachable -BrokerUrl $env:BACKEND_CELERY_BROKER_URL
    Invoke-Python @celeryArgs
}
finally {
    Pop-Location
}
