# 代码审查纪要（安全加固 + Gateway 默认 + 文档对齐，2026-08-14）

对照未提交改动与近期 `dev` 提交（Gateway 默认、鉴权硬化、在线时序、catalog seeds）做本地审查；Bugbot/Security 子代理因额度不可用，改为人工 diff 审查。

## 结论

| 维度 | 结论 |
|------|------|
| 可合并性 | **可提交**：安全向改动方向正确；审查中发现并已修 2 处回归风险 |
| 编译/联调 | 需 FE `build` + 相关 pytest + `launch.py restart`（默认 Gateway） |

## 本批代码改动摘要

| 区域 | 意图 |
|------|------|
| `ssrf.py` | 新增存储期 URL/URI 校验；HTTP(S) 与数据源 URI 分轨 |
| `config_service` / `config_routes` | 开放数据预设与 remote layer URI 入库前校验；`ValueError` → 400 |
| `remote_browser_router` | 远程路径规范化；错误信息不外泄；写鉴权已有 |
| `weather_router` | model 白名单 + URL encode；非法 model → 400 |
| `workflow_timer_router` | GET / cron-preview / 详情加写鉴权；字段类型校验；触发失败不回传异常细节 |
| weather providers / `remote_sync` | base_url / FileBrowser path 编码加固 |
| `WorkflowCanvas` / `WorkflowEditorPanel` | 框选保底、右键恢复原生菜单；导入节点 id 允许 number |

## 审查发现与处置

| Severity | Location | Finding | 处置 |
|----------|----------|---------|------|
| High | `config_service.update_remote_layer_data_uris` | 误用仅 HTTP(S) 的 `validate_url_for_storage`，会拒绝合法 `smb://` / `file://` / `minio://` | **已修**：新增 `validate_data_source_uri_for_storage`，scheme 与 `source_fetcher` 对齐 |
| Medium | `remote_browser_router._validate_remote_path` | ASCII 白名单会拒中文 NAS 路径；`\` 未规范化 | **已修**：禁控制字符 + `\`→`/` + 遍历检查，允许 Unicode |
| Low | `config_routes` open-data / remote-uris | `ValueError` 未转 400，可能变 500 | **已修** |
| Info | `workflow_timer` GET 写鉴权 | demo/只读角色无法列定时器 | 按上线安全默认保留；文档已同步 |
| Info | 子代理 | Bugbot / Security Review 额度不足 | 本纪要替代；后续有额度可复跑 |

## 文档对齐（相对代码）

| 文档 | 变更 |
|------|------|
| `Docs/README.md` | 摘要表补 catalog seeds / 在线时序 / Gateway 默认 |
| `Docs/02-架构设计/后端架构设计.md` | 定时器 API 全量写鉴权 |
| `Docs/06-代码审查/code-review-fullstack-2026-08-09.md` | S-P2-1 闭环；Gateway 状态更新 |
| `Docs/03/04/01` + gateway README | 此前已改为 Gateway 默认（见提交 `3fd292b`） |
| `Docs/06-代码审查/2026-08-12-global-code-review.md` | 快照文：保留历史表述，以本纪要与活文档为准 |

## 验证清单

- [ ] `Env/Python312/python.exe -m pytest Test/backend/test_ssrf.py Test/backend/test_layer_remote_uris.py Test/backend/test_config_contracts.py -q`
- [ ] `cd Code/frontend && npm run build`
- [ ] `Env/Python312/python.exe launch.py restart`
- [ ] `GET http://localhost:5175/health` → ok
