# 未闭合项收口审计（2026-08-18）

> 对应计划：`.trae/documents/2026-08-18-未闭合项收口与后端配置真实性验证计划.md` 阶段 1。
> 处置分类：**已闭合**（附证据）/ **保留待办**（附理由）/ **移交用户**（不代做）。

## 一、处置总表（对应计划 §2.1）

| 类别 | 项 | 处置决策 | 证据 / 理由 |
|---|---|---|---|
| 工作区 | info-panel 分析工具迭代（22M+9U，+410/−102，D1–D3） | ✅ 已闭合 | 收尾验证（后端+前端测试+lint+build）通过后提交 `fd1c11f feat(analysis): 信息面板统计卡片主题化与导入图层自动统计` |
| 运维 P0 | `launch.py restart backend` 世代堆积（08-16 事件：单日 5 世代 ~50 僵尸） | ✅ 已闭合 | 提交 `236c357 fix(launcher): restart backend 按世代清扫残留进程并验证死亡`。真因三件：① zh-CN 控制台 GBK 输出致进程枚举解码全损（修复：PS 强制 UTF-8 + Python 侧回退本地代码页）；② `os.kill`=TerminateProcess 不杀进程树（修复：`tree_kill_pid` taskkill /T /F + spawn 孤儿清扫）；③ 无死亡验证（修复：`_verify_backend_stop` 校验进程退出+端口可绑定，不净则中止重启防堆叠）。测试 `Test/backend/test_launcher_process_sweep.py` 15 项 |
| 计划残留 | 前端重构 V3：hex 收尾（~180→≤20）、TimelineScrubber 拆分（753→<400）、设计系统文档 3 份、12 项手动回归 | 📌 保留待办 | 非本轮范围（计划 ADR Follow-ups 已显式排除）；属持续重构项，无阻塞 |
| 计划残留 | P2 backlog：D1/L2/L3/X1、C4（SQLite CAS）、R1（流式拷贝）、P3 清单 12 项（~13/17 完成） | 📌 保留待办 | 剩余项均低风险增强，无假设置/报错类问题，不与本轮配置真实性验证耦合 |
| 计划残留 | next-sprint：真实数据 e2e / NAS 绿测（P1） | 📌 保留待办 | 阻塞于数据环境（NAS/NSIDC 凭据与连通性），非代码问题 |
| 进度遗留 | `stash@{0}` WIP on dev `2d71f3f`（08-12，19 文件） | ✅ 已闭合 | 补丁导出至 `.ai/progress/archive/stash-2d71f3f-20260812.patch`；抽查确认核心改动（SF 反演算法等）已被 HEAD 后续提交（`37b4fe1` 等）覆盖；经用户确认后 drop |
| 进度遗留 | `.trae-html-share-packages/` 未删（docs-organization-plan §3.9） | ✅ 已闭合 | 经用户确认后删除，目录已不存在（2026-08-18 核验 MISSING） |
| 进度遗留 | `.ai/progress/_tmp_*` 临时脚本 ~50 个 | ✅ 已闭合 | 51 个文件移入 `.ai/progress/archive/tmp-probes-20260816-17/`（保留追溯，不删除；2026-08-18 核验计数 51） |
| 文档漂移 | AGENTS.md「改 X 则跑 Y」数据根行仍指 `DataSourceSettings.vue` 可改（实际已收敛 `/deployment`，`PathConfigSection` 只读） | ✅ 已闭合 | AGENTS.md 高风险区 #7 与「数据根 / 图层就绪」行已改；`.ai/rules/project-conventions.md` 对应两处已同步（本日） |
| 文档漂移 | （本轮新发现）`.ai/rules/project-conventions.md` 高风险区仍为旧鉴权模型（仅 `X-API-Key` / `BACKEND_DEV_AUTH_BYPASS`），缺 AGENTS.md 现行的 1b 部署配置真源、2 用户鉴权 RBAC 三角色、6 生产禁止演示开关条目；「配置 / 鉴权」验证行缺 `test_auth.py` / `test_deployment_config.py` | 📌 保留待办（阶段 5 文档定稿时处置） | 与本轮阶段 3 修复面（runtime 白名单 / worker 钩子）同属配置域，届时以代码证据一次性对齐，避免中途两改 |
| 用户手动项 | Defender 排除项、「数据导出」按钮人工确认、NSMC 三账号轮换、`chkdsk D: /f` 根治 NTFS 后解除 17 文件 skip-worktree | ➡️ 移交用户 | 见第二节移交清单 |
| 代码 TODO | 后端 1 处（source_fetcher.py:33 性能备注）；前端/算法 0 处 | ✅ 无需处理 | 性能备注非缺陷，保留 |

## 二、移交用户手动项清单（不代做）

| # | 项 | 背景 | 建议动作 |
|---|---|---|---|
| U1 | Windows Defender 排除项 | vitest worker 实时扫描致超时（历史测试干扰） | 将仓库根与 `Code/frontend/node_modules` 加入排除 |
| U2 | 「数据导出」按钮人工点击确认 | 结题演示材料生成环节 | 按 `.ai/progress/ui-verification-steps.md` 流程人工执行一次 |
| U3 | NSMC 三账号轮换配置 | 涉账号凭据，AI 不代管 | 由数据管理员在 `/config` 面板配置 |
| U4 | `chkdsk D: /f` 根治 NTFS 损坏后解除 17 文件 skip-worktree | 08 月中 NTFS 事件遗留保护 | 重启进入检查 → `git ls-files -v | grep ^S` 核对 → `git update-index --no-skip-worktree` 逐个解除 |

## 三、本轮不扩大范围声明

以下事项经 ADR 确认排除（见计划 §四 Follow-ups），审计确认未在本轮制造新的未闭合项：

- gaode/bing 瓦片消费接入（P-D 仅做「预留」标注）
- TimelineScrubber 拆分、hex 收尾、P2 backlog 剩余、真实数据 e2e
- Celery worker 进程 log_level 跨进程热调（文档注明随 worker 重启生效）

## 四、验证记录

- 工作区状态：`git status --short` 仅 `M AGENTS.md`（本轮文档修正，随 C4 提交）
- 归档核验：stash 补丁 EXISTS；tmp-probes 目录计数 51；`.trae-html-share-packages` MISSING
- 提交链：`fd1c11f`（阶段 0）→ `236c357`（阶段 1.3 / C2）
