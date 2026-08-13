# 审查修复执行记录（v3 / brooks-lint，2026-08-14）

承接 [fix-review-b2b3-round2-2026-08.md](./fix-review-b2b3-round2-2026-08.md) 与 [详细修复计划-v3](../../.trae/documents/详细修复计划-v3.md)。

## 修复范围

基于 brooks-lint 代码审查（29 项发现）与 build-web-apps 前端测试调试视角，聚焦**前端运行质量**（内存泄漏、类型安全、错误处理、性能、可观测性）与**后端安全/并发**两项阻断项。v2 计划中已确认完成的 `except Exception` noqa 标注（RBAC v2 提交 `10b7eb1`）、runtime_router 编码修复、useSidebarSearch deep watch 优化等不再重复。

## 已落地

### P0 — 阻断级

| ID | 文件 | 改动摘要 |
|----|------|----------|
| P0-1 | `Test/backend/test_business_regression.py` | `check()` 函数追加 `assert condition`，修复 pytest 下静默失败；`import pytest` 移至文件顶部 |
| P0-2 | `Code/backend/app/api/routers/artifact_router.py` | `/artifacts/{id}` 与 `/artifacts/{id}/preview.png` 添加 `get_request_user` 认证依赖；`_deny_if_unauthenticated` 守卫 `user_auth_enabled` 门控；OpenAPI 重导 + gen:types 同步 |

### P1 — 高优先级

| ID | 文件 | 改动摘要 |
|----|------|----------|
| P1-1 | `Code/backend/app/gee/core/src/webgis_gee/gee/context.py` | **最终保留类级 `_runtime_lock`**（多账号并发 `ee.Initialize` 仍需全局串行）。曾试改为实例锁以减瓶颈，审查后回滚：ee 运行时共享状态不安全 |
| P1-2 | `Code/frontend/src/stores/analysis-runner.ts` | `watchRun()` 30 分钟轮询循环改为可取消：`cancelableSleep()` + `watcherCancellers` Map + `onScopeDispose` 统一清理；防止组件卸载后定时器泄漏 |
| P1-3 | `Code/frontend/src/stores/layers/workflow-runner.ts` | 移除 12 处 `as Record<string, unknown>` 类型断言；`run.layer_id` / `run.command_label` 直接安全访问 |
| P1-4 | 多文件（stores/composables 关键路径） | `safeLog()` 工具函数（try/catch 包裹 `useLogStore().logOperation`，无 Pinia 时 no-op）；stores 层 `console.error/warn` 接入业务日志系统；WebGL 渲染层保持 console 不变 |

### P2 — 中优先级

| ID | 文件 | 改动摘要 |
|----|------|----------|
| P2-1 | `workflow-timers.ts`、`useWeatherCoverage.ts`、`weather-reconcile.ts` | fire-and-forget 异步调用补全 `.catch()`；`weather-reconcile.ts` 用 `instanceof Promise` 守卫 `void | Promise<void>` 返回类型 |
| P2-2 | `Code/frontend/src/services/_http.ts` | 移除 L289-295 不可达死代码（`AbortError` + `!restInit.signal?.aborted` 分支永远不会执行） |
| P2-3 | `Code/frontend/src/stores/weather-tile-manager.ts` | `buildMergeStats` + 正则解析（`:z(\d+):` / `:x(\d+):` / `:y(\d+):`）包裹在 `if (isPerfEnabled())` 中；非 debug 模式跳过每瓦片正则开销 |
| P2-4 | `Code/frontend/src/stores/ui.ts` | `layerTimeMemory` watcher 移除 `{ deep: true }`；`rememberLayerTime()` 使用展开赋值（引用替换），浅监听即可触发 |
| P2-5 | `Code/frontend/src/views/dashboard/useTimelineSync.ts` | `workflowProgressTimeSeek` 参数类型从 `Ref<unknown>` 改为 `Ref<WorkflowProgressTimeSeekHint \| null>`；移除 3 处 `hint as { catalogId: string }` 类型断言；移除 `void currentHour.value` / `void currentDate.value` 冗余依赖追踪（两者在 computed body 所有分支中均已访问），保留其余 void 并加注释 |

### P3 — 低优先级

| ID | 文件 | 改动摘要 |
|----|------|----------|
| P3-1 | `Code/backend/app/services/circuit_breaker.py` | 模块 docstring 追加未接线状态说明：当前由 `weatherengine/client.py` 内联实现，registry 暂未接线，统一属大重构，保留供未来使用 |

## 验证

| 验证项 | 命令 | 结果 |
|--------|------|------|
| 后端回归测试 | `Env/Python312/python.exe -m pytest Test/backend/test_business_regression.py -p no:cacheprovider --basetemp="Test/.pytest-v3" -q` | 9 passed |
| 前端全量测试 | `cd Code/frontend && npm run test -- --run` | 669 passed (125 files) |
| 前端 lint | `cd Code/frontend && npm run lint` | clean (0 errors) |
| 前端构建 | `cd Code/frontend && npm run build` | success |
| OpenAPI 契约 | `cd Code/frontend && npm run check:openapi` | OK (176 paths, 202 schemas) |

## 设计决策记录

1. **artifact 认证不含所有权校验** — artifact 无 owner 字段，通过全局 `user_auth_enabled` 门控即可满足发布边界，避免过度设计。
2. **GEE 锁保持类级串行** — `ee` 全局运行时在多账号切换时仍可能串状态；实例锁会放开并发 Initialize。账号池吞吐瓶颈另案优化（进程隔离 / 单账号 worker），本轮不放开类级锁。
3. **circuit_breaker 不统一** — 两套实现参数/行为不同（client.py 内联实现有类级共享锁、独立参数），统一属大重构，本轮仅加注释降级为 P3。
4. **前端 console 双写模式** — 保留 `console.*` 作开发调试，追加 `safeLog` 接入业务日志；WebGL 渲染层（wind-particle、overlay-image-module）保持 console 不变。
5. **ui.ts deep watch 移除安全** — `rememberLayerTime()` 使用 `layerTimeMemory.value = {...}` 展开赋值，无原地突变路径（`delete` / 属性直写），浅监听即可。
6. **timelineSegments void 依赖部分移除** — `currentHour.value` 和 `currentDate.value` 在 computed body 所有分支中均被访问，void 追踪冗余；其余 void（`weatherStatusVersion`、`weatherActivityVersion`、`weatherCoverage`、`overlayTimeStates`、`selectedActiveLayer`、`jobLayers`、`runLayerGroups`）在部分分支中未被访问，保留并加注释确保跨路径响应式。

## 仍未纳入（后续技术债务）

- `circuit_breaker.py` registry 与 `weatherengine/client.py` 内联实现统一（大重构）
- `workflow-runner.ts` 手写 DTO 全面迁 `gen:types` / `api-reexports`
- Settings 组件级集成测试（ApiKeySettings 勾选持久化等）
- god-store 续拆（layers / weather-tile / WorkflowCanvas）

## 同期运维补强（同批提交）

- Gateway 维护页合并到 `Code/infra/gateway/maintenance/html/`（开关仍为同级 `on`）；升级时挡 SPA、放行 API。
- `launch.py clean-cache`：清本地 `__pycache__` / Vite `.vite`；与 `flush`（Redis + 天气文件缓存）隔离。代码更新后推荐 `clean-cache` 再 `restart`（或 `restart --clean-cache`）。
- FE 虚拟合并图层 `soil-moisture`：侧栏源选择禁止在 render 中写状态；`addLayer` 拒绝虚拟 catalogId 直达后端。
