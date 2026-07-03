param(
    [string]$RedisExe = "",
    [int]$Port = 6379,
    [string]$DataDir = ""
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptDir "..\..\"))
$defaultDataDir = Join-Path $repoRoot "Code\backend\.data\redis"
$resolvedDataDir = if ($DataDir) {
    [System.IO.Path]::GetFullPath($DataDir)
} else {
    $defaultDataDir
}

if (-not (Test-Path $resolvedDataDir)) {
    New-Item -ItemType Directory -Path $resolvedDataDir -Force | Out-Null
}

function Resolve-RedisCommand {
    param([string[]]$Candidates)

    foreach ($candidate in $Candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) {
            continue
        }
        if (Test-Path $candidate) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }
    return $null
}

function Resolve-RedisConfig {
    param([string[]]$Candidates)

    foreach ($candidate in $Candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) {
            continue
        }
        if (Test-Path $candidate) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }
    return $null
}

if ($IsWindows) {
    $serviceCandidates = @()
    $serverCandidates = @()
    $configCandidates = @(
        (Join-Path $repoRoot "Env\Redis\Redis-Windows\redis.conf"),
        (Join-Path $repoRoot "Env\Redis\redis.conf")
    )
    if ($RedisExe) {
        $serviceCandidates += $RedisExe
        $serverCandidates += $RedisExe
    }
    $serviceCandidates += (Join-Path $repoRoot "Env\Redis\Redis-Windows\RedisService.exe")
    $serviceCandidates += (Join-Path $repoRoot "Env\Redis\RedisService.exe")
    $serverCandidates += (Join-Path $repoRoot "Env\Redis\Redis-Windows\redis-server.exe")
    $serverCandidates += (Join-Path $repoRoot "Env\Redis\redis-server.exe")
    $serviceCandidates += "RedisService.exe"
    $serverCandidates += "redis-server"

    $serviceExe = Resolve-RedisCommand -Candidates $serviceCandidates
    $configFile = Resolve-RedisConfig -Candidates $configCandidates
    if ($serviceExe) {
        Write-Host "[redis] starting RedisService on port $Port"
        if ($configFile) {
            & $serviceExe run --foreground -c $configFile --port $Port --dir $resolvedDataDir
        } else {
            & $serviceExe run --foreground --port $Port --dir $resolvedDataDir
        }
        exit $LASTEXITCODE
    }

    $serverExe = Resolve-RedisCommand -Candidates $serverCandidates
    if ($serverExe) {
        Write-Host "[redis] starting redis-server on port $Port"
        & $serverExe --port $Port --dir $resolvedDataDir
        exit $LASTEXITCODE
    }

    throw "未找到 Redis for Windows。请将 Redis 放到 Env\Redis\Redis-Windows\ 下，或加入 PATH。"
}

$linuxCandidates = @()
if ($RedisExe) {
    $linuxCandidates += $RedisExe
}
$linuxCandidates += (Join-Path $repoRoot "Env/Redis/Redis-Linux/redis-server")
$linuxCandidates += (Join-Path $repoRoot "Env/Redis/redis-server")
$linuxCandidates += "redis-server"

$linuxExe = Resolve-RedisCommand -Candidates $linuxCandidates
if ($linuxExe) {
    Write-Host "[redis] starting redis-server on port $Port"
    & $linuxExe --port $Port --dir $resolvedDataDir
    exit $LASTEXITCODE
}

throw "未找到 Redis。Windows 下请放到 Env\Redis\Redis-Windows\，Linux 下请放到 Env/Redis/Redis-Linux/，或加入 PATH。"
