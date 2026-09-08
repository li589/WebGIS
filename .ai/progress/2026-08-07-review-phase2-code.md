# CGDA 代码审查清单（Phase 2）— 工程师寇豆码

> 日期：2026-08-07 ｜ 阶段：Phase 2 代码级全面审查（只读）
> 审查对象：`Code/backend/app`（G1/G2）、`Code/frontend/src`（G3）、`Code/algorithms/providers/Python`（G4）
> 方法：重点精读 ~60 个文件 + 全仓 grep 扫描（subprocess/eval/urlopen/pickle/测试统计）

## 1. 总览
- 审查文件数：后端 app 重点精读 ~35 个（routers/services/core/weatherengine/tasks/workflow），前端 stores/services/composables 精读 ~12 个，算法包 data_access/runner/ingest 精读 ~15 个；另做全仓 grep 扫描（subprocess/eval/urlopen/pickle/测试统计）。
- 问题统计：P0=0，P1=1，P2=11，P3=7（P3 已合并）。整体工程质量高，未发现崩溃/数据丢失级问题，但发现 1 个真实路径穿越（P1）与 SSRF 修复覆盖面不完整（P2）。

## 2. G1 后端核心问题
| ID | 文件:行 | 问题 | 维度 | 严重度 | 修复建议 |
|---|---|---|---|---|---|
| G1-01 | services/overlay_registry.py:149-172,122-131 + api/routers/layer_router.py:171,213,288 | **路径穿越**：`resolve_source_path`/`resolve_bounds` 把用户 `time` 直接 format 进路径且**不校验 time_list**（对比 `resolve_png` L103 有校验）。未鉴权 GET `/overlay-bounds`、`/overlay-value`、`/overlay-tiles` 传 `time=../../…` 可读任意 .json/.mat/.nc/.h5/.tif（配合 `*` 通配符放大）；`resolve_value` 还会用 UniversalDataReader 采样文件值 | 安全 | P1 | resolve_source_path/resolve_bounds 先校验 `t in self.time_list`，并对解析后路径做 overlay_dir 包含性检查 |
| G1-02 | services/tile_proxy_service.py:237 | `httpx.AsyncClient(follow_redirects=True)` 底图代理跟随重定向且无 SSRF 校验（与 BUG-1 同类，但 BUG-1 只覆盖 safe_urlopen 路径） | 安全 | P2 | 关闭 follow_redirects 或逐跳用 resolve_outbound_target 校验 |
| G1-03 | weatherengine/client.py:333；providers/weatherapi_provider.py:343；providers/openweather_provider.py:337；api/routers/weather_router.py:52；services/weather_engine_settings.py:140 | 多处出站请求仍用裸 `urlopen`（urllib 默认跟重定向）；provider base_url 可由管理员 DB 配置 → SSRF 加固不完整 | 安全 | P2 | 统一改走 core/ssrf.safe_urlopen |
| G1-04 | services/source_fetcher.py:212-291 | LocalFileSourceFetcher `file:///` 可读服务器任意本地文件（无根目录白名单/包含性校验）；受 admin 配置 gate，风险中 | 安全 | P2 | 限制 source_uri 在 download_source_root 等配置根内 |
| G1-05 | api/routers/workflow_router.py:59-66 | `_get_client_ip` 无条件信任 X-Forwarded-For/X-Real-IP，与 BUG-3 修复不一致（rate_limit.py:63 已按 trust_proxy 判断）→ events 轮询限流可被伪造头绕过/污染他人桶 | 安全 | P2 | 复用 rate_limit.client_ip 逻辑 |
| G1-06 | api/routers/layer_router.py:50-69 | 每次 /layers 请求新建 ThreadPoolExecutor(8) + 逐图层就绪检查，高频轮询开销大 | 性能 | P2 | 复用池/加就绪结果短缓存 |
| G1-07 | tasks/workflow_tasks.py:252-263；api/routers/weather_router.py:295-320 | 每次派发新建 ThreadPoolExecutor；`fut.result(timeout)` 超时后 raise 但后台线程仍可能完成 apply_async → 客户端重试造成重复派发 | 正确性/性能 | P2 | 用共享 executor + 幂等键/去重 |
| G1-08 | services/download_orchestrator.py:472-478 | `template.format()` 只捕获 KeyError/IndexError，非法格式串抛 ValueError → 500 | 正确性 | P2 | 捕获 ValueError 并返回 None |
| G1-09 | api/routers/workflow_router.py:293,372-373 | 调用私有方法 `_build_product_map_layer_refs`；`except Exception: continue` 吞掉 block 目录 upsert 错误 | 可维护性/正确性 | P2 | 改公开方法；记录 warning 而非静默 |
| G1-10 | api/routers/workflow_router.py:32-51；api/rate_limit.py:22-42 | 进程内限流 dict 永不清空过期 IP 桶，内存随 IP 数增长 | 性能 | P3 | 定期清理过期桶 |
| G1-11 | api/routers/weather_router.py:21-93 | `_COVERAGE_CACHE` 全局 dict 无锁（多线程竞争） | 正确性 | P3 | 加锁/用 functools |
| G1-12 | api/routers/artifact_router.py:13-34 | /artifacts/{id} 无鉴权 GET（为前端 img 设计使然），但算法结果可被未授权枚举读取 | 安全 | P3 | 增加可选 read key/来源限制 |
| G1-13 | services/coordinate_transform_service.py:1-101 | 已 deprecated 垫片仍被 tile_proxy_service 引用，迁移未完成 | 可维护性 | P3 | 排期移除 |

