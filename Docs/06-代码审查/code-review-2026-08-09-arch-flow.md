# 代码审查报告：CGDA 架构设计全流程闭环 + 近期代码变更

> 审查人：CodeReviewExpert（火眼眼）｜日期：2026-08-09
> 审查范围：① 架构设计全流程的产出与性质；② 最近 25 个提交（auth/RBAC、安全加固 B1-B4、并发/CI 修复）；③ 架构文档与实际代码的一致性核验
> 验证手段：git 历史/工作区核验、关键文件逐行审读、后端鉴权/限流测试实跑（31 passed）

---

## 一、先回答："这个架构设计全流程是干什么的？"

**一句话：它是另一款 AI 工具（AICoding）的架构专家团按 SOP 跑出来的"纯文档架构交付包"，没有改一行代码。**

产出位于 `.workbuddy/output/delivery/`（已归档，共 8 份、约 420KB）：

| # | 文档 | Gate | 内容定位 |
|---|------|------|----------|
| 1 | material_digest.md | G1✓ | 对仓库 14 项原始资料（README/AGENTS/.ai 文档等）逐份摘要 |
| 2 | research_report.md | G2✓ | 行业调研（可选证据） |
| 3 | 高层架构设计.md | G3✓ | 边界基线：D1~D5 决策（2D 主链、技术栈、部署形态、RBAC、写限流） |
| 4 | 系统设计.md | G4✓ | 系统设计（X3 五队列、SLA、四域等契约） |
| 5 | UserStory.md | G4✓ | 用户故事 |
| 6 | 部署设计.md | G5✓ | 部署设计（8/8 模板校验通过，单节点 Docker 自托管） |
| 7 | 安全设计.md | G5✓ | 安全设计（9/9 校验通过，envelope+Vault 三阶段、审计保留 ≥1 年） |
| 8 | G6交付总览.md | G6✓ | 集成总览：术语统一、冲突裁决（X2/X3/X4/T5/U-04/MFA/审计）、六项目交叉 diff |

**对项目的意义**：这是一份自包含的"蓝图/交付材料"——把散落在 README、AGENTS.md、.ai/docs 里的项目事实提炼为可对外交付、可支撑结题/评审的成套架构文档，并统一了错误码、队列、SLA、资源编号等跨文档契约。**它不产生新功能，是"文档化"而非"开发"**。今天日志（.workbuddy/memory/2026-08-09.md）记录其 G5→G6 收尾与归档，与代码仓库无关。

**重要提醒**：这些文档描述的是**目标态（to-be）**。部分契约（如错误码 C403001/C429001、Vault 三阶段）尚未在代码落地，详见第三节。

---

## 二、代码现状核验

**工作区"大量 M 文件"是假象**：`git status` 显示的前端文件均与 HEAD 内容哈希一致（如 App.vue 同为 `c65dc98…`），仅为 CRLF/LF 行尾差异导致 status 显示 dirty。**实际无未提交的真实代码变更**，近期改动全部已提交（最近 25 个 commit 集中在 2026-08-08 ~ 08-09）。

近两日提交主线（与"闭环"同期，但属于正常的开发/修复流，非架构流程产物）：
- `015f5f7` 用户登录 + RBAC + 工程化可观测性（最大改动：后端 auth 全套 + 前端登录/401/错误边界）
- `4f318fe` 登录重定向与会话过期加固
- `946b174` 安全审查 B1-B4：SSRF fail-closed、防 X-Forwarded-For 伪造、写限流扩展、天气同步/运行时管理读鉴权
- `c9c6e76` resumable 上传元数据原子写（并发 JSONDecodeError 竞态修复）
- `aec8c5e`~`5183c37` CI 依赖/跨平台修复链（POSIX 路径识别、_as_file_uri、并发竞态——本地过≠CI 过）

---

## 三、审查发现（按优先级）

### 🔴 Blocker：无

### 🟡 建议（should fix）

**S1. 架构文档声明的错误码契约未在代码落地**
《系统设计》《部署设计》《安全设计》统一引用写鉴权错误码 `C403001`（缺失凭据）、写限流 `C429001`（120/min/IP），但 `Code/` 全库搜索无此编码——代码实际返回 `401 {"detail":"Authentication required."}`、`429 {"detail":"登录尝试过于频繁…"}`（登录限流）/ 写限流 429。
- **风险**：文档对下游（前端、运维、集成方）承诺了标准错误码，未来前端按 C403001 做条件判断会失效。
- **建议**：若按文档实施，应在 `deps.py`/`rate_limit.py` 统一错误体结构（如 `{"error_code":"C403001","detail":…}`），并同步 OpenAPI + gen:types（沿用 F14 闸门教训：加字段后必须重新导出契约）；若暂不实施，至少在文档标注"to-be"。

