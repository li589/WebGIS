#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

$repoRoot = Resolve-Path (Join-Path $here "..\..")
$envPy = Join-Path $repoRoot "Env\Python312\python.exe"

$python = $null
if (Test-Path $envPy) {
    $python = $envPy
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $python = (Get-Command python).Source
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $python = "py"
} else {
    Write-Host "未找到 Python。请使用仓库 Env\Python312\python.exe，或安装 Python 3。"
    exit 1
}

if (-not $env:CGDA_PROXY_TARGET) {
    $env:CGDA_PROXY_TARGET = "https://api.cgdas.dpdns.org"
}
if (-not $env:CGDA_PROXY_PORT) {
    $env:CGDA_PROXY_PORT = "8000"
}

Write-Host "Using: $python"
Write-Host "Starting Python proxy on http://127.0.0.1:$($env:CGDA_PROXY_PORT) -> $($env:CGDA_PROXY_TARGET)"
Write-Host "Test: http://localhost:$($env:CGDA_PROXY_PORT)/health   (Ctrl+C to stop)"
& $python (Join-Path $here "api_proxy.py")
