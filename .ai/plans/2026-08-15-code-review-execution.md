# 全面代码审查执行计划（Praxis）

> spec: `.trae/documents/2026-08-15-comprehensive-code-review.md`（四聚焦域、六维度、遗留清单 L-1~L-15、分级标准）
> 模式：审查 + 修复（用户 2026-08-15 指令，覆盖先前"只读"选择）——P0/P1 最小变更修复，P2/P3 仅留痕。
> 命令约定：后端/算法测试用 `Env/Python312/python.exe`，仓库根执行，`ENVIRONMENT=test` + `REDIS_URL`，禁用 WorkBuddy safe-delete shim；前端 `cd Code/frontend && npm run ...`。

goal: 完成四聚焦域审查，产出分级问题清单与报告，并修复全部确认的 P0/P1 使全量回归不退化

- [x] T1: 基线采集
  files: 无改动（只读命令）
  acceptance: 后端/算法/前端测试通过数与失败清单、lint/build、`check:openapi`、`check:catalog` 基线数字落盘到本文件附表；失败按 08-15 审计 §6.1 归属核对
- [x] T2: [parallel] 域 A 安全专项审查
  files: `Code/backend/app/services/credential_resolver.py`、`app/core/ssrf.py`、`app/api/routers/remote_browser_router.py`、`Code/infra/gateway/nginx.conf`、`Code/frontend/src/services/_http.ts`
  acceptance: L-7/L-8/L-9/L-13 逐条状态结论（已闭环/仍存在+等级）；新发现含 文件:行
- [x] T3: [parallel] 域 B 后端核心与并发审查
  files: `app/services/_sqlite_pool.py`、`app/core/celery_app.py`、`app/services/workflow/`、`workflow_timer_service.py`、`app/api/rate_limit.py`、`app/core/redis_client.py`
  acceptance: L-4/L-5/L-14 状态结论；新发现含 文件:行
- [x] T4: [parallel] 域 C 前端状态与可维护性审查
  files: `Code/frontend/src/stores/layers/`、`stores/weather-tile-manager.ts`、`services/_http.ts` vs `data-manager/core/api.ts`、`package.json`
  acceptance: L-1 状态结论 + 两套 HTTP 层差异清单 + 死依赖确认（cesium 0 引用）
- [x] T5: 域 D 基础设施与治理审查
  files: `.github/workflows/ci.yml`、`Code/backend/mypy.ini`（或 apps/backend/mypy.ini）、`requirements*.txt`、`Code/backend/vendor/unrar/README.md`、仓库卫生项
  acceptance: L-11/L-12/L-15 状态结论；mypy exclude 失效验证（命令输出）
- [x] T6: 汇总分级清单，确定修复范围
  acceptance: 问题清单表（# / 域 / 文件:行 / 严重度 / 状态[新增|遗留] / 处置[修复|留痕]）；P0/P1 逐项给出修复方案
- [x] T7: 修复 P1-测试漂移①（并入 F3，见附表）
- [x] T8: 修复 P1-测试漂移②（并入 F4）
- [x] T9: 修复 P1-测试漂移③（并入 F5）
- [x] T10: 修复 T6 确认的其余 P0/P1（F1/F2/F6/F7/F8/F9，见附表）
- [x] T11: 全量回归
  acceptance: 后端 ≥ 基线通过数且失败集为空或仅剩已归属的本地环境项；算法/前端/lint/build/check:openapi/check:catalog 全绿
- [x] T12: 报告落盘
  files: `Docs/06-代码审查/问题清单-2026-08-15.md`、`Docs/08-HTML报告/comprehensive-code-review-2026-08-15/comprehensive-code-review-2026-08-15.html`
  acceptance: 四域结论（✅/⚠️/❌）+ 分级统计 + 遗留状态矩阵 + 本次修复清单 —— 均含
- [x] T13: ship（review 全 diff → 询问 commit/keep）
  review 结论：18 个改动文件（8 产品 + 10 测试）全部命中本次会话窗口（21:16–22:26），`console.log|debugger|TODO|FIXME|HACK|breakpoint` 残留扫描零命中；仓库无 CHANGELOG.md/ROADMAP.md（按仓库惯例不新建）；`.ai/plans` 按仓库惯例保留为进度留痕（不做 praxis 默认 staging 归档删除）

## 第二轮专项：安全收敛 + 并发加固（W-A / W-B，2026-08-15 深夜）

