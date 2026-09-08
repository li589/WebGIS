# CGDA 下一步工作规划（2026-08-16，事件恢复后）

> **进度（2026-08-16 当日）**：Wave 0 ✅（push 已执行、stash 已留档）；Wave 1 ✅（commit `2d45241`，18 新测试红→绿，16 套件回归 102/102）；Wave 2 ✅（commit `a1a355d`，演练记录 `Docs/04-执行部署/交付演练记录-2026-08-16.md`，checklist 已增补）；Wave 3.1/W3.2 ✅（B-N7/B-N8 测试基建：单文件直跑 7/7 绿；合并收集 1648 项 0 错误；**全量合并回归 1646 passed / 0 failed**——两套件首次同会话全绿；附带修复 local_root 测试的 settings 模块绑定隔离）；W3.3 ✅（commit `4f0ac54`：ci.yml 23 处 `uses:` 全部 sha pin——checkout v4.4.0 / setup-python v5.6.0 / setup-node v4.4.0 / pre-commit/action v3.0.1，sha 经 GitHub API 确认直指 commit；三份 requirements 全 `==` 锁 Env/Python312 实装版本；裸 pip install pytest/pytest-cov/pip-audit 一并锁版）；W3.4/W3.5/W3.6 ✅（2026-08-16 二段：前端覆盖率门达标并提阈值 30/32；B-N3 单域锁 + B-N2 retry 复用目录 claim；P-02 时间轴 seek 测试闭环 + 审计报告勾「已实施」；详见 Wave 3 表）。下一步：push 触发 CI 验证 sha pin 实效。

> 触发：用户指令「转会正规，看看下一步可以做哪些内容」（NTFS/VMCache 事件已结案，仓库状态全绿）。
> 方法：staff-engineer-mode 路由 → `production-readiness-review`（以交付就绪视角盘点差距 → 产出下一步工作项排序）。
> 依据（全部实读验证）：`.ai/plans/2026-08-15-code-review-execution.md`、`Docs/06-代码审查/问题清单-2026-08-15.md`、`.ai/plans/2026-08-12-p2-backlog-plan.md`、`Docs/01-协作规范/工程收口仪表盘.md`、`Docs/04-执行部署/delivery-checklist.md`、`Docs/05-专题研究/其它专题/workflow_scheduling_audit_report.md`，及本轮 grep 实证。

## 一、现状盘点（证据基线）

### 已闭环（无需重做）

- **两轮全面审查 + 修复**（08-15/16，commit `87e24ba`）：12/12 P1 全修（F1-F9 + B-R1~R3）；安全收敛 W-A1（AESGCM 五仓库收敛到 `secret_cipher.py`）、W-A2（legacy remote browser 下线）；全量回归终态：后端 **1217 passed / 0 failed**、算法 **411 passed + 28 subtests**、前端 **131 文件 736 全绿**、lint/build/check:openapi（190 paths）/check:catalog（55 items）全 OK。
- **遗留清单 L-1~L-15**：9 项闭环、4 项并入留痕、2 项未复检（N-11/N-12）。
- **仪表盘里程碑**：FY/SMAP 算法+UI 闭环、Open-Meteo Phase B/C/D、工作流调度 P0 与 V-01/V-02/P-01、Test 集中化、部署配置中心、品牌化 UI、结题文档——全部勾选完成。
- **NTFS 事件**：已结案（VMCache 清除 + 全链路验证），`git status` 干净、HEAD=`87e24ba`。

### 开放债务（本轮 grep/文档实证）

| 类别 | 项 | 状态证据 |
|------|----|---------|
| **版本风险** | dev 领先 origin/dev **7 个提交未推送** | `git log origin/dev..dev` = 7 条（`87e24ba`…`0a6aa52`） |
| **版本风险** | `stash@{0}` 08-12 WIP（19 文件）未处置 | `git stash list` 1 条 |
| **安全 P2** | G1-02 `tile_proxy_service.py:254` `follow_redirects=True` 无逐跳 SSRF 校验 | 本轮 grep 命中 |
| **安全 P2** | G1-03 裸 `urlopen` ×6：`weatherengine/client.py:355,375,525,860`、`weather_router.py:81`、`weather_engine_settings.py:141`（均 `from urllib.request import urlopen`，非 ssrf 包装） | 本轮 grep 命中 |
| **安全 P2** | G1-04 `source_fetcher.py::LocalFileSourceFetcher` 接受任意 `file:///` 绝对路径，无配置根约束 | 本轮实读 L228-268 |
| **P2/P3 留痕** | 08-15 清单 §3：P2 ×13 + P3 ×8（N-3/N-4/N-5/N-6/N-7/N-8、B-N1~N3、B-N7/N-8；N-9~N-12、B-N4~N6） | 问题清单 §3/§6 |
| **架构** | D2 god store（`stores/layers/index.ts` 仍为组合入口）；L3 god 模块（`weatherengine/service.py` 2436 行、`config_service.py` 1635 行）；X1 catalog 三处真源 | 仪表盘 Phase2 勾注 + backlog Wave 2 |
| **条件项** | 真实数据 e2e / 实机 NAS 绿测（需数据环境）；P-02 时间轴 seek；SMAP DEC2025 迁移；平台项（Cesium 主链/PostGIS/SSE） | 仪表盘 Phase3 + 调度报告 P-02 行 |

