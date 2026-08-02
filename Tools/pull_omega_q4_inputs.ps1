# Pull FY/SMAP daily mats for 2025-11 (Q4 gap) via Cloudflare SSH tunnel.
# Usage: powershell -File Tools/pull_omega_q4_inputs.ps1
# Requires: cloudflared on :2222, key ~/.ssh/seahpc_key
$ErrorActionPreference = "Stop"
$Key = Join-Path $env:USERPROFILE ".ssh\seahpc_key"
$Ssh = @("-p", "2222", "-o", "BatchMode=yes", "-o", "ConnectTimeout=30", "-i", $Key, "likr6008@127.0.0.1")
$ScpBase = @("-P", "2222", "-o", "BatchMode=yes", "-o", "ConnectTimeout=60", "-i", $Key)

$Root = "I:\Geograph_DataSet\Soil_Moisture"
$Jobs = @(
    @{ Local = Join-Path $Root "SMAP_Origin_Data"; Remote = "/public/shared_data/Chenhaojun/DDCAfuxian/DDCAdata/SMAPdata/MAT"; Prefix = "202511" },
    @{ Local = Join-Path $Root "FY3D"; Remote = "/public/shared_data/Chenhaojun/FY3D_output/matfinalfinal"; Prefix = "202511" }
)

function Get-RemoteList([string]$remoteDir, [string]$prefix) {
    $cmd = "ls -1 $remoteDir/${prefix}*.mat 2>/dev/null | xargs -n1 basename"
    & ssh @Ssh $cmd
}

$manifest = @()
foreach ($job in $Jobs) {
    New-Item -ItemType Directory -Force -Path $job.Local | Out-Null
    $names = Get-RemoteList $job.Remote $job.Prefix
    foreach ($name in $names) {
        if (-not $name) { continue }
        $localPath = Join-Path $job.Local $name
        $status = "skip_exists"
        if (-not (Test-Path $localPath)) {
            Write-Host "[PULL] $($job.Local) <= $name"
            & scp @ScpBase "likr6008@127.0.0.1:$($job.Remote)/$name" $localPath
            if ($LASTEXITCODE -ne 0) {
                $status = "fail"
                Write-Host "[FAIL] $name"
            } else {
                $status = "ok"
            }
        }
        $manifest += [pscustomobject]@{ product = Split-Path $job.Local -Leaf; file = $name; status = $status; bytes = if (Test-Path $localPath) { (Get-Item $localPath).Length } else { 0 } }
    }
}

$out = Join-Path $PSScriptRoot "pull_omega_q4_manifest.csv"
$manifest | Export-Csv -NoTypeInformation -Path $out -Encoding UTF8
Write-Host "[DONE] manifest -> $out"
$manifest | Group-Object status | ForEach-Object { Write-Host ("{0}: {1}" -f $_.Name, $_.Count) }
