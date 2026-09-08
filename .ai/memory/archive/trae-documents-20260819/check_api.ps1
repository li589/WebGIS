# Check health and public endpoints
Write-Host "=== Health Check ===" -ForegroundColor Cyan
try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 10
    Write-Host "Health: $($r.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "Health Error: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n=== Config About ===" -ForegroundColor Cyan
try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/config/about' -UseBasicParsing -TimeoutSec 10
    Write-Host "About: $($r.StatusCode)" -ForegroundColor Green
    $json = $r.Content | ConvertFrom-Json
    Write-Host "Environment: $($json.environment)"
    Write-Host "API Keys Enabled: $($json.api_keys_enabled)"
    Write-Host "Demo Sources: $($json.demo_sources_enabled)"
} catch {
    Write-Host "About Error: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n=== Workflow Definitions (no auth) ===" -ForegroundColor Cyan
$workflows = @('fy_tb_online_read', 'ndvi_online_read', 'ndvi_gee_read', 'fy_tb_nas_read', 'fy_tb_nsmc_online')
foreach ($wf in $workflows) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/workflow-definitions/$wf" -UseBasicParsing -TimeoutSec 10
        Write-Host "[$wf] OK: $($r.StatusCode)" -ForegroundColor Green
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        Write-Host "[$wf] HTTP $code" -ForegroundColor Yellow
    }
}
