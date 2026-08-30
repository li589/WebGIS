#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

$caddy = Join-Path $here "caddy.exe"
if (-not (Test-Path $caddy)) {
    Write-Host @"
未找到 caddy.exe。

1. 打开 https://caddyserver.com/download 下载 Windows amd64
2. 将 caddy.exe 放到本目录：
   $here
3. 再重新运行本脚本

"@
    exit 1
}

Write-Host "Starting Caddy reverse proxy on http://127.0.0.1:8000 -> https://api.cgdas.dpdns.org"
Write-Host "Test: http://localhost:8000/health   (Ctrl+C to stop)"
& $caddy run --config (Join-Path $here "Caddyfile")
