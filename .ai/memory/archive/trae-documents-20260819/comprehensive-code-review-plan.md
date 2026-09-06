# 全面代码审查计划

## Summary

对当前 git 工作树的 26 个文件变更（+453/−95 行）进行全面代码审查，采用 dev-code-review 技能的 5 轴方法论（规范/功能/闭环/注释/废码），按 P0/P1/P2 严重度分级。变更涵盖三个关注点：后端安全修复+输入验证（10 个 Python 文件）、前端校验（2 个 Vue 文件）、Nginx Gateway 默认化+文档同步（14 个文件）。

## Current State Analysis

### 变更集概览

| 关注点 | 涉及文件 | 行数占比 |
|--------|---------|---------|
| A. 后端安全修复 + 输入验证 | 10 个 Python 文件 | ~65% |
| B. 前端校验 | 2 个 Vue 文件 | ~20% |
| C. Nginx Gateway 默认化 + 文档同步 | 14 个文件 | ~15% |

### 已识别的关键风险（审查前预判）

| 风险 | 严重度 | 描述 |
|------|--------|------|
| 测试缺口 | P0 | 无新增测试覆盖任何新逻辑；`test_artifact_preview_route.py` 可能因新增 `_deny_if_not_artifact_owner` 未被 mock 而 break |
| artifact IDOR 修复行为分歧 | P1 | `_deny_if_not_artifact_owner` 在 `run_id is None` 时放行所有已认证用户，与 `workflow_router._deny_if_not_run_owner` 的 404 行为不一致 |
| RasterCommitBody.bounds 地理范围校验缺失 | P1 | 只校验长度=4，不校验经纬度有效范围（-180~180 / -90~90），与 BoundingBox 校验不对齐 |
| submission_service fail-closed 边界 | P1 | 需确认是否存在合理的「模板不兼容」跳过场景被误判为错误 |
| _validate_tool_params 未知 key 跳过 | P1 | 用户传入的未知 key 不经校验直接进入 workflow graph |
| scope 混杂 | P1 | 三个不相关关注点混合在同一 diff 中，违反「外科手术式改动」 |
| 鉴权函数三处重复 | P2 | `_deny_if_unauthenticated` 在 3 个文件中重复定义 |
| 前后端校验逻辑不完全对齐 | P2 | options 校验策略（严格类型 vs 强制转 str）和数值类型判断策略不同 |

## Proposed Changes

### 步骤 1：安全闭环验证（P0 优先）

**目标**：确认所有新符号有调用方，现有测试不会 break。

**操作**：
1. 读取 `Test/backend/test_artifact_preview_route.py` 全文，确认 `_deny_if_not_artifact_owner` 未被 mock 时测试是否 break
2. 对每个新增公共函数执行 `git grep` 闭环验证：
   - `git grep -n "_validate_tool_params"`
   - `git grep -n "_deny_if_not_artifact_owner"`
   - `git grep -n "sanitizeString"`
   - `git grep -n "validateParams"`
   - `git grep -n "formErrors"`
3. grep 调试残留：`git diff | grep -E "console\.log|print\(|debugger|breakpoint"`

### 步骤 2：安全修复一致性检查

**目标**：确认鉴权修复跨文件一致、无遗漏。

**操作**：
1. 对比 `_deny_if_not_artifact_owner`（artifact_router.py）与 `_deny_if_not_run_owner`（workflow_router.py）的逻辑分歧
2. 确认 `analysis_router.py` 是否已有鉴权
3. 确认 `_validate_tool_params` 的 unknown-key 跳过行为是否与 `_inject_tool_params` 的实际注入逻辑一致
4. 检查 `submission_service.py` 的 `except Exception` 分支是否会拦截合理的跳过场景

### 步骤 3：输入验证边界分析

**目标**：确认所有输入验证覆盖了必要的边界。

**操作**：
1. 检查 `BoundingBox` 的 antimeridian（跨日期线）场景是否需要支持
2. 确认 `RasterCommitBody.bounds` 与 `TransformBoundsRequest.bounds` 下游消费方是否有二次校验
3. 检查 `TransformPointRequest` 的 CRS 字符串 `max_length=64` 是否覆盖所有合法 CRS 标识
4. 确认 `TimeRange` 的 `start_at == end_at`（零长度时间范围）是否合法

