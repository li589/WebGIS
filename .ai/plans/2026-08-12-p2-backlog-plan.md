# P2 Backlog 计划（2026-08-12）

> 真源：本文件 + [工程收口仪表盘](../docs/reference/工程收口仪表盘.md) + [pending-tasks-audit](../progress/2026-08-04-pending-tasks-audit.md)。
> 来源审查：Phase 1 架构 / Phase 2 代码 / Phase 3 契约 / Phase 4 汇编 / Phase 5-6 交付 / 2026-08-11 global-code-review。
> 排期原则：安全 > 架构收敛 > 并发可靠 > 测试 & 功能。

## 1. 已完成项（2026-08-12 快速收口）

| 编号 | 主题 | 状态 | 证据 |
|------|------|------|------|
| R2 | 断路器 threshold 调参 | ✅ | `redis_client.py` threshold 1→3 + 指数退避 |
| D-1 | Task* 死契约清除 | ✅ | `api_contracts.py` / `openapi.json` 无 Task* 残留 |
| D-2 | OpenAPI security schemes | ✅ | `main.py` SessionAuth + BearerAuth |
| N-1/N-2 | Celery title 非 US-ASCII | ✅ | Phase 5 已修（"GEE Export Status" / "Lab Model Output"） |
| N-3 | hPa 字段单位语义 | ✅ | 9 个 Field(description=...) |
| N-4 | 时间戳类型化 | ✅ | `OpenMeteoSyncStatusResponse` + `response_model` |
| L2 | Ghost uvicorn 修复 | ✅ | `launch/commands.py` pattern + `spawn_main` + `uvicorn` |

## 2. 剩余 P2 项总览

共 **17 项**，分 4 波。每波内部可并行，波间有弱依赖。

### Wave 1 — 安全加固（10 项，建议优先）

> 风险最高、改动局部化、不涉及架构调整。

| 序 | ID | 来源 | 位置 | 问题 | 建议修法 | 预估 | 验证 |
|----|-----|------|------|------|---------|------|------|
| 1-1 | G1-02 | Phase2 | `tile_proxy_service.py:237` | `httpx.AsyncClient(follow_redirects=True)` 无 SSRF 校验 | 关闭 follow_redirects 或逐跳 `resolve_outbound_target` 校验 | 0.5d | pytest `test_tile_proxy_service.py` + 手工重定向拦截 |
| 1-2 | G1-03 | Phase2 | `client.py:333` / `weatherapi_provider.py:343` / `openweather_provider.py:337` / `weather_router.py:52` / `weather_engine_settings.py:140` | 5 处裸 `urlopen` 未走 `safe_urlopen` | 统一改 `core/ssrf.safe_urlopen` | 0.5d | grep 确认无裸 urlopen；各 provider 单测 |
| 1-3 | G1-04 | Phase2 | `source_fetcher.py:212-291` | `file:///` 可读任意本地文件 | 限制 `source_uri` 在 `download_source_root` 配置根内（Path.resolve + is_relative_to） | 0.5d | `test_source_fetcher.py` 穿越 matrix |
| 1-4 | G1-05 | Phase2 | `workflow_router.py:59-66` | `_get_client_ip` 无条件信任 X-Forwarded-For | 复用 `rate_limit.client_ip` 逻辑（按 `trust_proxy` 判断） | 0.5d | `test_workflow_routes.py` 伪造头用例 |
| 1-5 | G1-06 | Phase2 | `layer_router.py:50-69` | 每请求新建 `ThreadPoolExecutor(8)` | 复用模块级共享池 + 就绪结果 30s 短缓存 | 0.5d | `test_layer_routes.py` 并发 /layers 基准 |
| 1-6 | G1-07 | Phase2 | `workflow_tasks.py:252-263` / `weather_router.py:295-320` | 每派发新建 executor + 超时后线程仍完成 → 重复派发 | 共享 executor + 幂等键去重 | 1d | `test_celery_tasks.py` 超时去重用例 |
| 1-7 | G1-08 | Phase2 | `download_orchestrator.py:472-478` | `template.format()` 未捕获 ValueError → 500 | 捕获 ValueError 返回 None | 0.25d | `test_download_orchestrator.py` 格式异常用例 |
| 1-8 | G1-09 | Phase2 | `workflow_router.py:293,372-373` | 调用私有方法 `_build_product_map_layer_refs` + `except Exception: continue` 吞错 | 改公开方法；`except Exception` 改 `logger.warning` 记录 | 0.5d | `test_workflow_routes.py` block upsert 错误传播 |
| 1-9 | G4-01 | Phase2 | `ingest/fy_preprocess.py:220-681`（10 处） | `subprocess.run(cmd, shell=True)` 字符串拼接，命令注入风险 | 改 list 参数或 `shlex.quote` | 1d | `test_fy_preprocess.py` 注入 payload matrix |
| 1-10 | G4-02 | Phase2 | `algorithms/omega_sf.py:1345-1346` | `pickle.load` 反序列化 checkpoint，RCE 风险 | 换 JSON / `torch.load(weights_only=True)` 或校验路径归属 | 0.5d | `test_omega_sf_checkpoint.py` 恶意文件拦截 |