> spec: `.trae/documents/2026-08-15-security-convergence-and-concurrency-hardening.md`
> 触发：用户指令「①（安全收敛）需要做；研究并行资源抢占、冲突、缓存覆盖等问题和相关bug（Use plugin: brooks-lint）」。
> 模式：W-B 审查用 brooks-lint 方法论；修复 praxis TDD（红→绿）。

- [x] W-A1: AESGCM 收敛（闭环 N-1/L-8）
  - 新建 `Code/backend/app/services/secret_cipher.py`（19 例单测 `test_secret_cipher.py`）；
  - 五仓库薄壳化：⑤ weather_providers → ① api_keys → ④ remote_storage → ② gee_credentials（保留 `v1:` 前缀）→ ③ portal_credentials（保留 `iv="plain"` 标记）；零数据迁移、密文格式零变化；
  - 验收：`test_credential_roundtrip.py` 7 + `test_secrets_encryption.py` 5 + 新增 19 全绿；`rg "from cryptography"` 全仓唯一实现点。
- [x] W-A2: legacy remote browser 下线（闭环 N-2/L-7）
  - 后端：删 `remote_browser_router.py` + 两处注册 + 5 例测试；`openapi.json` 重生成（190 paths）；
  - 前端：`RemoteDirBrowser.vue` → `browseRemoteStorage(profileId, path)`；`SshSyncForm.vue` → `testRemoteStorageProfile`（403 提示「仅管理员可测试连接」）；`api-contracts.ts` 清 `/api/remote/servers`；
  - 验收：vitest 相关文件全绿 + `check:openapi` 零漂移 + `rg "/api/remote"` 源码零命中。
- [x] W-B1: brooks-lint 并发审查（8 面全读源，定级见 spec §2 B1 表）：P1 ×3（B-R1/R2/R3）、P2 ×3、P3 ×2
- [x] W-B2: P1 修复（`test_concurrency_hardening.py` 10/10 红→绿）
  - B-R1 `redis_client.py`：`_ACQUIRE_SLOT_LUA` 单次 eval 原子 INCR+EXPIRE，`TTL==-1` 孤儿键补挂自愈；
  - B-R2 `weatherengine/client.py`：`unique_cache_tmp_path`（pid+tid+uuid8）+ `replace_with_retry`（指数退避×5），两处写点接入；
  - B-R3 `open_meteo_sync_tasks.py::_sync_lock_key`：domains 排序+去重+去空白归一化。
- [x] R2 回归（见附表 3）：后端全量复验时发现 `test_secret_cipher.py::test_decrypt_secret_production_empty_iv_rejected` 顺序依赖失败——测试 `_as_production()` 打在导入期绑定的旧 settings 对象上（F6 同款 split-brain：全量套件中其它测试已整体替换 `app.core.config.settings`），修复为调用时动态解析 `config.settings` 当前对象后 19/19 通过；算法/前端/契约门复验全绿。
- [x] D2 落盘：问题清单 §7 增补 + HTML 报告 §8 专项章节 / 统计与 L 矩阵更新。

## 附表 2：T11 终态回归数字（2026-08-15 22:5x）

| 检查 | 终态 |
|------|------|
| 后端 pytest（basetemp=`%TEMP%\cgda-be-r1`） | **1193 passed, 2 skipped, 0 failed / 0 errors**（252.96s；基线 13F+12E 全消解，含 2 新增回归测试） |
| 算法 pytest（basetemp=`%TEMP%\cgda-alg-r1`） | **411 passed + 28 subtests**（51.86s） |
| 前端 vitest（串行） | **131 文件 / 736 测试全绿**：全量 121 文件/663 + 10 文件（auth/session/settings 域）73 单独批次；满载机器（45 node+21 python 进程）worker 启动超时为环境性 |
| 前端 lint | 0 errors / 2 warnings（既有 `MultiOverlayBarChart.vue` no-explicit-any，非本次改动） |
| 前端 build | ✓ built in 6.1s |
| check:openapi / check:catalog | OK 零漂移 / OK（55 items + 7 categories） |

> 环境注记：三组测试并行触发 basetemp `WinError 5`（`Test/.pytest-be` 残留锁定，=L-11/N-8）与 vitest worker 超时；串行 + 独立 basetemp 后稳定。`Test/.pytest-be` 受本环境删除策略限制无法清理（需本地管理员手动）。

## 附表 3：R2 第二轮终态回归数字（2026-08-16 0:1x–0:3x）

