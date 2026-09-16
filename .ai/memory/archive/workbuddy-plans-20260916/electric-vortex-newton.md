# ω 反演图层组在线反演 · 续接执行计划（2026-08-19 深夜）

> 骨架：Trae 旧计划 P0-P6（`.ai/memory/archive/trae-documents-20260819/2026-08-19-omega变体验证与时间轴联动续接执行计划.md`）
> 基线：2026-08-19 23:48 三探索代理 + Plan 代理核验（服务已由用户重启，全栈正常）

## 一、用户需求 → 对应阶段

| 用户需求 | 阶段 |
|---|---|
| 残留问题检查 + 计划可行性 | P0（基线复验） |
| 分析-工具逐个正常、图层正常加载 | P0（冒烟 13 条 + UI 抽验） |
| ω 图层组默认在线、失效切换本地 | P1（X2 变体路由验证，代码已落盘） |
| 一组三个无占位、组标题进度、颜色变化 | P2（实跑验证）+ P3（chip 四态配色） |
| 时间轴联动动态反演、实时渲染、失败重试 | P3（online_temporal + 时间轴） |
| 逐瓦片渲染 + 可改配色 | P2（渲染配色验证） |
| 风云拼接（FY3F） | P5 |
| 残留修复 | P4 |

## 二、当前状态核验（关键更新）

**已完成可跳过**：
- ω run 残留清理（run-65bc52ff2c5a / run-f6b15b8181ce 全库 NOT FOUND，无 running/pending/queued）
- fy拼接 Matlab 原始代码入库（4ca6fdc）；products/ repro 残留已清
- X2 单测已全绿（旧计划「零验证」过时）：resolver 15 + variant_readiness 8 + omega_alignment 4 + 前端 vitest 1162 全过
- resource_profile 已闭环：`resource_profile_resolver.py:21` 含 omega_sf_fenkuai，`submission_service.py:158` 自动升级 standard→heavy → 降级为 API 断言项
- openapi.json / api-contracts.ts 已含 WorkflowVariantDef，无需 gen:types

**仍需执行**：
- dist 过期（dist 21:33 < src 23:37）→ 重建
- online_temporal：4 个 ω method 图层均缺（现仅 layer_descriptors.json:89/828 两图层有）
- group-status-chip 四态配色缺失
- API 级实跑验证（双变体 + resource_profile 断言）
- P2 组结构/渲染/配色实跑验证、P4 残留修复、P5 FY3F、P6 全量回归提交

## 三、执行阶段

### P0 基线复验 + dist 重建（~1h）
1. `cd Code/frontend && npm run build`（静态目录直读，无需重启 Gateway）
2. 冒烟复验：`Env\Python312\python.exe Tools/smoke_system_workflows.py --report Test/reports/smoke-analysis-2026-08-20a.md` → 13/13
3. UI 图层加载抽验（Gateway :5175，抽 2-3 个非 ω 图层 + ω 合并组两成员可见 + 分析工具 Tab 可用）
4. run-1a0f754b7f0a 排查（failed 且 error 空）：`Test/debug/query_run_detail.py` 查事件流；开发期残留则记录放行，系统性失败则升级阻塞

**验收**：dist mtime > src 最新 mtime；冒烟 13/13；UI 正常。

### F4 小修（P1 前置）+ P1 X2 变体路由 API 级验证（~1h）
1. F4：`workflow_request_resolver.py:270` `_describe_workflow_variant_readiness` 的 local_ready 加 `local is not None` 前提（防单变体 descriptor 误报）；跑 `Test/backend/test_workflow_request_resolver.py test_workflow_variant_readiness.py`（`--basetemp` 指向系统临时目录绕 WinError 5）
2. API 实跑（登录态经 `Test/debug/api_admin.py` 模式）：
   - 提交 `layer_id=method-fy-omega-doy-dynamic`（layer_id-only，无显式变体）
   - 断言：payload `workflow_name=="omega_sf_fenkuai_fy_online"` 且无 module_name；事件流 fy_download→fy_daily→omega_sf_fenkuai 链；`{YYYYMMDD}` 已展开；`resource_profile=="heavy"`
   - local 变体实跑一次（切本地 → omega_sf_fenkuai_fy_single）

**验收**：双变体断言全过。失败按 resolver→bridge→provider 链逐层定位（`Test/debug/check_compile_api.py` 复用）。

### P2 ω 组「一组三个」实跑验证（~1.5h）
1. `Tools/smoke_system_workflows.py --only omega_sf_fenkuai_smap_single`（本地链不依赖凭据）
2. 组结构：3 占位成员（SM/VOD/OMEGA）→ 终态 3 importedRaster、无占位残留、组标题带进度
3. 瓦片渲染+配色：勾选 SM 成员 → 地图显示；InfoPanelStyleTab 切 palette/vmin/vmax → 即时变化+回写 URL

### P3 online_temporal + 时间轴联动 + 组颜色（~3h）
1. 4 个 method 图层（layer_descriptors.json `method-{fy,smap}-omega-doy-{dynamic,avg}`）加：
   `online_temporal: {enabled:true, native_step:"1d", max_batch:8, prefetch_depth:1, queue_tag:"temporal-fetch", priority:"low"}`；coverage SMAP≥2015-04、FY3D≥2017-01，coverage_end:null
