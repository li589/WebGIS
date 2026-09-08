# 提交后全量缺陷审查报告

**日期**：2026-08-05  
**基线**：`origin/dev...HEAD`（HEAD `e4ac39de`，ahead 31）  
**WIP**：仅未跟踪本地脚本（`_env_*.bat` 等），无已跟踪未提交改动 —— 不入本报告缺陷表。  
**方法**：对照 gstack 修复声称 → L1–L5 精读 → 针对性 pytest / vitest / lint / build / check:openapi。

## 修复进展（2026-08-05）

| ID | 状态 | 说明 |
|----|------|------|
| BUG-1 | 已修 | `safe_urlopen` 重定向再校验；`HttpSourceFetcher` 改用；`Test/backend/test_ssrf.py` |
| BUG-2 | 已修 | `finalize_workflow_success/failure` 跳过覆盖 watchdog-failed / cancelled；`test_workflow_watchdog_finalize.py` |
| BUG-3 | 已修 | `BACKEND_TRUST_PROXY` 默认 false；`client_ip` 条件解析；`test_rate_limit_client_ip.py` |
| BUG-4 | 已修 | `WORKFLOW_COPY.noMapLayers` + `resolveEmptyOverlayWorkflowError`；vitest `materialize-empty` |

验证：后端抽样 18 passed；前端 materialize-empty + workflow-local 6 passed。

---

## 验证门禁摘要

| 门禁 | 结果 |
|------|------|
| `test_config_security` + `test_api_keys_basemap` + `test_celery_tasks` + `test_workflow_routes` + `test_interaction_hub` | 30 passed |
| `test_import_raster_crs` + `test_crs_detector` + `test_unified_tile_service` | 66 passed |
| `test_omega_avg_daily_module` + `test_omega_avg_algorithm` | 14 passed |
| `npm run check:openapi` | OK |
| `npm run lint` | 0 errors / 40 warnings |
| `npm run build` | 通过 |
| 构建产物扫描 `VITE_BACKEND` | 未发现内联 |

## 声称修复核对（抽样）

| 项 | 结论 |
|----|------|
| P0-1 env 默认 production | 属实（`config.py`）；无 key 时写接口 503 fail-closed |
| P0-2 SSRF + remote_browser 鉴权 | 部分属实：初始 URL 校验 + router 级 `require_write_access`；**重定向未再校验**（见缺陷 #1） |
| P0-3 端口回环 | 属实；MinIO 默认凭据仍为 `minioadmin`（Known） |
| P0-7 visibility_timeout=8100 | 属实 |
| P0-8 吊销不回落 env | 属实（`has_api_key_db_row`）；同进程写路径 `hydrate`；跨进程仍 stale（Known） |
| P0-9 materialize→workflowError | 属实；**succeeded+0 图层仍无空态**（Known / #4） |
| P1-1 去构建期内联密钥 | 属实 |
| P1-4 solo 看门狗 | 属实；不杀 worker（Known）；与成功收口竞态（#2） |
| omega-sf-fenkuai catalog 输入源 | 已提交：`smap_folder`/`anc_root`/`ndvi_clim_folder` + `workflow_id` |

---

## 缺陷清单（按严重度）

### P0 / 高

#### BUG-1：HTTP 出站 SSRF 可被重定向绕过

- **位置**：[`Code/backend/app/services/source_fetcher.py`](Code/backend/app/services/source_fetcher.py)（`HttpSourceFetcher.fetch`）；[`Code/backend/app/core/ssrf.py`](Code/backend/app/core/ssrf.py)
- **症状**：`validate_outbound_url` 仅校验请求前 URL；`urllib.request.urlopen` 默认跟随重定向，攻击者可控的外网 URL 可 302 到 `127.0.0.1` / `169.254.169.254` 等，绕过环回/链路本地阻断。
- **复现（推理）**：配置/下载源指向攻击者服务器 → 返回 `Location: http://127.0.0.1:6379/` → 后端读内网响应。
- **建议**：禁用自动重定向，或对每个 `Location` 再跑 `validate_outbound_url`；补单元测试（mock 重定向到环回应抛 `SSRFBlockedError`）。当前 **无** `Test/**/test*ssrf*`。

### P1

#### BUG-2：solo 看门狗与仍在执行的 worker 竞态，可能「假失败后变成功」或状态撕裂

