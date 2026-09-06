# CGDA 全面代码审查计划（2026-08-07）

> 触发：用户要求"熟悉项目结构和规划，制定计划进行全面代码审查"。
> 本计划为**编排层规划**，经确认后按团队 SOP 执行（架构师 → 工程师 → QA → 回归）。

## 0. 背景与目标

- 项目已进入工程化落地阶段：`workflow-runs` 主链、天气瓦片、Celery/Redis/MinIO 均可用；测试基线全绿（后端 **489** / 算法 **306** / 前端 **439**）。
- 历史已做过**局部**审查，本次目标是**全仓、全维度**的系统性审查，识别盲区，产出可追踪的问题清单：

| 历史审查 | 范围 | 与本计划关系 |
|---------|------|-------------|
| `代码审查纪要-2026-07-21` | Open-Meteo 运行/数据拆分、Celery Beat、前端加载 | 结论并入本计划输入，不重复审查 |
| `workflow_scheduling_audit_report`（08-04） | 调度 P0（cancel/reuse） | 已闭环；P1 项纳入重点复核 |
| `hardcode-extension-audit`（08-05） | 硬编码扩展审计 | 结论并入输入 |
| `post-commit-bug-review`（08-05） | 提交后全量缺陷（SSRF 等） | **已修项做回归复核，不重审** |

## 1. 审查范围（按模块分组）

| 分组 | 路径 | 规模 | 优先级 |
|------|------|------|--------|
| G1 后端核心 | `Code/backend/app/api/`、`app/services/`、`app/core/`、`app/weatherengine/` | ~244 py | **P0** |
| G2 后端任务/运行 | `app/tasks/`、`app/weatherengine/`、`config_routes.py`、`tile_routes.py` | 同上 | **P0** |
| G3 前端 | `Code/frontend/src/`（views/components/stores/composables/services） | ~248 ts/vue | **P0** |
| G4 算法包 | `Code/algorithms/`（providers/Python 全量） | ~187 py | P1 |
| G5 契约 | `Code/shared/contracts/` + 前端 `api-contracts.ts` + OpenAPI drift | 35 | **P0** |
| G6 基础设施 | `launch.py`、`Code/infra/`、`docker-compose.yml`、`Test/` 组织 | — | P1 |

## 2. 审查维度（每模块六维度）

| 维度 | 检查要点 |
|------|---------|
| **安全** | 鉴权/`X-API-Key`、SSRF（重定向再校验）、路径穿越、凭据加密落库、限流绕过、`demo://`/占位开关 |
| **正确性** | 边界条件、并发竞态、时空精度（CRS/Mercator/瓦片归属）、错误处理、Celery 元数据 US-ASCII |
| **性能** | N+1、缓存策略（LRU/TTL/覆盖签名）、瓦片渲染、Redis 使用（SCAN 而非 KEYS）、大文件流式 |
| **可维护性** | god store 拆分进度、重复代码、死代码、命名、注释、分层边界 |
| **契约一致性** | snake_case、ISO 8601、枚举小写、shared 单一事实来源、OpenAPI drift 为零 |
| **测试覆盖** | 关键路径有无测试、断言真实性、测试是否被 `noqa`/放宽掩盖问题 |

## 3. 团队分工

| 成员 | 职责 |
|------|------|
| 主理人（齐活林） | 编排、上下文中转、问题清单汇总分级、报告汇编 |
| 架构师（高见远） | G1 架构级审查：模块边界、依赖图、Layers god store 拆分评估、性能架构 |
| 工程师（寇豆码） | G1–G4 逐文件代码级审查、缺陷定位、修复建议（最小变更原则） |
| QA（严过关） | G5 契约审查、测试覆盖审计、回归验证门禁、OpenAPI drift |

> 消息流经主理人中转；成员间不直连。

## 4. 执行流程（SOP）

```text
Phase 0  基线采集：全量测试 + lint + build + check:openapi（记录基线数字）
Phase 1  架构审查（架构师）：分层/依赖/god store/性能架构 → 架构问题清单
Phase 2  代码审查（工程师）：G1→G4 逐模块六维度 → 代码问题清单
Phase 3  契约与测试审查（QA）：drift、命名、测试覆盖 → 契约/测试问题清单
Phase 4  主理人汇编：合并三清单 → P0/P1/P2/P3 分级 → 优先级排序
Phase 5  修复（工程师）：P0/P1（最小变更）→ QA 回归（全量测试不退化）
Phase 6  报告：审查报告落盘（含已知遗留项）
```

**质量关卡**：每阶段产出经主理人确认后才进入下一阶段；Phase 5 修复须回归通过。

## 5. 已知遗留问题（审查重点输入，优先复核）

| 项 | 状态 | 复核要点 |
|----|------|---------|
| Layers god store 未完全拆分 | 进行中 | `stores/layers/index.ts` 聚合入口边界 |
| confirm 端点 Mercator 往返 ~0.013° | 已知 | 是否需重设计 bounds |
| 时间轴 coverage 时区偏差（Asia/Shanghai vs 浏览器） | 已知 | 探针时区一致性 |
| sync 无全局互斥锁 | 已知 | Beat+UI+`launch.py sync` 并行写 volume |
| `_LOCAL_SYNC_JOBS` 仅内存、多进程不共享 | 已知 | FastAPI 多 worker 一致性 |
| P-02 时间轴 seek | 可选 | 是否本期处理 |
| NAS 实机 e2e 绿测 | 待数据环境 | 保持标注，不阻塞 |

## 6. 输出物

- `本计划`（.ai/plans/）
- `问题清单`：含位置（文件:行）/严重度/复现路径/修复建议，可追踪
- `审查报告`：按 G1–G6 分组结论 + 分级统计 + 已修/暂缓清单

## 7. 验收标准

1. G1–G6 每模块六维度均有明确结论（✅/⚠️/❌）
2. 问题清单按 P0/P1/P2/P3 分级，P0/P1 含修复建议
3. P0/P1 修复后全量测试不退化（后端/算法/前端）
4. OpenAPI drift 为零
5. 已知遗留项逐条给出"已处理/暂缓+理由"

## 8. 执行方式确认

- **A)** 批准本计划，按 Phase 0→6 全量执行（含 P0/P1 修复）
- **B)** 仅审查出报告（Phase 0–4 + 6），不修复
- **C)** 只审指定分组（如仅 G1+G5，或仅 G3）
- **D)** 计划需修改（说明改哪）