## 二、下一步工作项（按波次排序）

> 排序原则沿用项目既定约定（`.ai/plans/2026-08-12-p2-backlog-plan.md` §「安全 > 架构收敛 > 并发可靠 > 测试 & 功能」），并叠加一条前置原则：**版本落袋先于一切**——NTFS 事件已实证单盘持有 7 个未推送提交的持久性风险。

### Wave 0 — 版本落袋（立即，≤0.5 天）

| # | 项 | 动作 | 验证 |
|---|----|------|------|
| W0.1 | 推送 dev → origin/dev | `git push origin dev`（**可见动作，须用户确认**） | `git status`；`origin/dev` == `87e24ba` |
| W0.2 | 处置 `stash@{0}` | 先 `git stash show -p stash@{0}` 审阅 19 文件内容 → 与用户确认 apply（恢复工作）或 drop（废弃） | `git stash list` 空 |
| W0.3 | （可选）dev → main 合并 | 用户决定；上一次 main 合并为 `e759f04` | `git log main..dev` 空 |

### Wave 1 — 安全收尾（08-12 backlog Wave 1 尾巴，~2 天）

> 全部为已验证仍开放的 SSRF/越权读类 P2，改动局部、TDD 可红→绿。

| # | 项 | 修法（沿用 backlog §Wave1 既定方案） | 验证 |
|---|----|------|------|
| W1.1 | G1-02 瓦片代理重定向 SSRF | 关闭 `follow_redirects` 或逐跳 `resolve_outbound_target` 校验 | `pytest Test/backend/test_tile_proxy_service.py`；手工 302→内网地址拦截用例 |
| W1.2 | G1-03 裸 urlopen ×6 → `core/ssrf.safe_urlopen` | 六处调用点统一替换；`client.py:368` 已有 ssrf 导入可对齐 | grep 全仓 `urllib.request import urlopen` 于 `app/` 源码零命中（测试桩除外）；weather provider 单测 |
| W1.3 | G1-04 `file:///` 根约束 | `LocalFileSourceFetcher.fetch` 增加 `Path.resolve() + is_relative_to(download_source_root)` 校验，越界返回 FetchResult(success=False) | `pytest Test/backend/test_source_fetcher.py` 穿越 matrix（`../../etc`、盘外绝对路径、符号链接） |

完成后按 AGENTS.md「改 X 则跑 Y」补跑天气点查/引擎套件。

### Wave 2 — 交付演练（机构交付 Go/No-Go 证据，~1 天）

> 项目目标为单机构交付；两轮审查后代码侧已具备演练条件。产出物为**交付演练记录**（PRR Full 模板的执行起点）。

| # | 项 | 动作 | 验证 |
|---|----|------|------|
| W2.1 | 生产配置走查 | 按 `Docs/04-执行部署/delivery-checklist.md` 逐项核对：必改环境（DATA_ROOT/OUTPUT_ROOT/UI 重启/MinIO 非 minioadmin/GEE 加密 key）、生产禁止开关（DEMO_SOURCES/NODE_STUBS/RELOAD/TRUST_PROXY）、白标变量 | 演练记录表（每项 ✅/❌ + 证据命令输出） |
| W2.2 | deployment.config.json 生产预览 | 设置页（admin）→ 部署配置 → 预览 diff → 确认脱敏与 restart_level 提示正确 | `pytest Test/backend/test_deployment_config.py Test/backend/test_config_security.py -q` |
| W2.3 | 交付验证命令组 | checklist「验证」节命令 + `npm run check:catalog` + `GET /layers` run_readiness | 全绿输出落盘到演练记录 |

### Wave 3 — P2/P3 留痕快赢（按价值挑选，~2-3 天）

