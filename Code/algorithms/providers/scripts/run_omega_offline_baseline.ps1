param(
    [ValidateSet("quick", "formal96", "formal192", "dual96", "cprofile96", "all")]
    [string[]]$Profiles = @("all"),
    [string]$PythonExe = "python",
    [string]$OutputRoot = "",
    [int]$Nt = 64,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-ProjectRoot {
    if ($PSScriptRoot) {
        return (Split-Path -Parent $PSScriptRoot)
    }
    return (Get-Location).Path
}

function New-ProfileSpec {
    param(
        [string]$Name,
        [string[]]$Arguments
    )
    return [pscustomobject]@{
        Name = $Name
        Arguments = $Arguments
    }
}

$projectRoot = Resolve-ProjectRoot
$pythonDir = Join-Path $projectRoot "Python"
if (-not (Test-Path $pythonDir)) {
    throw "Python directory not found: $pythonDir"
}

if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $projectRoot "tmp\omega_offline_baseline"
}
elseif (-not [System.IO.Path]::IsPathRooted($OutputRoot)) {
    $OutputRoot = Join-Path $projectRoot $OutputRoot
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runRoot = Join-Path $OutputRoot $timestamp
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null

$specs = @(
    (New-ProfileSpec -Name "quick" -Arguments @("--nt", "$Nt", "--npix", "48", "--repeats", "1", "--pixel-repeats", "1", "--pixel-samples", "6", "--trial-count", "3", "--warmup", "1", "--exp-mode", "Exp2")),
    (New-ProfileSpec -Name "formal96" -Arguments @("--nt", "$Nt", "--npix", "96", "--repeats", "1", "--pixel-repeats", "1", "--pixel-samples", "8", "--trial-count", "7", "--warmup", "2", "--exp-mode", "Exp2")),
    (New-ProfileSpec -Name "formal192" -Arguments @("--nt", "$Nt", "--npix", "192", "--repeats", "1", "--pixel-repeats", "1", "--pixel-samples", "8", "--trial-count", "5", "--warmup", "2", "--exp-mode", "Exp2")),
    (New-ProfileSpec -Name "dual96" -Arguments @("--nt", "$Nt", "--npix", "96", "--repeats", "1", "--pixel-repeats", "1", "--pixel-samples", "8", "--trial-count", "5", "--warmup", "2", "--exp-mode", "Exp2", "--temp-scheme", "DUAL")),
    (New-ProfileSpec -Name "cprofile96" -Arguments @("--nt", "$Nt", "--npix", "96", "--repeats", "1", "--pixel-repeats", "1", "--pixel-samples", "2", "--trial-count", "1", "--warmup", "0", "--exp-mode", "Exp2", "--cprofile", "--cprofile-top", "30"))
)

if ($Profiles -contains "all") {
    $selectedSpecs = $specs
}
else {
    $selectedSpecs = foreach ($profileName in $Profiles) {
        $match = $specs | Where-Object { $_.Name -eq $profileName } | Select-Object -First 1
        if ($null -eq $match) {
            throw "Unknown profile: $profileName"
        }
        $match
    }
}

$manifestPath = Join-Path $runRoot "run_manifest.txt"
@(
    "project_root=$projectRoot"
    "python_dir=$pythonDir"
    "python_exe=$PythonExe"
    "profiles=$($selectedSpecs.Name -join ',')"
    "timestamp=$timestamp"
) | Set-Content -Path $manifestPath -Encoding ascii

Write-Host "OMEGA offline baseline output: $runRoot"

if ($DryRun) {
    foreach ($spec in $selectedSpecs) {
        $cmdText = @("debug_omega_profile.py") + $spec.Arguments
        $cmdLine = "$PythonExe " + ($cmdText -join " ")
        Write-Host ("DRYRUN {0}: {1}" -f $spec.Name, $cmdLine)
    }
    Write-Host "Dry run completed. Manifest written to: $manifestPath"
    return
}

Push-Location $pythonDir
try {
    foreach ($spec in $selectedSpecs) {
        $logPath = Join-Path $runRoot ("{0}.log" -f $spec.Name)
        $cmdText = @("debug_omega_profile.py") + $spec.Arguments
        $cmdLine = "$PythonExe " + ($cmdText -join " ")

        Write-Host ""
        Write-Host ("=== Running {0} ===" -f $spec.Name)
        Write-Host $cmdLine

        "COMMAND: $cmdLine" | Set-Content -Path $logPath -Encoding ascii
        & $PythonExe @cmdText 2>&1 | Tee-Object -FilePath $logPath -Append
    }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Completed. Logs written to: $runRoot"
