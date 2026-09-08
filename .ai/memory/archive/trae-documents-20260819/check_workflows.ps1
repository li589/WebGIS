$workflows = @('fy_tb_online_read', 'ndvi_online_read', 'ndvi_gee_read', 'fy_tb_nas_read', 'fy_tb_nsmc_online')
foreach ($wf in $workflows) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/workflow-definitions/$wf" -UseBasicParsing -TimeoutSec 10
        Write-Host "[$wf] Status: $($r.StatusCode)" -ForegroundColor Green
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        Write-Host "[$wf] Error: $code $($_.Exception.Message)" -ForegroundColor Red
    }
}