## 3. G2 任务与运行问题
| ID | 文件:行 | 问题 | 维度 | 严重度 | 修复建议 |
|---|---|---|---|---|---|
| G2-01 | services/workflow_timer_service.py:487-549 | update_timer 对 payload_overrides 无类型/schema 校验，非序列化值 json.dumps 500 | 正确性 | P3 | 校验 dict + 可序列化 |
| G2-02 | 全仓（backend/app 主服务） | 后端仅 12 个测试文件（11 个在 gee/core + 1 个 celery e2e）；app 的 routers/services/tasks/workflow 子包**零测试**；algorithms 仅 conftest.py；前端 0 测试。workflow submission/lifecycle、download 链、SSRF、timer tick 均无回归保障 | 测试覆盖 | P2 | 为核心路径补 pytest/vitest |
| G2-03 | services/workflow_request_resolver.py（1125 行） | 单文件过大，可继续拆分（submission/lifecycle/retry 子包已拆得不错） | 可维护性 | P3 | 后续拆分 |

## 4. G3 前端问题
| ID | 文件:行 | 问题 | 维度 | 严重度 | 修复建议 |
|---|---|---|---|---|---|
| G3-01 | composables/workflow-validator.ts:100-110 | isValidYYYYMMDD 只查 y/m/d 范围，未校验月内天数（如 20240231 通过）→ 与后端模板校验不一致 | 契约/正确性 | P3 | 用 Date 构造校验 |
| G3-02 | stores/weather-tile-manager.ts（2064 行） | 单文件过大；services/weather-tile-api.ts:63-67 normalizeProviderPart 与后端 normalize_provider_id 人工对齐 | 可维护性 | P3 | 抽公共常量/拆模块 |

## 5. G4 算法包问题
| ID | 文件:行 | 问题 | 维度 | 严重度 | 修复建议 |
|---|---|---|---|---|---|
| G4-01 | ingest/fy_preprocess.py:220-221,407,466,493-494,517,565,573,661-662,681 | 大量 `subprocess.run(cmd, shell=True)` 字符串拼接；路径参数来自 algorithm_params，含 `"`/`$()` 有命令注入风险 | 安全 | P2 | 改 list 参数或 shlex.quote |
| G4-02 | algorithms/omega_sf.py:1345-1346 | `pickle.load` 反序列化 output_dir 下 checkpoint（路径受算法参数影响），外部可放置文件则 RCE | 安全 | P2 | 换 JSON/safe 格式或校验路径归属 |
| G4-03 | algorithms/omega.py（2579 行）、debug_omega_profile.py、debug_station.py:5（硬编码 d:/Workspace/...） | 巨型文件与调试脚本混入发布包 | 可维护性 | P3 | 拆分/移出 |

## 6. 已修项复核结论（BUG-1~4）
- **BUG-1 SSRF 重定向：未彻底。** safe_urlopen 已实现逐跳校验+IP 钉死（core/ssrf.py:239-292），source_fetcher 已接入；但 tile_proxy(httpx follow_redirects)、weatherengine client、weatherapi/openweather、weather_router coverage probe、weather_engine_settings 仍走裸 urlopen/httpx（见 G1-02/03）。
- **BUG-2 finalize 跳过 watchdog-failed：已修复。** lifecycle_service.py:257-272 `_is_protected_terminal` 拦截 cancelled 与 stuck_running_watchdog 的 success/failure 覆盖，复核通过。
- **BUG-3 BACKEND_TRUST_PROXY：部分修复。** rate_limit.py:63 已按 trust_proxy 判断；但 workflow_router._get_client_ip（G1-05）未同步，events 轮询限流仍可被伪造头绕过。
- **BUG-4 materialize empty：已修复。** workflow_router.py:329-397 对无 products 的 run 走磁盘 block 目录扫描兜底，空结果返回 layers=[] 而非 500；demo:// 在 production 由 DemoSourceFetcher（source_fetcher.py:384-389）拦截，闭环通过。

## 7. 代码健康度结论
**⚠️ 良好但不完整。** 后端在安全工程上投入显著（SSRF 单点、environment 默认 fail-secure、API Key 加密存储、容量原子预留、看门狗保护终态），G2 workflow 子包（submission/lifecycle/retry/reuse）拆分清晰、注释与实现高度一致，前端 weather-tile-manager 与 weather-tile-api 的缓存键与后端 tile_key 严格对齐，算法包 data_access/contracts 分层规范。主要短板：① overlay `time` 参数路径穿越未闭环（P1，必须修）；② SSRF 防护只覆盖了 source_fetcher 一条路径，tile 代理/天气 provider/探针仍裸出网；③ 测试覆盖几乎为零（后端核心 0 测试、算法 0 测试、前端 0 测试），与如此大的代码量不匹配，P0/P1 修复后建议至少为 SSRF、overlay 路径解析、workflow lifecycle 补回归测试。

---

## 勘误
（补充说明：G1-01 行最初消息中存在一处字符编码残缺，已修正为"可读任意 .json/.mat/.nc/.h5/.tif（配合 `*` 通配符放大）"，本文件即为修正后正文。）