- **位置**：[`follow_up_dispatch_service.py`](Code/backend/app/services/workflow/follow_up_dispatch_service.py) `fail_stuck_running_workflows`；[`submission_service.py`](Code/backend/app/services/workflow/submission_service.py) `process_workflow_run` → `finalize_workflow_success`
- **症状**：看门狗按 `updated_at` 超时把 run 标为 `failed`，但 solo worker 仍在跑；任务结束后 `finalize_workflow_success` **不检查**是否已被看门狗失败，可写回 `succeeded`，UI 先失败后成功；或失败态与产物半写入并存。
- **建议**：收口前若 status 已为 `failed` 且 `cleanup_reason=stuck_running_watchdog`，跳过成功覆盖或改为 `cancelled`/`superseded`；看门狗记录 `celery_task_id` 并尝试 revoke（即使 Windows terminate 弱）。

#### BUG-3：写限流信任客户端 `X-Forwarded-For`

- **位置**：[`Code/backend/app/api/rate_limit.py`](Code/backend/app/api/rate_limit.py) `client_ip`
- **症状**：未在受信反代后时，攻击者可伪造 `X-Forwarded-For` 绕过每 IP 120/min 限制（或污染桶）。
- **建议**：仅当 `BACKEND_TRUST_PROXY=true`（或类似）时解析转发头；默认用 `request.client.host`。内网单 Key 场景风险中等。

#### BUG-4：工作流 succeeded 但 0 产出图层仍无用户可见空态

- **位置**：[`Code/frontend/src/stores/layers/index.ts`](Code/frontend/src/stores/layers/index.ts) `attachAlgorithmProductOverlays`（`if (!imports.length) return 0`）
- **症状**：materialize 抛错已写 `workflowError`；但成功返回空 `layers` / 无 overlay 时静默 return 0。审计标为有意后续项，**主链仍可「成功无图」**。
- **建议**：当 `runId` 存在且 terminal=succeeded 且 attach 计数为 0 时设置 `workflowError` 或专用空态文案。

### P2 / 残留与已知降级

| ID | 说明 | 归类 |
|----|------|------|
| K-1 | Redis 无 `requirepass`（端口已回环） | Known 审计降级 |
| K-2 | MinIO 默认 `minioadmin/minioadmin`（可经 env 覆盖） | Known；生产须覆盖 |
| K-3 | 配置缓存跨进程不失效（FastAPI 写 key，Worker 投影陈旧） | Known；同进程有 `hydrate` |
| K-4 | `invalidate_effective_config()` 零调用（写路径直接 `hydrate`，函数仍死代码） | 卫生问题，非新漏洞 |
| K-5 | 看门狗不释放被卡 solo worker（须重启） | Known |
| K-6 | SSRF 默认 `allow_private=True`（内网 NAS 合法） | 设计取舍；无重定向修复前仍偏松 |
| K-7 | `BACKEND_RELOAD` 默认 `true`，误用 production 易开 reload | 运维脚枪 |
| K-8 | CI `security-scan` `continue-on-error` + `\|\| true`，漏洞不挡合并 | 有意非阻塞 |
| K-9 | `smap-soil` 仍出现在 `.env.example` / `source_uri_map.example.json` 注释示例 | 文档漂移，运行 seed 已改 `smap-sm-ts` |
| K-10 | 前端 lint 40 warnings（`no-console` / `any`）；litegraph `eval` 构建告警 | 非功能性 |

### 未发现（本轮抽样为绿）

- production 无 key 时写接口免鉴权（已 fail-closed）
- remote_browser 路由级鉴权缺失
- Celery `visibility_timeout` 缺失
- 前端 bundle 内联 `VITE_BACKEND_API_KEY`
- OpenAPI 关键前缀漂移
- Mercator preview 主路径仍用整像素 `array_bounds` 取全图范围（已改 `transform_bounds`；末尾 `array_bounds` 仅回读重建 Affine，合理）
- omega_avg_daily 路径假绿（本机 14 passed；CI 有合成数据生成步骤）

---

## 建议修复优先级

1. **立刻**：BUG-1（重定向 SSRF）+ 补测试  
2. **短期**：BUG-2（看门狗与 finalize 互斥）  
3. **发布前体验**：BUG-4（0 图层空态）  
4. **加固**：BUG-3（可信代理）、K-2 生产文档强制改 MinIO 凭据  

本阶段按计划 **未改产品代码**。
