# 2026-09-06 — 全量代码审查修复（P1/P2）：绑定回归、测试接缝、路径惰性化

## 背景

对 `41ca0bf6..HEAD`（09-03→09-05，16 提交 328 文件）做全量代码审查：auth/agent/layer/session/timer/data_io/CSP/算法/前端逐文件 diff 精读 + 三套测试门禁实测。审查报告结论：无安全漏洞；P1×3（前端绑定白名单回归、9 处测试接缝漂移、导入期路径快照致测试污染真实数据根）、P2×2（NDVI 魔法数、scope 热路径逐请求 SQLite 读）。

## P1 修复（9 文件）

- **产物绑定白名单回归**：`run-layers.ts` `isTagCompatibleWithTarget` 重构——黑名单（smap-aux/aux/gebco）前置对全路径生效；`wf-out-*` 产出层对全部产物 tag 兼容；调用方指定的发起层（preferredCatalogId 回退）信任调用方。修复 SM 产物无法绑定 `wf-out-*` 输出层（vitest 2 失败实证，`b6e2bcfd` 引入）。
- **测试接缝漂移**：`test_http_materialize_status` 5 处 patch 目标 `urlopen`→`_open_http_request`（earthdata 安全重定向重构后旧符号已删）；3 个 NDVI 测试文件 mock `load_ndvi_stack`→`load_ndvi_stack_full`（返回 `NdviStackInfo`）。
- **测试污染真实数据根**：`workflow_definition_service` 目录常量被历史会话固化指向真实根，`wf-alice-owned.json`/`test-histogram-p1.json` 测试产物已从 `I:\Geograph_DataSet\workflow_definitions\user\` 清除；`test_auth_boundary_hardening` 重绑目录、`test_import_job_ownership` 夹具级 no-op 属主断言、`test_materialize_run_subdir` stub 补 `command_label`。

## P2 修复（~40 文件）

- **NDVI 魔法数**：`ingest/ndvi.py` `(1624,3856)` → `EASE2_SHAPE_9KM`。
- **scope 热路径缓存**：`resolve_catalog_group_scope` 消费端加 30s TTL 缓存（`_scope_cache`，key=(user_id,role)），失效统一挂 `invalidate_cache()`（全部分组/预设/归属写路径汇聚点）+ `reset_for_tests`；admin `theme_id` 预览绕过缓存。新增回归锁 `test_scope_cache_invalidated_on_preset_write`。
- **导入期快照惰性化**：`paths.py` 四常量 → `output_root()/imports_dir()/staging_dir()/jobs_dir()/doc_sessions_dir()`（逐调用读 `config.settings`，CWD 兜底告警只发一次）；`workflow_definition_service` → `definitions_root()/system_dir()/user_dir()`。20+ 消费方机械替换；16 个测试文件 ~55 处 monkeypatch 形态适配（字符串名 setattr→函数 patch+lambda、点路径 setattr、赋值式恢复→monkeypatch）；`test_resumable_upload` staging fixture 改 patch `output_root`；`test_auth_boundary_hardening` 移除常量重绑（settings patch 即可隔离）。从此测试写不进真实数据根。

## 复审收尾

- 失效链核验：`merge_display_names_in_theme`/`sync_workspace_to_theme` 均经 `_save_mutated_theme_preset`→`save_theme_preset`→`invalidate_cache()` ✓
- 旧代码残留：`BACKEND_OUTPUT_ROOT` 命中均为环境变量名（合法）；`import_router` 别名 `_IMPORTS_DIR` 调用点已带 `()`
- 文档：活文档引用符号（`_build_meta`/`_ID_PATTERN`/`QuotaExceededError`）未改；带日期快照按约定不动；本篇即进度记录

## 验证

- `pytest Test/backend Test/algorithms`：**2761 passed / 0 failed**
- `vitest`：**1726 passed / 0 failed**；`npm run build`、vue-tsc、eslint 绿
- `check:catalog` / `check:openapi` OK；ruff（algorithms 门禁范围）绿
- 联调注意：360 安全卫士会丢弃环回入站 TCP（python/node/powershell 自连 127.0.0.1 全超时），导致 asyncio Proactor socketpair 阻塞、FastAPI 无法启动——启动挂起先暂停 360 网络防火墙