**Wave 1 小计**：~5.25 人天；目标：消除全部 P2 级安全漏洞。

### Wave 2 — 架构收敛（7 项，可在 Wave 1 后并行推进）

> 提升可维护性，降低后续开发摩擦。部分项有跨模块影响。

| 序 | ID | 来源 | 位置 | 问题 | 建议修法 | 预估 | 验证 |
|----|-----|------|------|------|---------|------|------|
| 2-1 | D2 | Phase1 | `stores/layers/index.ts`（4464 行/~80 导出） | god store 未完全拆分 | 按 Phase1 §4 方案拆为 `useLayerWorkspaceStore` / `useWorkflowRunStore` / `useLayerViewportStore`；`index.ts` 仅留 re-export | 3d | `cd Code/frontend && npm run test && npm run build` |
| 2-2 | D1 | Phase1 | `weather-tile-manager.ts:18` / `layers/index.ts:25` / `overlay-symbology.ts:7` | store 反向 import components/map | `normalizeLngBounds` / `renderHint` 等下沉 `src/utils`，store 只依赖 services/utils | 1d | eslint `no-restricted-imports` 规则；`npm run test` |
| 2-3 | L1 | Phase1 | `weather_router.py:180` | trigger_open_meteo_sync 在 router 内 ~90 行业务编排 | 抽取 `services/weather_sync_service.py`，router 只留 HTTP 壳 | 0.5d | `test_weather_routes.py` 不变 |
| 2-4 | L2 | Phase1 | `workflow_router.py:218` | materialize_workflow_map_layers 含 ~180 行磁盘扫描 | 下沉到 `services/python_provider_result_builder` 域 | 1d | `test_workflow_routes.py` materialize 回归 |
| 2-5 | L3 | Phase1 | `weatherengine/service.py`（2436 行）/ `config_service.py`（1635 行） | 两个 god 模块 | 按域拆分：渲染原语构建器（`weatherengine/builders/`）、配置域仓储（`services/config/` 子包） | 3d | `pytest Test/backend -q` 全量回归 |
| 2-6 | X1 | Phase1 | `layer_catalog.py` / `weatherengine/constants.py` / `catalog.ts` | 图层注册表三处真源 | 统一为后端下发 schema，前端消费，消灭手工同步 | 2d | `npm run check:catalog` + `GET /layers` schema 校验 |
| 2-7 | X2 | Phase1 | `fetch_gateway.py:229` | 商业源稀疏网格不可用于瓦片是隐式规则 | 提升为 provider 能力声明 `grid_density=dense|sparse` | 0.5d | `test_fetch_gateway.py` sparse 源 404 用例 |

**Wave 2 小计**：~11 人天；目标：god store / god 模块拆分完成，依赖方向归正。

### Wave 3 — 并发与可靠性（3 项）

> 面向生产部署可靠性，当前单机构环境可容忍但规模化后风险放大。

| 序 | ID | 来源 | 位置 | 问题 | 建议修法 | 预估 | 验证 |
|----|-----|------|------|------|---------|------|------|
| 3-1 | C3 | Phase1 | `celery_app.py:53` | `worker_pool="solo"` 无并行，concurrency 无效 | 生产 Linux 切 `prefork` + `concurrency` 按队列分配；solo 保留为 Windows 开发兜底（settings 分支） | 1d | `pytest test_celery_tasks.py`；Linux 实机 prefork 冒烟 |
| 3-2 | C4 | Phase1 | `workflow_repository.py` 等 4 库 | SQLite 状态机无 CAS 版本号，竞态可致状态回滚 | run 状态更新加 `WHERE status=<期望前态>` 乐观锁，冲突重读（3 次） | 1.5d | `test_workflow_repository.py` 并发转移用例 |
| 3-3 | R1 | Phase1 | `source_fetcher.py:239,325` | `read_bytes()` 全量进内存，8GB 上限 OOM | 流式拷贝 `shutil.copyfileobj` / 分块上传到 object_store | 1d | `test_source_fetcher.py` 大文件流式用例 |

**Wave 3 小计**：~3.5 人天；目标：生产并发安全性达标。

### Wave 4 — 测试覆盖与功能补全（3 项）

> 质量基线与残留功能。