| 检查 | 终态 |
|------|------|
| 后端 pytest（basetemp=`%TEMP%\cgda-be-s2`） | **1217 passed, 2 skipped, 0 failed / 0 errors**（281.89s；R2 首跑 1216P+1F → 修复测试顺序依赖后复跑 1217P） |
| 算法 pytest（basetemp=`%TEMP%\cgda-alg-s2`） | **411 passed + 28 subtests**（63.03s） |
| 前端 vitest（串行） | **131 文件 / 736 全绿**（主批 121 文件/663 + auth/session/settings 域 10 文件单独批次 73；worker 启动超时为环境性，与第一轮同款） |
| 前端 lint / build | 0 errors / 2 warnings（既有） / ✓ built in 5.79s |
| check:openapi / check:catalog | OK 零漂移（190 paths）/ OK（55 items + 7 categories） |

> R2 过程发现并修复：`test_secret_cipher.py::_as_production` 导入期绑定旧 settings 对象 → 全量套件顺序依赖失败（1 failed）；改为调用时动态解析 `config.settings` 后全绿（见 R2 条目）。

## 附表：基线数字（T1，2026-08-15 21:0x）

| 检查 | 结果 |
|------|------|
| 后端 pytest | **13 failed, 1164 passed, 2 skipped, 12 errors**（473.7s；basetemp=`Test/.pytest-baseline`） |
| 算法 pytest | 通过（exit 0） |
| 前端 vitest（串行 `--no-file-parallelism`） | **130 文件 / 733 测试全绿**；并行模式在本机有 worker 启动超时（资源饥饿，非测试失败） |
| 前端 lint / build | 待 T11 前补跑 |
| check:openapi / check:catalog | 待 T11 前补跑 |

### 后端失败归属（相对 08-15 晨间审计的增量标注）

| 测试 | 数量 | 归属 |
|------|------|------|
| test_weather_coverage + test_weather_engine_settings_phase_a | 12 ERROR | 既有：引用已移除的 `weather_router.get_redis_client`（RBAC v2 `10b7eb1`）→ **修复 F3** |
| test_frontend_call_simulation | 3 | 既有：匿名 fail-closed 401 语义漂移 → **修复 F4** |
| test_import_raster_crs | 2 | 既有：`ValueError` 不可 JSON 序列化（真产品缺陷）+ 422≠400 → **修复 F5** |
| test_dataset_registry | 6（晨间 5，+1 新） | 本地 `.data` 注册库共享状态（45 条真实数据集）；测试未隔离 → **修复 F6** |
| test_workflow_request_resolver::test_fy_single_descriptor | 1 | **新增**：依赖 `I:\test` 下 FY3D/FY3B 等数据目录存在性（当前全不存在）；晨间通过→数据已漂移；测试未隔离 → **修复 F7** |
| test_archive_safe::test_safe_extract_7z_roundtrip | 1 | **新增**：**真产品缺陷** —— `7z l -slt` 首块 `Path = <绝对路径>`（压缩包自身头）未被过滤，解析器仅比对 basename → 合法 .7z 误拒「非法压缩包路径」；CI 无 7z CLI 故 skip 掩盖 → **已修复 F1** |

### 修复进度（T10 展开，红→绿逐项）

