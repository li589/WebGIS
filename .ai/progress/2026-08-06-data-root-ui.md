# 可变数据根 + 前端重启后端（2026-08-06）

## 摘要

地理数据根改为配置驱动（`.env` 真源），本机联调接入 `I:\Geograph_DataSet`；前端「设置 → 数据源」可改路径并调度 `launch.py restart backend`（FastAPI+Worker+Beat，不动 Docker/Vite）。Catalog 种子路径与实盘对齐后 `GET /layers` **44/44 ready**。

## 操作面

| 入口 | 行为 |
|------|------|
| `Code/backend/.env` | `BACKEND_DATA_ROOT` / `BACKEND_OUTPUT_ROOT` / 可选 `BACKEND_UI_RESTART_ENABLED` |
| FE 设置 → 数据源 | 编辑路径 → 保存 / 保存并重启后端 |
| `PUT /config/data-source/paths` | 校验绝对目录 → upsert `.env` → `pending_restart` |
| `POST /config/service/restart` | 202 后 detach `launch.py restart backend`（development 默认允许） |
| CLI | `Env\Python312\python.exe launch.py restart backend` |

## 文档已同步

- 根 `README.md` / `AGENTS.md` / `CLAUDE.md`
- `.ai/rules/project-conventions.md`
- `.ai/docs/design/后端架构设计.md`、`reference/delivery-checklist.md`、`reference/hardcode-extension-audit.md`、`specs/当前数据源与产出一览.md`
- `Code/frontend/README.md`、`Code/backend/.env.example`

## 验证

- `Test/backend/test_data_source_paths.py` + `test_config_security.py`
- `npm run check:openapi` / `npm run build`
- 重启后 `/config/data-source` 生效根 = `I:\Geograph_DataSet`；`/layers` 无 blocked
