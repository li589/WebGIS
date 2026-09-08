# CGDA 全面代码审查 — 问题汇编分级（Phase 4）

> 汇编：主理人齐活林 ｜ 2026-08-07
> 输入：Phase 1 架构清单 + Phase 2 代码清单 + Phase 3 契约清单 + Phase 0 基线

## 1. 基线（Phase 0）

| 门禁 | 结果 |
|------|------|
| 后端 pytest（Test/backend） | 585 passed / **5 failed**（4 个 WIP 测试漂移 + 1 个 SMAP catalog 遗留） |
| 算法 pytest（Test/algorithms） | 327 passed / 0 failed |
| 前端 vitest | 516 passed / 104 文件 |
| 前端 build | ✅ 通过（1 个非阻塞 INEFFECTIVE_DYNAMIC_IMPORT 警告） |
| check:openapi | ✅ OK |
| eslint | **5 errors / 36 warnings**（3 个可 --fix） |
| 全量 pytest（backend+algorithms 合并） | ❌ 两个 conftest sys.path 叠加把 `algorithms` 劫持到内层 → 收集错误；**约定分开跑** |

## 2. 问题分级汇总

### P0（阻断）— 0 项
无崩溃/数据丢失级问题。

### P1（高，本 Phase 修复）— 3 项
| ID | 来源 | 位置 | 问题 | 建议 |
|----|------|------|------|------|
| G1-01 | Phase2 | `Code/backend/app/services/overlay_registry.py:122,149` + `layer_router.py` | **路径穿越**：resolve_bounds/resolve_source_path 未校验 `time_list`（resolve_png 有），用户可控 `time` 拼接进路径 + `*`/`?` 通配符 glob；未鉴权 GET `/overlay-bounds`、`/overlay-value`、`/overlay-tiles` 可读服务器任意 .json/.mat/.nc/.h5/.tif | 解析前校验 `t in self.time_list`；解析后做 overlay_dir 包含性检查；value 采样同 |
| C1 | Phase1 | `tasks/open_meteo_sync_tasks.py:110` + `weather_router.py:180` + `launch/cli.py:209` | sync 三入口（Beat/UI/launch）均直接 `docker compose run` 写同一 named volume，**无全局互斥**，可并行写损坏；现成 `acquire_dedup_lock` 未接线 | sync 入口统一加 Redis SET NX 锁（key=sync:{domains}），持锁失败跳过/409；本地线程加 threading 锁 |
| C2 | Phase1 | `weather_router.py:21,25` | `_LOCAL_SYNC_JOBS`、`_COVERAGE_CACHE` 仅进程内存：多 worker 下 status/coverage 请求落到其他进程 → 404 / 重复探针打上游 | sync job 状态落 Redis(TTL) 或 DB；coverage 结果落 Redis |

### P2（中，本轮尽量修）— 17 项
| ID | 来源 | 位置 | 问题 |
|----|------|------|------|
| G1-02 | Phase2 | `tile_proxy_service.py:237` | httpx follow_redirects=True 无 SSRF 校验 |
| G1-03 | Phase2 | `weatherengine/client.py:333`、`weatherapi_provider.py:343`、`openweather_provider.py:337`、`weather_router.py:52`、`weather_engine_settings.py:140` | 多处裸 urlopen 未走 safe_urlopen |
| G1-04 | Phase2 | `source_fetcher.py:212-291` | file:// 可读任意本地文件（admin gate 缓解） |
| G1-05 | Phase2 | `workflow_router.py:59-66` | _get_client_ip 未同步 trust_proxy 修复（BUG-3 不完整） |
| G1-06 | Phase2 | `layer_router.py:50-69` | 每请求新建 ThreadPoolExecutor(8) |
| G1-07 | Phase2 | `workflow_tasks.py:252-263`、`weather_router.py:295-320` | 每派发新建 executor + 超时后线程仍完成 → 重复派发 |
| G1-08 | Phase2 | `download_orchestrator.py:472-478` | template.format 只捕 KeyError/IndexError，ValueError → 500 |
| G1-09 | Phase2 | `workflow_router.py:293,372-373` | 私有方法调用 + except Exception: continue 吞错 |
| G2-02 | Phase2 | 后端核心服务 | 零测试覆盖（GEE 除外） |
| G4-01 | Phase2 | `ingest/fy_preprocess.py:220-681` | 大量 shell=True 拼接，命令注入风险 |
| G4-02 | Phase2 | `algorithms/omega_sf.py:1345` | pickle.load 反序列化 checkpoint，RCE 风险 |
| D1 | Phase1 | 前端 3 个 store | store 反向 import components/map，依赖倒置 |
| D2 | Phase1 | `stores/layers/index.ts` | god store 4464 行/~80 导出 |
| C3 | Phase1 | `celery_app.py:53` | worker_pool=solo 无并行 |
| C4 | Phase1 | workflow_repository 等 4 库 | SQLite 状态机无 CAS 乐观锁 |
| R1 | Phase1 | `source_fetcher.py:239,325` | read_bytes 全量进内存，8GB 上限 OOM 风险 |
| ~~R2~~ | ~~Phase1~~ | ~~`redis_client.py:30`~~ | ~~断路器 threshold=1 过敏感~~ **✅ 已修复（2026-08-12）** |

契约 P2：~~D-1（Task* 死契约）~~ **✅ 已清除**、~~D-2（OpenAPI 无 securitySchemes）~~ **✅ 已完成**、N-1/N-2（Celery title 非 US-ASCII ×3，Phase 5 已修）、~~N-3（hPa 字段非 snake_case，两端一致，白名单化）~~ **✅ 已完成**、~~N-4（6 个时间戳 str 未强制 ISO8601）~~ **✅ 已完成**（均 2026-08-12）

### P3（低，合并建议）— 记录不阻塞
L4/D3/X3/遗留项（god store 拆分方案 §4）/G1-10/G1-11/G1-12/G1-13/G2-01/G2-03/G3-01/G3-02/G4-03/R3/X1/X2 + lint 36 warnings

## 3. 修复范围（Phase 5）

**必修（P1×3）**：G1-01 路径穿越、C1 sync 互斥、C2 内存态落 Redis
**回归修复**：后端 5 failed（4 个 WIP 测试漂移 + 1 个 SMAP catalog）
**质量门**：eslint 5 errors → 0（36 warnings 保留）
**契约快赢（P2 低风险）**：N-1/N-2 US-ASCII title、D-1 死契约清理

其余 P2 记入 backlog 标注建议，不在本轮修复范围（避免过度改动破坏 WIP 工作区）。