**S2. 写限流"120/min/IP"在多进程下会被稀释**
`rate_limit.py` 的滑动窗口限流器是**进程内内存态**。当前单进程形态没问题，但若未来多 worker/多实例部署，每进程独立计数 → 实际限流阈值 = 120 × 进程数，与文档承诺的"120/min/IP"全局口径不一致。建议文档明确"单进程口径"或改为 Redis 集中计数（当前发布边界单机构单进程可接受，记录即可）。

**S3. safeRedirect 白名单硬编码，路由扩展时易漏**
`safe-redirect.ts` 中 `SPA_PATHS = new Set(['/'])` 与 router.ts 的 3 条路由（/login、/、404）恰好一致，当前无风险；但新增 SPA 路由（如 /settings）时若忘记同步，登录后永远回首页（行为退化非安全问题）。建议从路由表导出或加单测锁定"路由集 = 白名单集"。

### 💭 Nit（nice to have）

- **N1** `auth_router.py::create_token` 创建后二次查询 `list_tokens_for_user` 取 created_at（小 N+1），SQL 可直接 RETURNING。
- **N2** `user_repository.py::update_user` 用 f-string 拼字段名——当前均为代码内白名单常量，无注入风险，但建议加 `assert` 断言字段名集合，防止未来加字段时引入注入面。
- **N3** `rate_limit.py` 第 62 行注释"天气瓦片 GET：公开读面"错位挂在 `_login_limiter` 上方，应下移到 `_tile_limiter`。
- **N4** `auth_bootstrap.py` dev 模式 `os.environ.setdefault` 改进程环境变量（dev only，可接受），若误配 `BACKEND_API_KEY=`（空串）会静默回退 dev 默认 key，建议启动时对空串值告警。

### ✅ 亮点（值得保持）

- **SSRF 防护是教科书级实现**（`core/ssrf.py`）：解析一次、IP 钉死连接（`_pinned_create_connection`）+ 重定向逐跳再校验 + 代理 fail-closed——连 DNS 重绑定/TOCTOU 窗口都考虑到了。
- **密码与会话**：PBKDF2-SHA256 200k 迭代、`compare_digest` 常量时间比较、登录用 dummy hash 做时序均衡（防用户枚举）、cookie httponly + SameSite=lax + 按环境 secure。
- **RBAC 边界处理周全**：最后 admin 保护、不能禁用/降级自己、角色/密码变更即吊销全部会话与 token、viewer 写操作 403、production 无用户拒启（fail-closed）。
- **前端**：`_http.ts` 401 统一走 SessionExpired + 敏感 GET 带 X-Api-Key + 30s 超时可读化；`safe-redirect` 防开放重定向（编码斜杠 `%2f`、`//`、login 循环、后端 API 前缀全部拒绝）。
- **并发**：resumable meta 临时文件 + `os.replace` 原子写，修复正确。
- **测试**：实跑 `test_auth.py` + `test_rate_limit_*` + `test_config_security` = **31 passed**；覆盖登录、RBAC、token、最后 admin、限流 IP 解析（防伪造头）等关键路径。

---

## 四、架构文档 vs 代码一致性核验结论

| 文档声明 | 代码现状 | 结论 |
|----------|----------|------|
| 单机构私有化 Docker Compose + SQLite + Redis/MinIO | AGENTS.md / config.py 一致 | ✅ 一致 |
| RBAC 三角色（admin/operator/viewer） | VALID_ROLES / deps.py 一致 | ✅ 一致 |
| 写限流 120/min/IP（production） | rate_limit.py 默认 120/min/IP，仅 production 生效 | ✅ 一致 |
| 登录限流 | 10/min/IP（文档未声明数值，代码实现更严） | ✅ 一致（优于文档） |
| X3 五队列族（algorithm/download/weather/gee/standard） | config.py/celery_app.py 有更细的 realtime/standard/heavy/batch/gee 分层 | ⚠️ 文档为族级抽象，实现更细，无冲突 |
| 错误码 C403001 / C429001 | 代码未实现 | ❌ **漂移（目标态）** |
| BACKEND_DATA_ROOT / BACKEND_OUTPUT_ROOT | config.py 存在且为硬约束 | ✅ 一致 |
| 安全设计 R-Sec-001~003（网络ACL/Vault/审计桶） | 部署侧目标态，本地栈未落地 | ⚠️ 蓝图项，按 T5 三阶段推进 |

---

## 五、结论

1. **"架构设计全流程闭环"= 8 份架构文档交付（蓝图），非代码开发**——若你此前不知情，现在可以放心：它没有改动仓库任何文件，全部产物在 `.workbuddy/output/delivery/`。
2. 仓库代码质量总体**优秀**：安全关键路径（鉴权/SSRF/密码/限流）实现严谨且有测试兜底，31 个相关测试全绿；工作区无未提交的真实变更。
3. **建议行动项**：S1（错误码契约落地与否需决策）、S3（前端路由白名单同步）；N1~N4 顺手可修。