| 序 | ID | 来源 | 位置 | 问题 | 建议修法 | 预估 | 验证 |
|----|-----|------|------|------|---------|------|------|
| 4-1 | G2-02 | Phase2 | 后端 `app/` 核心服务 | routers/services/tasks/workflow 子包零测试覆盖 | 为 SSRF、overlay 路径解析、workflow lifecycle、download 链补回归 pytest | 3d | 覆盖率从 ~0 → 核心路径 >60% |
| 4-2 | SMAP | Phase5/6 | catalog | DEC2025 全量迁移 | catalog 数据迁移 + catalog seed 更新 | 0.5d | `GET /layers` 含 SMAP_L3_DEC2025；`check:catalog` |
| 4-3 | P-02 | Phase5/6 | 前端时间轴 | 时间轴 seek（可选增强） | 前端交互实现 | 1d | 手工目视 + vitest |

**Wave 4 小计**：~4.5 人天；目标：核心路径测试覆盖 + 数据迁移。

## 3. 依赖与并行度

```
Wave 1 (安全) ──────► 可独立并行，互不依赖
                      │
Wave 2 (架构) ──────► D2(god store) 独立；L1/L2 可在 Wave 1 后；L3 可与 D2 并行
                      │
Wave 3 (并发) ──────► C3 依赖 settings 分支；C4 独立；R1 独立
                      │
Wave 4 (测试) ──────► G2-02 最好在 Wave 1-2 修完后补测试
```

**建议执行顺序**：Wave 1 → Wave 2 (D2 + L3 并行) → Wave 3 → Wave 4。
**总预估**：~24 人天（单人）；2 人并行约 14 人天。

## 4. P3 项（不排进本轮，记录备查）

| ID | 主题 | 说明 |
|----|------|------|
| L4 | effective_config 访问 config_service 私有函数 | 提公共接口 |
| D3 | 176 处服务间交叉 import | 抽共享契约层 |
| X3 | ApiConfigManager 与 effective_config 双读路径 | 收敛为单入口 |
| R3 | 进程 LRU 内存放大 | 接受现状，Redis 为权威缓存 |
| G1-10 | 限流 dict 不清理过期桶 | 定期清理 |
| G1-11 | _COVERAGE_CACHE 无锁 | 加锁（Phase 5 已部分落 Redis） |
| G1-12 | /artifacts/{id} 无鉴权 GET | 增加可选 read key |
| G1-13 | coordinate_transform_service deprecated 垫片 | 排期移除 |
| G2-01 | timer payload_overrides 无类型校验 | 校验 dict + 可序列化 |
| G2-03 | workflow_request_resolver 1125 行过大 | 后续拆分 |
| G3-01 | isValidYYYYMMDD 未校验月内天数 | 用 Date 构造校验 |
| G3-02 | weather-tile-manager 2064 行 | 抽公共常量/拆模块 |
| G4-03 | omega.py 2579 行 + 调试脚本混入 | 拆分/移出 |

## 5. 平台 backlog（非本期 P3+）

PostGIS / Cesium 主链 / deck.gl / TiTiler / Martin / 全站容器化 / SSE — 不排进当前 sprint。

## 6. 风险与约束

- **WorkBuddy safe-delete shim**：本地跑 pytest 须前缀 `CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX=`。
- **Windows Docker 须管理员**：启动 Docker Desktop + 终端须以管理员身份运行。
- **唯一解释器**：`Env/Python312/python.exe`，勿用系统 PATH。
- **勿默认 flush Redis**：dispatch 不确定依赖 watchdog 回收。
- **前端预存问题**：`IconButton.vue` return-in-computed-property lint error；`basemap-module.ts` overlayUrlTemplate build error — 均非本次引起，需单独修。

## 7. 验收检查表

每波完成后执行：

```bash
# 后端/算法测试
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= \
  Env/Python312/python.exe -m pytest Test/backend -q -p no:cacheprovider --basetemp="Test/.pytest-be"

# 前端测试
cd Code/frontend && npm run test

# 契约校验
npm run check:openapi && npm run check:catalog

# lint / build
npm run lint && npm run build

# 提交前
pre-commit run --all-files
```

## 8. 相关链接

- [工程收口仪表盘](../docs/reference/工程收口仪表盘.md)
- [2026-08-04-pending-tasks-audit](../progress/2026-08-04-pending-tasks-audit.md)
- [2026-08-12-p2-quick-wins](../progress/2026-08-12-p2-quick-wins.md)
- [Phase 1 架构审查](../progress/2026-08-07-review-phase1-arch.md)
- [Phase 2 代码审查](../progress/2026-08-07-review-phase2-code.md)
- [Phase 3 契约审查](../progress/2026-08-07-review-phase3-contract.md)
- [Phase 4 汇编分级](../progress/2026-08-07-review-phase4-consolidated.md)
- [Phase 5/6 交付报告](../progress/2026-08-07-review-phase5-6-delivery.md)
- [2026-08-11 global-code-review](../progress/2026-08-11-global-code-review.md)
