param()

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

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptDir "dev.env.ps1")

$backendDir = [System.IO.Path]::GetFullPath((Join-Path $scriptDir "..\..\Code\backend"))
$activateScript = Join-Path $backendDir ".venv\Scripts\Activate.ps1"
if (Test-Path $activateScript) {
    . $activateScript
}

$env:BACKEND_WORKFLOW_EXECUTOR = "sync"

Push-Location $backendDir
try {
    $uvicornArgs = @(
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        $env:BACKEND_HOST,
        "--port",
        $env:BACKEND_PORT
    )
    if ($env:BACKEND_RELOAD -eq "true") {
        $uvicornArgs += "--reload"
    }
    Invoke-Python @uvicornArgs
}
finally {
    Pop-Location
}
