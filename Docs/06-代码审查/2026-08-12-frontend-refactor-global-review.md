# 2026-08-12 全局代码审查（本地已提交 3 笔 ahead of origin/dev）

## 范围

审查对象为相对 `origin/dev` 的本地提交：

1. `ec27235` docs: reorganize Docs directory structure and clean up root
2. `939cb2e` refactor(frontend): component splitting, design token migration, and UI cleanup
3. `50c5d21` feat(frontend): AppSelect component, accessibility fixes, and refactoring report

工作区审查时已干净；Bugbot / Security Review 子代理不可用（计划额度），改为人工审查 + 编译门。

## 结论

**可联调。** 编译与测试门通过；`config_service` L3 门面再导出仍在；前端大拆分经 `vue-tsc` / vitest 验证。发现仓库误跟踪了 pytest 临时目录与部分 `.trae` 计划文件，本轮清理后另提交。

## Critical / Medium / Low

### Critical
无。

### Medium
1. **误入库产物**：`Test/pytest-run-tmp*`、`Test/.tmp_tianditu-*.jpg` 及部分 `.trae/documents/*` 进入 Git 历史，增大仓库噪音。已从索引移除并强化 `.gitignore`（本轮提交）。历史 blob 仍在旧 commit 中，后续若需彻底清历史需单独 `filter-repo`（未做）。
2. **结题备份 docx / Windy 整站抓取** 体量大（`Docs/09`、`Docs/10`）。按文档结构属有意归档，但克隆成本高——保留，不在本轮删除。

### Low
1. 拆分后的 InfoPanel / LayerSidebar 子模块存在较多 `any`（eslint warnings，0 errors）。
2. `AppSelect` 原先 `modelValue: string|number` 但 emit 仅 `string`；已改为按 options 还原 number。
3. OpenTopoMap 等海外底图仍可能因网络不可达失败（非本批回归）。

## 编译门

| 门 | 结果 |
|----|------|
| `npm run lint` | 0 errors / 29 warnings |
| `npx vue-tsc -b` / `npm run build` | OK |
| `npm run test`（vitest） | **121 files / 632 tests passed** |
| `check:catalog` / `check:openapi` | OK |
| pytest `auth` + `api_keys_basemap` + `config_security` + `error_handlers` | **30 passed** |

## 架构核对（抽样）

| 点 | 结论 |
|----|------|
| `ControlPanel` → `PanelDock` | Dashboard / Timeline 已切；几何函数仍在 `control-panel-geometry.ts` |
| `config_service` 再导出 | 含 `get_effective_api_key`（防 lifespan ImportError） |
| 鉴权 / 配置写路径 | 本批主要为 FE UI；未改 `/auth`、加密主密钥链路 |

## 重启

见同轮：`launch.py stop` → `start` → `/health` 与登录抽样。
