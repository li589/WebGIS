# 2026-08-12 晚 全局代码审查（UI token / selector / 样式拆分）

## 范围

未提交工作区（相对 `c983999` / 含已提交 `ca12f95` 之后的本地改动）：

- 设计 token / 硬编码色值迁移（大量 Vue/CSS）
- 样式外提：`MapCanvas.styles.css`、`ModeToolbar.styles.css`、`TimelineScrubber.*.css`
- 新 UI：`SegmentedControl.vue`、`ui/icons.ts`、`useBreakpoint.ts`
- layers selectors：`storeToRefs` 保响应式
- OpenAPI 类型别名收敛：`LayerCatalogResponse`、`TestResultResponse` 等

## 结论

**可提交联调。** Critical 无；编译与测试门通过；鉴权/配置门面未回退。

## Critical / Medium / Low

### Critical
无。

### Medium
无阻断。selectors 从「直接返回 store 属性」改为 `storeToRefs`——正确修复解构丢响应式问题；消费者须按 Ref 使用（`.value` 或模板自动解包）。本轮 `vue-tsc` + vitest 覆盖通过。

### Low
1. InfoPanel / LayerSidebar 子模块仍有 `any` eslint warnings（0 errors）。
2. `useBreakpoint` 断点数值与 `tokens.css` 靠注释同步——漂移风险低但需约定。
3. vite build 对 litegraph `eval` 警告为既有上游问题。

## 编译门

| 门 | 结果 |
|----|------|
| `npm run lint` | 0 errors / 28 warnings |
| `vue-tsc` / `npm run build` | OK |
| vitest | **122 files / 635 tests passed** |
| `check:catalog` / `check:openapi` | OK |
| pytest auth/config/error | 见同轮执行 |

## 抽样核对

| 点 | 结论 |
|----|------|
| `config_service.get_effective_api_key` | 仍再导出 |
| `api-reexports` 去掉手写 alias | 对齐 OpenAPI schema 名 |
| SegmentedControl a11y | radiogroup + 方向键 |

## 重启

`launch.py stop` → `start` → `/health` + 登录抽样。
