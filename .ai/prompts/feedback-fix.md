# 处理用户反馈（feedback-fix）提示词

> 触发：用户说「处理反馈 / 看下反馈 / 修复 CGDA-BUG-xxxx」或会话开始时扫描到新反馈。
> 使用：以本文件为工作提示，逐节执行；编号缺失时先扫描。

## 1. 扫描（确定待办）

```powershell
Env\Python312\python.exe Tools/feedback_triage.py --open
```

若用户给定了具体编号 `CGDA-BUG-xxxx`，跳过扫描，直接进入 Step 2。

## 2. 读取该反馈完整内容

```powershell
Env\Python312\python.exe Tools/feedback_triage.py --show CGDA-BUG-xxxx
```

## 3. 问题分析（输出物）

以结构化格式回答以下问题（供后续修复与发布引用）：

- **现象**：一句话复述描述；列出复现步骤与期望/实际差异。
- **环境**：页面 URL、前端/后端健康、平台与 UA（区分环境性与代码缺陷）。
- **模块归属**：按 `category` 与现象映射到 后端路由域 / 前端视图与 store / 算法包。
- **根因假设**：1~3 条最可能的根因（附代码位置证据，非猜测）。
- **影响面**：波及的接口/页面/测试；是否需要配套改动（openapi、类型、文档）。
- **复现/验证方式**：能复现则给出步骤；不能则说明如何最小验证。

## 4. 规范化修复

遵守 `.ai/rules/project-conventions.md` 与 `.ai/rules/feedback-triage.md`：

1. 最小改动定位根因；不顺手重构无关代码。
2. 后端改动补测试（`Test/backend/test_feedback_api.py` 或对应域测试）；前端同理。
3. 回归：
   - 后端：`Env\Python312\python.exe -m pytest Test/backend -q`
   - 前端：`cd Code/frontend && npm run test`
   - lint：ruff / mypy / prettier（按约定执行）
4. 提交：
   ```
   fix(<scope>): 修复反馈 CGDA-BUG-xxxx：<根因与修法一句话>
   ```
   正文引用反馈编号、根因、验证结果；`<scope>` 按模块（workflow / feedback / layer / ...）。

## 5. 闭环发布（修复完成后必做，用户可见）

调用 `PUT /feedback/api/reports/{id}/response`（admin 会话或 X-API-Key），
或指导用户在工程师处理台 `/feedback/console.html` 发布：

```json
{
  "status": "fixed",
  "updatedAt": "2026-08-20 10:30",
  "assignee": { "name": "AI 工程师", "role": "开发" },
  "timeline": [{ "status": "fixed", "at": "2026-08-20 10:30", "note": "<修复摘要：根因+改动位置>" }],
  "replies": [{ "author": "AI 工程师", "role": "开发", "body": "<给用户的说明：已修复 + 如何验证>", "at": "2026-08-20 10:30" }]
}
```

- `status` 取 `fixed`（已修复）/ `closed`（关闭）/ `rejected`（不予处理，需说明理由）/
  `needs_info`（需用户补充信息，附具体追问）。
- 发布成功后用户端 60 秒内可见；`--open` 清单中该反馈消失（闭环）。

## 6. 汇报（最终回复给用户）

- 反馈编号与标题；根因与修复内容（文件 + 提交号）；测试/验证结果；
  已发布进展说明（用户端可见方式）；未闭环/需用户补充的项。
