# 2026-08-12 全局代码审查 + 编译门 + 全栈重启 + 推送

## 结论

**可推送联调。** Bugbot 未报阻断；前端 `vue-tsc`/`build`、catalog/openapi、关键后端 pytest 通过；文档已同步天地图 UA 与 vec+cva 叠层说明。

## 审查要点

| 区域 | 结论 |
|------|------|
| 天地图代理 UA / vec+cva | OK：服务端 UA=`CGDA-Backend/1.0`；街道 = vec 底 + cva overlay |
| config L3 拆分 / facade 再导出 | **必须**经 `config_service` 再导出；遗漏会导致 lifespan `ImportError`（见补记） |
| layers store domain 拆分 | OK：域类型用 `ReturnType`，避免手写接口 arity 漂移 |
| ModeToolbar / 可用性 chip | OK：去掉 availability chip，保留 WorkflowStatusButton |
| 导出 / workflow 422 / 设置 | 本批一并纳入推送（先行会话已验证） |

## Critical / Medium / Low

### Critical
无（推送当时）。

### Medium
无新增阻断。OpenTopoMap 海外主机不可达属**网络环境**，非代码缺陷。

### Low
1. FE eslint 仍有既有 warnings（0 errors）。
2. 并行编辑曾短暂回退 UA 修复；收口时已确认在树中。

## 本轮最小修复（编译门）

- `Code/frontend/src/stores/layers/catalog-builders.ts`：`(hasPres && presValue(...))` 改为三元，消除 `string \| false` 赋值错误。

## 编译门

| 门 | 结果 |
|----|------|
| Bugbot | no bugs |
| pytest（关键后端切片） | **88 passed**（先行会话） |
| `npm run lint` | 0 errors |
| `npx vue-tsc -b` / `npm run build` | OK |
| `check:catalog` / `check:openapi` | OK |

## 文档

- `Docs/07-工程保障/UI优化与底图模块修复-2026-08-12.md`（任务 6–7：天地图 + 构建验证；任务 8：登录超时补记）
- `AGENTS.md` / `.ai/rules/project-conventions.md`：统一瓦片行补充 `tile_proxy_service` / 天地图 UA
- 2026-08-12 晚：`Docs/` 编号结构导航、工程决策纪要、前后端 README、文档治理说明已对齐现行代码

## 重启与推送

1. `launch.py stop` → `launch.py start`：Docker + FastAPI + 7 Worker + Beat + **Nginx Gateway** 均就绪（本地 HMR 改用 `start --vite`）
2. `GET /health` → ok；`tianditu-vec` / `tianditu-cva` 瓦片抽样 → **200**
3. 提交 `4ac932f` → `git push origin dev`（`2d71f3f..4ac932f`）成功

本地未推送：`.trae/`、备份 docx、`Test/.tmp_*`、pytest tmp（`.ai/` 本就不入库）。

## 补记：登录超时（同日后续）

**现象**：登录页提示请求超时；`launch.py status` 显示 fastapi PID 在跑但 `/health` 超时。

**根因**：`config_service` 未再导出 `get_effective_api_key` → lifespan `hydrate_effective_config()` `ImportError` → 应用启动失败，端口假活。

**修复**：在 `config_service.py` 完整再导出 L3 模块公开符号；全栈重启后 `POST /auth/login` → 200。

**文档约束**：已写入 `Docs/02-架构设计/工程决策纪要-配置瓦片与契约.md` §2。