2. orchestrator 零代码接入核验：MAX_CONCURRENT_FETCHES、去重键 `${catalogId}:${timeKey}`、失败 60s 冷却
3. F3 chip 四态配色（纯样式）：`LayerSidebarActive.vue:103` 加状态 modifier class；`LayerSidebar.styles.css:1026` computing 蓝/ready 绿/failed 红/cancelled 灰（主题 token），不动状态机
4. 8 天块对齐（AD10）：timeKey `{8digits}_{8digits}` + 8day step 与 `raster_timeseries.upsert_block_dir_timeseries` 投影核对
5. 重放幂等（D12）：失败 60s 后重拖同段无重复组；出错后拖动时间轴继续 拉取→处理→渲染
6. F1 缩进修复：`workflow-runner.ts:936-947` 归位；F2 注释修正：`useWorkflowState.ts` switchWorkflowVariant 注释与实现一致
7. 验证：`npm run test -- online-temporal workflow-timekey-seek workflow-runner run-layers` + `npm run check:catalog` + lint

### P4 残留修复 R1/R2/R3/R5/R4（~5h，P3 后期穿插）
- R1 esa：`GET /workflow-runs/{id}/events` 定位 401（CDSE 凭据预检）；`--only open_data_esa_product_sample` 复跑
- R2 h5→mat：新增 `smap_h5_to_mat` 模块（参照 `download_nodes.py:685` GldasNc4ToMatModule；输入以 `I:\Geograph_DataSet\Soil_Moisture\SMAP_Origin_Data` 真实样例为准）→ 种子图插 `nsidc_smap_download → smap_h5_to_mat → omega_avg_daily` → Test/algorithms 单测 → `--only omega_avg_daily_smap_online` 至 succeeded
- R3 gldas 凭据传播：追 portal store → worker env/job payload → `ingest/gldas_download.py` 消费点；**只改传播路径不动存储/加密**（高风险区）；`test_config_security.py` 全量回归
- R5 GDAL PATH：`fy_preprocess` 的 GDAL CLI 解析链（CGDA_GDAL_BIN→OSGeo4W→QGIS→conda→PATH）定位并配置 `.env`；`--only fy_tb_online_read` 复跑
- R4 HPC：隧道连通探测；不可达 → 如实 blocked + 指引

### P5 FY3F 接入（~2.5h）
1. `ingest/fy_preprocess.py` FY3F 变体（SDS/波段命名/nodata -32767/-32768→NaN，以 `Matlab/fy拼接/B4_FY3F.m` + `FY3F_MWRI_mosaic.py` 为准）；mosaic 复用 buildvrt+warp 骨架
2. `fy_download` 模块 `fy_platform` 支持 `"3F"`；种子 `omega_sf_fenkuai_fy_online` 加 FY3F 支路（默认 disabled，对齐 FY3B 先例）
3. `Matlab/readme.txt` 补说明；Test/algorithms FY3F 合成 fixture 用例
4. 验证：`pytest Test/algorithms -q` + `--only omega_sf_fenkuai_fy_online` + `Tools/audit_workflow_seeds.py`

### P6 全量回归 + 提交（~2h）
1. `launch.py restart backend`（Windows 管理员终端）
2. 全量矩阵（后台）：`Tools/smoke_system_workflows.py --report .ai/progress/2026-08-19-workflow-live-matrix-omega.md`
3. 后端全量：`CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -m pytest Test/backend -p no:cacheprovider --basetemp="Test/.pytest-be"`
4. 前端：`npm run test && npm run lint && npm run build`
5. `pre-commit run --all-files`（PATH 前置 `C:\Windows\System32` + Git cmd；`env -u ACC_PRODUCT_CONFIG_V3`）

**提交序列**（分批收尾：每轮提交前隔离非本线文件，保证 add -A 时工作区仅含本线；硬约定 conventional commits、1MB 大文件限制）：

| 序 | 任务线 | Commit message |
|---|---|---|
| 1 | X2+P2+P3：resolver/builder/descriptors(variants+online_temporal)/contracts/openapi/前端变体链/chip 配色/相关测试/smoke 脚本 | `feat(omega): ω 在线默认+变体路由+时间轴联动与组配色` |
| 2 | 品牌：config.py service_name、AboutSettings/LoginView、config_service 技术栈、SettingsPanel/Tooltip 等 UI | `feat(brand): 品牌信息更新` |
| 3 | F5 调试脚本：Test/debug/ 46 个 .py 入库（**先删/ignore 3 个数据文件** payload_fy_omega_online.json、run-probe0001.backup.json、v2r_api_payload.json） | `chore(test): 调试与探查脚本入库` |
| 4 | P4 修复 | `fix(workflow): DATA_ROOT 展开+esa/gldas/GDAL 残留修复` |
| 5 | P5 | `feat(fy): FY3F 预处理变体与种子支路` |

推送 origin/dev：**待用户明确指示**，不自动推送。

## 四、风险与回滚
| 风险 | 缓解 |
|---|---|
| X2 路由 live 仍有遮蔽路径 | P1 三断言逐层定位；FE 显式键优先级已有测试守护 |
| ω 在线实跑时长拉长（35min/chunk） | light-smoke 先行；长任务后台轮询；P2 结构验证用本地链 |
| online_temporal 1d vs 8 天块语义冲突 | 先核对 timeKey 解析，冲突修 native_step 投影而非前端 |
| R3 凭据传播触加密高风险区 | 只改传播路径；单文件 revert；test_config_security 回归 |
| Windows 文件锁 pre-commit 吞改动 | 每提交前 git add -A 全量暂存 |
| 提交线误并 | 每轮 git status --short 复核清单 |

## 五、执行顺序总览

```
P0(dist 重建→冒烟→UI 抽验→run-1a0f 排查)
  → F4 local_ready 小修+单测 → P1(API 实跑双变体+resource_profile 断言)
  → P2(组结构+渲染配色) → P3(online_temporal+时间轴+chip，顺带 F1/F2)
  → P4(R1→R2→R5→R3→R4 穿插) → P5(FY3F)
  → P6(全量回归→pre-commit→提交 1-5 序列→待用户指示推送)
```
