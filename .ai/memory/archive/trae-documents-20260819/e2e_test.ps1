# E2E 测试脚本：在线数据拉取功能验证
$baseUrl = 'http://127.0.0.1:8000'
$apiKey = 'cgda-dev-write-key'
$headers = @{ 'X-API-Key' = $apiKey; 'Content-Type' = 'application/json' }

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  E2E 在线数据拉取功能测试" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# ── 1. 检查工作流定义加载 ──
Write-Host "`n[1] 检查工作流定义加载" -ForegroundColor Yellow
$workflows = @('fy_tb_online_read', 'ndvi_online_read', 'ndvi_gee_read', 'fy_tb_nas_read', 'fy_tb_nsmc_online')
foreach ($wf in $workflows) {
    try {
        $r = Invoke-WebRequest -Uri "$baseUrl/workflow-definitions/$wf" -Headers $headers -UseBasicParsing -TimeoutSec 10
        $json = $r.Content | ConvertFrom-Json
        $nodeCount = $json.nodes.Count
        Write-Host "  [OK] $wf - $nodeCount nodes" -ForegroundColor Green
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        Write-Host "  [FAIL] $wf - HTTP $code" -ForegroundColor Red
    }
}

# ── 2. 检查图层 online_temporal 能力 ──
Write-Host "`n[2] 检查图层 online_temporal 能力" -ForegroundColor Yellow
$layers = @('ref-fy-tb-202512-mwri', 'ndvi')
foreach ($layerId in $layers) {
    try {
        $r = Invoke-WebRequest -Uri "$baseUrl/layers/$layerId/online-temporal" -Headers $headers -UseBasicParsing -TimeoutSec 10
        $json = $r.Content | ConvertFrom-Json
        Write-Host "  [OK] $layerId - enabled=$($json.enabled) workflow=$($json.workflow_online_name)" -ForegroundColor Green
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        Write-Host "  [FAIL] $layerId - HTTP $code" -ForegroundColor Red
    }
}

# ── 3. 检查图层目录列表 ──
Write-Host "`n[3] 检查图层目录 (GET /layers)" -ForegroundColor Yellow
try {
    $r = Invoke-WebRequest -Uri "$baseUrl/layers" -Headers $headers -UseBasicParsing -TimeoutSec 10
    $json = $r.Content | ConvertFrom-Json
    $layerIds = $json | ForEach-Object { $_.layer_id }
    $fyExists = $layerIds -contains 'ref-fy-tb-202512-mwri'
    $ndviExists = $layerIds -contains 'ndvi'
    Write-Host "  Total layers: $($json.Count)" -ForegroundColor Green
    Write-Host "  FY TB layer exists: $fyExists" -ForegroundColor $(if ($fyExists) {'Green'} else {'Red'})
    Write-Host "  NDVI layer exists: $ndviExists" -ForegroundColor $(if ($ndviExists) {'Green'} else {'Red'})
} catch {
    Write-Host "  [FAIL] GET /layers - $($_.Exception.Message)" -ForegroundColor Red
}

# ── 4. 提交 FY 在线工作流 ──
Write-Host "`n[4] 提交 FY 在线工作流 (fy_tb_online_read)" -ForegroundColor Yellow
$fyPayload = @{
    layer_id = 'ref-fy-tb-202512-mwri'
    workflow_name = 'fy_tb_online_read'
    time_range = @{
        start_at = '2025-06-01T00:00:00'
        end_at = '2025-06-02T00:00:00'
        granularity = 'day'
    }
} | ConvertTo-Json -Depth 5
try {
    $r = Invoke-WebRequest -Uri "$baseUrl/workflow-runs" -Method POST -Headers $headers -Body $fyPayload -UseBasicParsing -TimeoutSec 30
    $json = $r.Content | ConvertFrom-Json
    Write-Host "  [OK] Run ID: $($json.run_id)" -ForegroundColor Green
    Write-Host "  Status: $($json.status)" -ForegroundColor Green
    $fyRunId = $json.run_id
} catch {
    Write-Host "  [FAIL] $($_.Exception.Message)" -ForegroundColor Red
    $fyRunId = $null
}

# ── 5. 提交 NDVI Earthdata 在线工作流 ──
Write-Host "`n[5] 提交 NDVI Earthdata 在线工作流 (ndvi_online_read)" -ForegroundColor Yellow
$ndviPayload = @{
    layer_id = 'ndvi'
    workflow_name = 'ndvi_online_read'
    time_range = @{
        start_at = '2025-06-01T00:00:00'
        end_at = '2025-06-02T00:00:00'
        granularity = 'day'
    }
} | ConvertTo-Json -Depth 5
try {
    $r = Invoke-WebRequest -Uri "$baseUrl/workflow-runs" -Method POST -Headers $headers -Body $ndviPayload -UseBasicParsing -TimeoutSec 30
    $json = $r.Content | ConvertFrom-Json
    Write-Host "  [OK] Run ID: $($json.run_id)" -ForegroundColor Green
    Write-Host "  Status: $($json.status)" -ForegroundColor Green
    $ndviRunId = $json.run_id
} catch {
    Write-Host "  [FAIL] $($_.Exception.Message)" -ForegroundColor Red
    $ndviRunId = $null
}

# ── 6. 轮询工作流状态（30秒）──
Write-Host "`n[6] 轮询工作流状态 (30s)" -ForegroundColor Yellow
$start = Get-Date
$runIds = @()
if ($fyRunId) { $runIds += @{Id=$fyRunId; Name='FY'} }
if ($ndviRunId) { $runIds += @{Id=$ndviRunId; Name='NDVI'} }

while ((Get-Date) -lt $start.AddSeconds(30) -and $runIds.Count -gt 0) {
    Start-Sleep -Seconds 5
    foreach ($run in @($runIds)) {
        try {
            $r = Invoke-WebRequest -Uri "$baseUrl/workflow-runs/$($run.Id)" -Headers $headers -UseBasicParsing -TimeoutSec 10
            $json = $r.Content | ConvertFrom-Json
            $status = $json.status
            Write-Host "  [$($run.Name)] $($run.Id) => $status" -ForegroundColor Cyan
            if ($status -in @('succeeded', 'failed', 'cancelled')) {
                $runIds = @($runIds | Where-Object { $_.Id -ne $run.Id })
            }
        } catch {
            Write-Host "  [$($run.Name)] Poll error: $($_.Exception.Message)" -ForegroundColor Red
        }
    }
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  E2E 测试完成" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
