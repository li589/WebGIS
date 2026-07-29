# 工作流深度优化方案

## 问题诊断

### 校验缺口（最严重）
1. 后端 `validate_request_against_template` / `validate_job_request` 从未在提交端点调用
2. 前端 `canRun` 仅检查 `hasDefinition && !running`，不校验参数
3. Inspector 的 `validateParam` 不阻塞运行，validationErrors 未被运行路径读取
4. node-forms 完全无校验
5. 后端错误响应为纯字符串 `{"detail": "..."}`，丢失字段级定位

### 数据缺口
- 14 个工作流种子中 12 个缺少 `_meta.tags` 和 `extra.outputs`
- 多个节点模板 `params: []` 为空（omega_avg_daily、天气渲染节点等）
- 所有 Python 模块 `default_params` 为空

### UI 性能
- WorkflowStatusPanel 每秒 tick 触发 6+ computed 重算（即使无运行中工作流）
- PipelineLauncher 串行 fetchWorkflowDefinition
- WorkflowInspector `JSON.stringify` 对比
- WorkflowNodePalette Set 变化立即序列化

## 优化方案

### A. 运行前参数校验系统

#### A1: 前端统一校验器 `workflow-validator.ts`
- 新建 `src/composables/workflow-validator.ts`
- `validateWorkflowBeforeRun(graphData, nodeTemplates)`: 遍历所有节点，返回 `ValidationIssue[]`
- 校验项：
  - 必填参数非空（从 nodeTemplate.params 中 required=true 的字段）
  - 日期范围 start_date <= end_date
  - 数值参数 min/max 范围
  - enum 参数值在 allowed 列表内
  - 路径参数格式（非空、无非法字符）
  - 节点必填输入端口已连接
- `validateNode(node, template)`: 单节点校验
- `formatValidationIssues(issues)`: 格式化为用户可读消息

#### A2: 校验结果展示
- WorkflowRunDialog: 确认前调用校验器，有 critical 错误时显示错误列表并阻止提交
- WorkflowInspector: 从校验结果中过滤当前节点错误，在对应字段下方红字显示
- 工具栏: 校验状态图标（绿色✓ / 红色⚠ + 数量）

#### A3: 后端提交期预校验
- `submission_service.submit_workflow` 中调用 `validate_request_against_template`
- 返回结构化错误：`{"error_type": "validation", "issues": [...], "user_message": "..."}`
- 前端 `_http.ts` 解析结构化错误并传递给 UI

### B. 工作流种子与模板补全

#### B1: 补全工作流种子
- 为 12 个缺少 tags/outputs 的种子添加 `_meta.tags` 和 `extra.outputs`
- omega_avg_daily_* → tags: ["pipeline", "omega_avg"], outputs: ["SM", "OMEGA"]
- open_data_* → tags: ["sample", "download"]
- weather_* → tags: ["demo", "weather"]

#### B2: 补全节点模板 params
- omega_avg_daily: 添加 12+ 参数定义
- 天气渲染节点: 添加 layer_id 等参数
- 其他空 params 节点

### C. UI 流畅度优化

#### C1: WorkflowStatusPanel 条件 tick
- 仅当存在 running/queued 状态工作流时才启用每秒 tick
- 无活跃工作流时停止 setInterval，改用事件驱动
- `workflowItems` computed 添加 memoization 缓存

#### C2: PipelineLauncher 并行加载
- `loadPipelines()` 改用 `Promise.all` 并行 fetchWorkflowDefinition
- 添加加载进度指示

#### C3: WorkflowInspector isModified 优化
- 替换 `JSON.stringify` 为浅层 key-by-key 对比
- 对嵌套对象使用深度对比但限制递归层数

#### C4: WorkflowNodePalette 防抖
- `collapsedCategories` 变化防抖 300ms 后再写入 localStorage

### D. 细节功能增强

#### D1: 工具栏校验状态指示器
- 保存按钮旁显示校验状态图标
- 点击图标展开错误列表浮层

#### D2: 节点端口连接检查
- 校验器检查每个节点的 required 输入端口是否有连线
- 画布中未连接的必填端口显示红色高亮

#### D3: 下载节点表单校验
- SshSyncForm: remote_path 非空、local_path 非空、日期范围
- NsidcDownloadForm: short_name 非空、日期范围
- FyPreprocessForm: 输入/输出目录非空、日期范围
- 所有日期字段: start <= end

#### D4: PipelineLauncher 日期范围校验
- start_date <= end_date
- 日期格式 YYYYMMDD 合法性
- 高级参数类型转换校验

## 实施顺序
1. A1 (前端校验器) — 核心，所有校验依赖此模块
2. C1 (StatusPanel 优化) — 独立，UI 流畅度最大收益
3. B1 (种子补全) — 独立，快速完成
4. A2 (校验展示) — 依赖 A1
5. D3+D4 (表单校验) — 依赖 A1 的校验工具函数
6. A3 (后端校验) — 独立
7. C2+C3+C4 (性能优化) — 独立
8. D1+D2 (功能增强) — 依赖 A1
9. B2 (模板补全) — 独立
10. 验证