| # | 问题 | 状态 | 验证 |
|---|------|------|------|
| F1 | archive_safe 7z `l -slt` 头块（压缩包自身 `Path`）误判为成员 → 合法 .7z 误拒 | ✅ 已修复 | 新增 `_parse_7z_slt_listing`（`----------` 分隔符后才开始收集条目）；`test_archive_safe.py` 22/22 通过（含 2 个新回归测试：绝对路径头、相对路径头+Folder 条目） |
| F2 | data-manager `core/api.ts` 独立 HTTP 层缺 401 会话过期处理（与 `_http.ts` 双轨） | ✅ 已修复 | `writeFetch` 统一：401（非 `/auth/*` bootstrap）→ `handleSessionExpired` + 抛 `SessionExpiredError`（分块上传立即中止、无重试风暴）；新测试 `Test/frontend/data-manager/core/api-401.test.ts` 2 例（红→绿）；data-manager/session-expired/_http 相关 7 文件 21 测试全绿；lint 通过 |
| F3 | weather 测试桩引用已移除的 `weather_router.get_redis_client`（12 ERROR） | ✅ 已修复 | 两文件 fixture 改从 `app.services.weather_coverage_cache` 取 `get_redis_client`/`COVERAGE_REDIS_PREFIX`（P0-2 迁移后的真源）；断言零改动；`test_weather_coverage.py` + `test_weather_engine_settings_phase_a.py` 19/19 通过 |
| F4 | frontend_call_simulation 鉴权漂移（3，RBAC v2 匿名 fail-closed 401）+ 单文件运行时 tile 注册表重建顺序（1） | ✅ 已修复 | 新增 `_admin_cred()`（`CredentialContext(source="dev_bypass", role="admin")`），生命周期/取消/重试直接调用显式携带凭据（不绕过 fail-closed）；tile 503 测试改为先 `create_app()` 触发默认注册再插入失败 provider（首调 `clear()` 重建会清掉插入项），清理加 `suppress(ValueError)`；30/30 通过 |
| F5 | `validation_exception_handler` 直接序列化 `exc.errors()` → model_validator 的 ValueError 进 ctx → **TypeError 500**（系统性产品缺陷：workflow_engine/models、data_io/router、import_router 3 处生产 validator 均触发）；+ 2 处测试断言与现行契约漂移（422≠400/200） | ✅ 已修复 | handler 改用 `jsonable_encoder(exc.errors())`（`main.py`）；新回归测试 `test_model_validator_value_error_serializes_cleanly`（红→绿）；`test_empty_points`/`test_invalid_bounds_length` 断言对齐 openapi 契约（均 422，schema minItems=4 与 model_validator 均为现行语义）；`test_import_raster_crs+test_error_handlers+test_crs_detector` 62/62 通过；未改任何 Pydantic schema → openapi 零漂移 |
| F6 | dataset_registry 6 failed：**settings split-brain**——`dataset_registry_service`/`workflow_request_resolver` 以 `from app.core.config import settings` 导入期绑定引用；test_config_*/test_data_root_policy 以 `monkeypatch.setattr("app.core.config.settings", replace(settings, ...))` 换对象时，服务模块首次导入若落在 swap 窗口内即永久持有临时对象 → 此后一切属性补丁（`_patch_setting` 打在还原后的对象上）对服务无效（sync=45≠1、Z:/ 盘 patch 后仍 45≠0、rescan=11≠3） | ✅ 已修复 | 两模块改动态读 `config.settings.X`（与 credential_resolver/deps/effective_config 既有约定一致，见 `test_config_security.py` L170 注释）；新增回归测试 `test_rescan_reads_current_settings_object`（红：`assert 11 == 1` 与全量失败同值 → 绿）；dataset_registry+data_source_paths+data_root_policy 26/26 通过 |
| F7 | `test_fy_single_descriptor_uses_accepted_fy_dataset_keys` 依赖真实机构数据盘 `<DATA_ROOT>/Soil_Moisture/FY3D|FY3B` 存在（当前 `I:\test` 下不存在）→ `data_access` 为空 | ✅ 已修复 | 测试内 tmp 数据根自建 descriptor.default_data_access_sources 全部候选目录（SMAP_Origin_Data/SMAP_Auxiliary_Data/NDVI climatology/FY3D/FY3B）；`object.__setattr__` 补丁 `data_root` + finalizer 还原；前后 `invalidate_template_cache()` 清 `_resolve_provider_dataset_path` lru_cache（防跨 data_root 缓存污染双向泄漏）；test_workflow_request_resolver 5/5 通过 |
| F8 | 网关与 Vite 均未代理 `/api` 前缀 → remote browser（`/api/remote/list|test|servers`，RemoteDirBrowser/SshSyncForm 调用）两条链路全断（返回 index.html）；网关无 CSP 等安全响应头 | ✅ 已修复 | nginx.conf：`api` 加入反代白名单 regex；server 级新增 `Content-Security-Policy`（script/style 'unsafe-inline' 受内联主题脚本与运行时样式约束，img-src https: 支持外部瓦片源，worker-src blob: 支持 MapLibre）+ `X-Content-Type-Options: nosniff` + `Referrer-Policy`；vite.config.ts 补 `/api` 代理（注释说明例外原因） |
| F9 | weather-tile `clearLayer` 漏清 `viewportFillStartedAt` → 同 id 图层重建后继承旧填充起点，viewport-fill perf 指标失真（低危，仅遥测） | ✅ 已修复 | `clearLayer` 补 `viewportFillStartedAt.delete(layerId)`；回归测试以可中止 fetch mock + `performance.now` spy 精确复现 60000ms 失真（红）→ 修复后 <30s（绿）；weather-tile 9 文件 43/43 通过 |