### 步骤 4：前后端校验对齐

**目标**：确认前端校验与后端校验规则一致。

**操作**：
1. 逐项对比 `InfoPanelToolsTab.validateParams` 与 `analysis_run_service._validate_tool_params` 的校验规则
2. 确认前端 `sanitizeString` 的 `<>` 剥离是否与后端任何净化逻辑对齐
3. 检查前端 `field.options` 类型定义与后端 `param_schema` 的 `options` 字段类型是否一致

### 步骤 5：注释与废码检查

**目标**：确认无残留调试输出、无过时注释、无重复代码。

**操作**：
1. 检查 `WorkflowEditorPanel.vue` 中注释 `// Create new workflow (use imported ID or generate new ID)` 是否与代码矛盾
2. 确认 `analysis_run_service.py` 中 `# unknown keys are ignored` 注释是否反映设计意图
3. 评估 `_deny_if_unauthenticated` 三处重复是否应提取为公共函数

### 步骤 6：输出审查报告

按 dev-code-review 标准模板输出，包含：
- Verdict（READY / FIX P1 / BLOCK）
- Scope（文件数、行数、staged/unstaged）
- Axis Check（5 轴结果）
- Findings（P0/P1/P2 分级）
- Cleanup（可一次性删除的内容）
- Commit message（仅 Verdict = READY 时）

### 步骤 7（条件性）：修复发现的问题

根据审查报告的 Verdict：
- **BLOCK**：修复所有 P0 项后重新审查
- **FIX P1**：修复所有 P1 项
- **READY**：可直接提交

### 步骤 8：提交策略

建议将混合关注点拆分为独立 commit：

| Commit | scope | 文件 |
|--------|-------|------|
| 1 | `fix(backend): add auth guards and IDOR fixes` | algorithm_router, provider_router, artifact_router, result_storage, submission_service |
| 2 | `fix(backend): add input validation at trust boundaries` | api_contracts, import_router, data_io/api/router, analysis_run_service |
| 3 | `fix(frontend): add param validation and import safety` | InfoPanelToolsTab.vue, WorkflowEditorPanel.vue |
| 4 | `feat(launch): make Nginx Gateway the default entry` | launch/*, infra/gateway/*, AGENTS.md, CLAUDE.md, README.md, Docs/*, Tools/ |

## Assumptions & Decisions

1. **审查范围**：覆盖全部 26 个变更文件，但代码审查深度集中在 12 个代码文件（Python + Vue），文档/配置文件仅做一致性检查
2. **闭环验证**：使用 `git grep` 而非 `grep -r`，确保只搜索 git 跟踪的文件
3. **测试缺口判定**：无新增测试不自动视为 P0，但如果现有测试因变更而 break 则为 P0
4. **提交拆分**：建议拆分为 4 个 commit，但最终是否拆分由用户决定
5. **跨日期线支持**：如果 CGDA 业务范围不涉及太平洋区域，BoundingBox 的 antimeridian 限制可接受
6. **artifact legacy 回退**：如果存在大量无 run_id 的遗留 artifact，`run_id is None` 时放行是必要的兼容措施，但应限制为 admin 访问

## Verification Steps

审查完成后执行以下验证命令：

```powershell
# 后端安全 / 鉴权
Env\Python312\python.exe -m pytest Test/backend/test_artifact_preview_route.py Test/backend/test_config_security.py Test/backend/test_auth.py -q

# 工作流 / 提交链路
Env\Python312\python.exe -m pytest Test/backend/test_workflow_routes.py Test/backend/test_interaction_hub.py -q

# 导入 / CRS / 输入验证
Env\Python312\python.exe -m pytest Test/backend/test_import_raster_crs.py Test/backend/test_import_data_io.py -q

# 前端
cd Code/frontend; npm run test; npm run lint; npm run build

# 契约一致性
cd Code/frontend; npm run check:openapi; npm run check:catalog

# 提交前全量门禁
pre-commit run --all-files
```

WorkBuddy 环境需加前缀禁用 safe-delete shim：
```powershell
$env:CODEBUDDY_SESSION_ID = $null; $env:CLAUDE_SESSION_ID = $null; $env:CODEBUDDY_SAFE_DELETE_SANDBOX = $null
```
