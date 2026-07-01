$ErrorActionPreference = "Stop"

$RedisServerExe = $env:REDIS_SERVER_EXE
$RedisPort = "6379"

if ([string]::IsNullOrWhiteSpace($RedisServerExe)) {
    $Candidate = Join-Path (Split-Path -Parent $PSScriptRoot) "Redis\redis-server.exe"
    if (Test-Path $Candidate) {
        $RedisServerExe = $Candidate
    }
}

if ([string]::IsNullOrWhiteSpace($RedisServerExe)) {
    $RedisServerExe = "redis-server"
}

Write-Host "Starting Redis server..."
Write-Host "Command: $RedisServerExe"
Write-Host "Port: $RedisPort"

& $RedisServerExe --port $RedisPort

if ($LASTEXITCODE -ne 0) {
    throw "Redis startup failed. Set REDIS_SERVER_EXE or place redis-server.exe under Env\\Redis\\."
}
