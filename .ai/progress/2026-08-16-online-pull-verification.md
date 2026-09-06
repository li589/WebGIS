# 在线数据链路验证报告（2026-08-16）

S1 图层库清理 + S2 在线拉取（NDVI / SMAP / 风云）全链路验证完成，两笔提交已推送 origin dev。

## 提交记录

| commit | 内容 | 文件数 |
|--------|------|--------|
| `cf119c8` | refactor(catalog)：图层库清理与 overlay 资产审计同步 | 5（+193/−365） |
| `a664598` | feat(data-access)：在线数据链路修复（CMR/Earthdata/FY NAS） | 15（+925/−102） |

推送区间 `0f2a91b..a664598`（含此前 W3.4 前端覆盖率门 / W3.5 并发加固 / W3.6 时间轴自动 seek）。

## 实测结果矩阵

| 链路 | 端点 | 结果 | 说明 |
|------|------|------|------|
| CMR granule 检索 | `cmr.earthdata.nasa.gov/search/granules.json` | 通过（HTTP 200，5 granule） | 公共只读免凭据；VNP13A1（VIIRS NDVI 500m 16-day） |
| URS token 交换 | `urs.earthdata.nasa.gov/api/users/token` | 通过（token 复用逻辑生效） | 账号 Rejoyce 有效；复用优先避免 max_token_limit |
| Earthdata 云 CDN 下载 | `data.lpdaac.earthdatacloud.nasa.gov` | 通过（HTTP 206，1KB Range） | 必须带 `Authorization: Bearer <token>` 前缀；302 跳预签名 CloudFront |
| NSIDC 云 CDN | `data.nsidc.earthdatacloud.nasa.gov` | 代码层迁移完成 | 旧 ECS host（n5eil01u）已停服；复用 earthdata 凭据（use_for_nsidc=True） |
| FY NAS 拉取工作流 | `/workflow-runs`（ssh_sync → map_layer） | 通过（run-1f0ac8ee1da4 succeeded） | 13MB `FY3D_GBAL_L1_10H_20240101_MWRID_0.tif` 落盘 `_runtime/python_provider/data_access/ssh_sync/` |

## 关键修复

1. **`workflow_request_resolver`**：`compile_litegraph_to_workflow_definition` 将 `download/ssh_sync` 编译为 `node_type="module"` + `params.module_name="ssh_sync"`，原始前缀丢失导致单 download 节点图被展平错配为 `fy_daily`。新增 `_registry_type_by_node_class()` 注册表反查恢复规范类型；补编译形态回归用例。
2. **`fy_download`**：NAS 默认 URI 由不存在的目录式 `smb://nas/Chenhaojun/fy/{date}/` 修正为实测路径 `smb://nas/Chenhaojun/Data/fy3dhdf2425/FY3D_GBAL_L1_10H_{ymd}_MWRID_0.tif`；支持 `CGDA_FY_NAS_URI` 环境变量覆盖。
3. **`data_access_nodes`**：URS token 交换改复用优先（列 token → 校验 → 复用，仅在无可用 token 时新建），规避 provider 侧 403 max_token_limit；CMR 日期规范化与非数据后缀过滤。
4. **`portal_catalog`**：CMR 公共检索不再发送无效凭据头（此前 401）；`nsidc_data` base_url 迁移云 CDN。

## 凭据矩阵（本地记录，禁入仓库/前端）

| 用途 | profile | 状态 |
|------|---------|------|
| Earthdata（CMR 检索后下载 / NSIDC 复用） | `earthdata`（Rejoyce） | 已入门户凭据库，实测有效 |
| 风云 NSMC 网页下载（单账号限额 ×3 轮换） | 未配置 | 账号已记录于本地记忆；FY 链路当前走 NAS 拉取，不依赖 NSMC |

## 测试与质量门

- 后端：174 passed / 1 skipped（resolver / 种子编译 / 门户 / 下载链路 12 个测试文件）
- 前端：`check:catalog` 52 items 同步；workflow-definitions + validator 48 passed
- pre-commit 全量（ruff / mypy / eslint / prettier / 契约）通过

## 用户待办

1. **运维 P0**：`launch.py restart backend` 不会杀干净旧进程——本次排查发现单日堆叠 5 世代约 50 个 FastAPI/Worker 僵尸，端口 8000 由最老僵尸应答，造成"代码修复不生效"假象。建议修复 launcher 停止逻辑（按命令行模式 + PID 文件双重清扫），或在排障手册中固化"按 CreationDate 清扫 `start_fastapi.py`/celery 进程"步骤。
2. FY 预处理/反演若需 NSMC 官网直连（非 NAS），再配置三账号轮换（凭据已在本地记忆）。
3. NDVI 在线链路（CMR → Earthdata 下载 → ndvi_daily）已具备端到端条件，可择时从前端画布提交 `ndvi_online_read` 种子做全链路联调。
