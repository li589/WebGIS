#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "未找到 node。请先安装 Node.js：https://nodejs.org/"
    exit 1
}

if (-not $env:CGDA_PROXY_TARGET) {
    $env:CGDA_PROXY_TARGET = "https://api.cgdas.dpdns.org"
}
if (-not $env:CGDA_PROXY_PORT) {
    $env:CGDA_PROXY_PORT = "8000"
}

Write-Host "Starting Node proxy on http://127.0.0.1:$($env:CGDA_PROXY_PORT) -> $($env:CGDA_PROXY_TARGET)"
Write-Host "Test: http://localhost:$($env:CGDA_PROXY_PORT)/health   (Ctrl+C to stop)"
node (Join-Path $here "api-proxy.mjs")
