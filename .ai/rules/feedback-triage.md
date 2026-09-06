# 问题反馈 → AI 修复闭环（单一真源）

> 面向所有 AI 编码助手（WorkBuddy / Cursor / Trae / Qoder 等）与工程师。
> 用户经 `/feedback/` 反馈中心上传的服务端反馈，存放在
> `BACKEND_DATA_ROOT/_runtime/feedback/`，**本规范定义 AI 如何识别、读取、
> 分析并规范化修复这些反馈**，以及修复后的闭环发布方式。
> 约定改动直接改本文件；各工具规则文件仅保留指针。

---

## 1. 反馈数据面（三环）

```
[用户] /feedback/ 提交
   ├─ 离线轨：存本机浏览器（IndexedDB），导出 JSON 经 IM 交给工程师
   └─ 在线轨：POST /feedback/api/reports → 服务端落盘（权威存储）
                                              │
[服务端] DATA_ROOT/_runtime/feedback/CGDA-BUG-*/   ← AI 读取入口（本规范）
   ├─ report.json   # 净化后的导出原文（schema + report + attachments 清单）
   ├─ meta.json     # token / 上传时间 / 上传 IP / 附件数
   ├─ attachments/  # base64 解包后的附件文件（可选）
   └─ response.json # 工程师/AI 发布的处理进展（可选；存在即"已受理"）
                                              │
[AI/工程师] Tools/feedback_triage.py 扫描 → 分析 → 定位修复 → 提交
   → 处理台 /feedback/console.html 或 PUT /feedback/api/reports/{id}/response 发布进展
   → 用户端 60 秒内可见
```

## 2. 存储位置与目录结构

- 根目录解析（`Tools/feedback_triage.py` 内实现，与后端 `config.py` 一致）：
  `BACKEND_FEEDBACK_DIR` > `BACKEND_RUNTIME_ROOT/feedback` >
  `BACKEND_DATA_ROOT/_runtime/feedback` > 候选探测（项目现行
  `I:/Geograph_DataSet/_runtime/feedback`）> `Code/backend/.data/_runtime/feedback`。
- 目录名 = reportId（`CGDA-BUG-YYYYMMDD-XXXX`，白名单正则校验，防路径穿越）。
- 每条反馈一个目录，无 `response.json` = 未受理（状态 `submitted`）。

### 关键字段（report.json → `report` 内层）

| 字段 | 含义 | AI 用途 |
|------|------|---------|
| `title` / `description` | 标题 / 问题描述 | 问题定位首要依据 |
| `steps` / `expected` / `actual` | 复现步骤 / 期望 / 实际 | 复现与根因判断 |
| `category` / `categoryLabel` | 类型（functional/data/workflow/performance/ui/ingest/deploy/security/other） | 分流到模块域 |
| `severity` / `severityLabel` | 严重度（low/medium/high/critical） | 优先级排序 |
| `contact` | 提交人姓名/角色/联系方式/deviceId | 回复署名与回访 |
| `env` | 页面 URL / UA / 平台 / 后端健康 / 时区 | 环境复现条件 |
| `client.page` | 反馈页版本（`feedback-page/1.0`） | 版本定位 |

### 状态机（response.json 的 `status`）

`submitted`（无 response，未受理）→ `received` 已受理 → `in_progress` 处理中 /
`needs_info` 待补充信息 → `fixed` 已修复 / `closed` 已关闭 / `rejected` 不予处理。
**闭环状态**：`fixed` / `closed` / `rejected`（`--open` 待办不再出现）。

## 3. AI 处理 SOP（规范化修复）

### Step 0 扫描（会话开始或接到反馈任务时）

```powershell
Env\Python312\python.exe Tools/feedback_triage.py --open   # AI 待办：未受理/未修复
Env\Python312\python.exe Tools/feedback_triage.py --count  # 统计
Env\Python312\python.exe Tools/feedback_triage.py          # 全部
```

> **约定**：编码会话开始或用户提到"反馈/问题/报错"时，先跑 `--open` 检查是否有
> 服务端反馈待处理；有新反馈时主动列出并提示处理。

### Step 1 分析（读取单条完整内容）

```powershell
Env\Python312\python.exe Tools/feedback_triage.py --show CGDA-BUG-YYYYMMDD-XXXX
```

- 提取：标题 / 描述 / 复现步骤 / 期望与实际 / 环境（页面 URL、后端健康、版本）。
- 归类：按 `category` 映射到后端路由域（`app/api/routers/`）、前端视图
  （`Code/frontend/src/views|components|stores|services`）、算法包（`Code/algorithms/`）。
- 环境差异优先：`env.backendHealth` 为 down 的反馈，先确认是否环境性/网关问题，
  勿直接归因代码。

### Step 2 定位与修复

- 遵守 `.ai/rules/project-conventions.md` 全部硬约定（唯一解释器 `Env/Python312`、
  launch.py 入口、测试位置 `Test/`、提交规范等）。
- 修改范围最小化；能补测试必补（后端 `Test/backend/`、前端 `Test/frontend/`）。
- 涉及 CI 闸门（openapi 漂移 / gen:types）时执行对应回归。

### Step 3 验证

- 后端改动：`Env\Python312\python.exe -m pytest Test/backend -q`
  （反馈 API 专测：`Test/backend/test_feedback_api.py`）。
- 前端改动：`cd Code/frontend && npm run test`。
- ruff / mypy / prettier 按 project-conventions 执行。

### Step 4 提交（conventional commits）

```
fix(<scope>): 修复反馈 CGDA-BUG-YYYYMMDD-XXXX：<一句话根因与修法>
```

- scope 按模块（如 `fix(workflow)` / `fix(feedback)`）。
- 提交正文引用反馈编号与根因；相关测试用例一并提交。

### Step 5 闭环发布（修复完成 → 用户可见）

优先经工程师处理台 `/feedback/console.html`（admin 会话）→「发布处理进展」，
或直接调用 API（admin cookie / X-API-Key）：

```powershell
# PUT /feedback/api/reports/{id}/response 的 JSON 体（与处理台同构）：
# { "status": "fixed", "updatedAt": "<YYYY-MM-DD HH:MM>",
#   "assignee": {"name": "<姓名>", "role": "<角色>"},
#   "timeline": [{"status": "fixed", "at": "<...>", "note": "<修复摘要>"}],
#   "replies": [{"author": "<姓名>", "role": "<角色>", "body": "<给用户的说明>", "at": "<...>"}] }
```

- 用户端 60 秒内轮询可见进展与回复。
- `status` 合法值：`received` / `in_progress` / `needs_info` / `fixed` / `closed` / `rejected`。

## 4. 安全与边界（硬约束）

- `Tools/feedback_triage.py` **只读**：绝不修改 / 删除反馈数据。
- 删除反馈只走工程师处理台或 `DELETE /feedback/api/reports/{id}`（admin 鉴权）。
- 附件按白名单与魔数校验；AI 预览附件时按文本/图片处理，**不得执行**可执行文件。
- 反馈可能含敏感信息（联系方式 / 密钥告警），分析报告与提交信息中**不复制**敏感字段；
  导出文件勿长期保留在共享位置。
- 反馈页 token 是用户私密凭据（防编号枚举），AI 读取 `meta.json` 时**不得外泄 token**。

## 5. 相关指针

- 用户页/处理台/API 文档：`Code/infra/gateway/maintenance/README.md`
- 后端实现：`app/api/routers/feedback_router.py` + `app/services/feedback_store.py`
- 测试：`Test/backend/test_feedback_api.py`
- 工作区记忆：`.workbuddy/memory/MEMORY.md`（反馈入口约定）
