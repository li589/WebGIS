# Vue 模板事件表达式修复与编译复核

- 日期：2026-08-07
- 范围：前端 SFC `@click` / `@input` / `@change` 多语句非法表达式
- 验证：`cd Code/frontend && npm run build`、`npm run lint`；静态扫描 `multi_stmt_hits=0`

## 问题

Vue 编译器要求模板事件属性值为**单个 JavaScript 表达式**。下列写法会在 Vite 报：

`Error parsing JavaScript expression: Unexpected token, expected ","`

```vue
@click="
  foo()
  bar()
"
```

运行时表现为 HMR overlay、`DashboardView.vue` 动态导入失败（连锁）。

## 修复（已落地）

| 文件 | 原问题 | 修复 |
|------|--------|------|
| `src/data-manager/ui/DataImportMenu.vue` | 关菜单 + 开工作区两行 | `openAttributesWorkspace` / `openDetailsWorkspace` |
| `src/components/InfoPanel.vue`（2 处） | `setActiveTab` + `emit` 两行 | `enterInspectTools()` |
| `src/components/workflow/WorkflowEditorPanel.vue` | 两个 ref 赋值两行 | `proceedAfterValidation()` |

多行但**合法**的单表达式（对象字面量、多参调用、箭头函数）未改，例如：

- `openDataWorkspace({ tab: 'details', ... })`
- `patchImportedVectorStyle({ color: ... })`
- `(e) => savePriority(...)`

## 代码审阅要点

1. **模式正确**：多步逻辑进 `<script setup>` 方法；模板只绑方法名，与既有 `openImport` / `openExport` 一致。
2. **声明顺序**：`enterInspectTools` 放在 `defineEmits` 之后，避免使用未初始化的 `emit`。
3. **公开 API**：无 Pinia / 路由契约变更；仅为事件绑定抽取。
4. **全库扫描**：前端 `src/**/*.vue` 同类「两行语句」命中 **0**。

## 编译 / Lint

| 命令 | 结果 |
|------|------|
| `npm run build`（`vue-tsc -b && vite build`） | **通过**（exit 0） |
| `npm run lint` | **通过**（0 errors，36 warnings） |

构建附带告警（非本次引入、不阻断）：

- `litegraph.js` direct `eval`（第三方）
- `overlay-symbology.ts` 动静态双导入（chunk 提示）
- lint warnings：地图 wind 层 / `_http.ts` any / 少量 `console`（既有）

## 残留风险 / 建议

1. **约定**：模板事件禁止多语句；需要时用方法或 `a(); b()`（仍推荐方法）。
2. **可选门禁**：CI 或 pre-commit 加轻量扫描（模板内 `@click="` 后换行且出现第二个语句起始），防复发。
3. **运行态**：开发服硬刷新 `http://localhost:5175`；若曾出现双 Vite 占端口，以 `launch.py status` 为准。

## 结论

模板事件表达式缺陷已清零；生产构建与类型检查通过。当前无阻塞编译错误；余下仅为既有 lint/vendor 告警，与本次修复无关。
