param()

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptDir "dev.env.ps1")

if ([string]::IsNullOrWhiteSpace($env:BACKEND_MINIO_ENDPOINT)) {
    throw "BACKEND_MINIO_ENDPOINT 未设置。"
}

$scheme = if ($env:BACKEND_MINIO_SECURE -eq "true") { "https" } else { "http" }
$url = "{0}://{1}/minio/health/live" -f $scheme, $env:BACKEND_MINIO_ENDPOINT

try {
    $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
    Write-Host "[minio] healthy: $url (status=$($response.StatusCode))"
} catch {
    throw "MinIO 连通性检查失败: $url`n$($_.Exception.Message)"
}