| # | 项 | 理由 | 验证 |
|---|----|------|------|
| W3.1 | B-N7 conftest 补 `PYTHONPATH=Code/algorithms/providers/Python` | 测试基建，改动 1 行，消除单文件运行依赖 | `pytest Test/backend/test_weatherengine_service.py` 单文件直跑通过 |
| W3.2 | B-N8 `Test/algorithms/conftest.py` sys.path[0] 遮蔽修复 | 测试基建，消除「Test/backend 与 Test/algorithms 不可同会话收集」 | 合并收集 22 文件无 ImportError |
| W3.3 | N-9 CI actions pin sha + requirements 全 `==` | 供应链加固（PRR 安全维度标准项） | CI 绿 + `.github/workflows/ci.yml` 全 sha 引用 |
| W3.4 | N-5 前端覆盖率门 22%→30%（优先鉴权与 weather-tile-manager） | 质量基线 | ✅ 2026-08-16：行 32.2%/语句 30.94%/分支 26.79%/函数 29.11%，144 文件 1066 测试全绿；阈值提至 30/32 锁基线；附带修复 weather-tile-merge 邻近 z 垫底死代码（key 前缀判断恒 false）与 workflow-validator Windows 盘符误报 |
| W3.5 | B-N3 sync 单域加锁 / B-N2 retry reuse_output_dir 代次子目录 | 并发可靠性（需先出小设计，非纯代码） | ✅ 2026-08-16：B-N3 按单域 all-or-nothing 锁（18 例）；B-N2 改为复用目录 claim 写互斥（pending→run_id 升级 + 终态懒抢占 + TTL 兜底，`reuse_cache.py`，16 例）；`test_concurrency_hardening.py` + `test_retry_reuse_claim.py` 全绿 |
| W3.6 | P-02 时间轴随 `node_progress.timeKey` 自动 seek | 调度审计唯一仍开的 P1 转化项（可选增强） | ✅ 2026-08-16：`useTimelineSync.ts` hint→守卫→`applyDateHour` seek 链路已测（`useTimelineSync.test.ts` + `workflow-timekey-seek.test.ts`）；审计报告 P-02 已勾「已实施」 |

### Wave 4 — 架构收敛（大项，另立专项排期，~2-3 周）

| # | 项 | 预估 |
|---|----|------|
| W4.1 | D2 god store 完成拆分（`useLayerWorkspaceStore` / `useWorkflowRunStore` / `useLayerViewportStore`，`index.ts` 仅 re-export） | ~3d |
| W4.2 | L3 god 模块拆分（`weatherengine/builders/` 渲染原语、`services/config/` 配置域） | ~3d |
| W4.3 | X1 catalog 三处真源统一（后端下发 schema，前端消费） | ~2d |
| W4.4 | N-4 双 HTTP 层合并共享内核；N-3 `X-Api-Key` 迁会话 Cookie + HttpOnly | ~2d |

### 条件项（不排期，触发时执行）

- **真实数据 e2e / NAS 实机绿测**：需数据环境就绪（I: 盘挂载 + NAS 可达）。
- **SMAP DEC2025 catalog 迁移**（~0.5d）：随数据到位执行。
- **N-11/N-12 未复检项**（Mercator 往返 ~0.013°、时区一致性）：复检数值后再定。
- **平台项**（Cesium 3D 主链、PostGIS、全站容器化、SSE）：明确非本期。

## 三、交付就绪视角（advisory，非本次 go/no-go）

按 PRR 影响维度分类：机构交付 = production/customer-impacting（外部承诺 ✓、数据敏感 ✓、状态持久 ✓、影响半径单机构 ✗小）。当前**不是**发布事件，故给紧凑咨询矩阵；真正交付前需按完整 PRR 模板执行（Wave 2 产出即其输入）。

| 维度 | 状态 | 缺口 → 对应工作项 |
|------|------|------------------|
| 安全 | ⚠️ | SSRF 三项 → Wave 1；localStorage → Wave 4 |
| 变更安全 | ✅ | 两轮审查 + 全绿回归（08-16 终态） |
| 可靠性 | ◐ | B-N2/N3 并发留痕 → Wave 3.5；SQLite/solo 池为平台约束（N-6，Linux+prefork 部署时消解） |
| 可观测性 | ✅ | LogPanel/SystemStatus/错误处理链已闭环 |
| 版本持久性 | ❌ **最急** | 7 提交未推送 + stash 未处置 → Wave 0 |
| 交付证据 | ◐ | 有 checklist 无演练记录 → Wave 2 |

## 四、假设与决策点

1. **假设**：延续项目既定优先级（安全 > 架构 > 并发 > 测试&功能）；I: 盘/数据环境可用性由用户掌握。
2. **需用户决策**：W0.1 push（可见动作）；W0.2 stash apply/drop；W0.3 是否合并 main；Wave 3 内挑选哪些项。
3. **明确不做**：平台项（Cesium/PostGIS/SSE）、需要数据环境的 e2e——除非用户指定。

## 五、验证命令速查（每波完成后）

```powershell
# 后端/算法（沙箱内 basetemp 必须 C 盘）
$env:PATH = 'C:\FreeRulesPrograms\BasicToolkits\Git\cmd;C:\Windows\System32;C:\Windows;' + $env:PATH
$env:ENVIRONMENT='test'; $env:REDIS_URL='redis://127.0.0.1:6379/0'
Env\Python312\python.exe -m pytest Test/backend -p no:cacheprovider --basetemp="$env:TEMP\cgda-be" -q

# 前端与契约门
cd Code/frontend; npm run test; npm run lint; npm run build; npm run check:openapi; npm run check:catalog

# 提交前
pre-commit run --all-files
```
