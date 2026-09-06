# 技能：多源数据接入（校园 SSH / NAS / NSIDC SMAP / Earthdata / CDS / NOMADS / CDSE）

> 场景：需要从课题组外部数据源拉取 FY/SMAP/NDVI/ancillary/再分析/GRIB2 等原始数据，接入 CGDA 后端做反演/展示。
> 适用工具：后端数据接入 / `shared/remote_sources` 扩展 / 配置真源。

## 1. 后端接入入口

| 角色 | 路径 |
|------|------|
| 远程存储扩展说明（公开） | `Docs/03-规范协议/远程存储接入说明.md` |
| 远程源协议/注册表 | `Code/shared/remote_sources/`（registry / protocol / uri / download / limits / transports/） |
| 工作流下载节点 | `modules/download_nodes.py`：`ssh_sync`（legacy + 远程存储 profile）、`http_open_data`、NSIDC/GLDAS/FY；专用源节点 `modules/cds_download.py` / `nomads_download.py` / `cdse_download.py`（实现下沉 `ingest/` 同名模块，共享 `_http_resume.py` 续传）；表单见 `node-forms/*` |
| FY 下载（NSMC 在线+NAS） | `modules/fy_download.py` + `ingest/nsmc_portal.py`（2026-08-20 重写）：NSMC 新门户链路 = RSA+验证码登录（fy4 center）→ tokensync 跨域会话 → subfile 检索 → POST 表单直下；会话缓存 `CGDA_NSMC_SESSION_FILE`/`<DATA_ROOT>/_runtime/cache/nsmc_session.json`；无 ddddocr 时人工预热（`Tools/nsmc_online_probe.py prepare → login --code → export`）；限额保护 `max_files_per_day`（默认2）/`download_interval`（默认5s）+ 频控 600s 冷却轮换；FY3F ORBA NAS 分支 `/Chenhaojun/Data/3Ffinal`（合并 HDF 优先，回退 10V/10H TIF 对） |
| 专用库主/回退矩阵 | `Docs/03-规范协议/远程存储接入说明.md`：cdsapi / herbie / earthaccess 为主路径，legacy HTTP 直链为回退（NOMADS/NASA 静默回退记 warning，CDS/CDSE 不可复现时报可诊断错误） |
| 已注册传输方案 | `sftp`（`transports/sftp.py`）、`smb`（`transports/smb.py`）、`ftp`（`transports/ftp.py`）、`gs`/gcs（`transports/gcs.py`） |
| 配置写操作真源 | `Code/backend/app/api/config_routes.py` + `app/services/config_service.py` |
| 任务需求/产出 | `.ai/docs/specs/课题组数据需求与产出说明.md`、`当前数据源与产出一览.md`、`数据源与工作流对照说明-2026-07-21.md` |
| 原始需求记录 | `.ai/docs/reference/一份任务说明-7.25.txt`、`一份任务记录-8.01.txt` |

传输注册表（`Code/shared/remote_sources/registry.py` 已确认）：`get_default_transport_registry()` 默认注册 `SftpTransport / SmbTransport / FtpTransport / GcsTransport`，按 URI scheme 路由（`parse_remote_uri`）。

## 2. 数据源通道（仅描述通路，不写明文凭据）

| 源 | 通道 | 用途 |
|----|------|------|
| 校园网服务器 | SSH（sftp 走 `SftpTransport`）；内网地址经 Cloudflare 隧道可达 | FY/SMAP/NDVI 原始数据、Matlab 参考脚本 |
| NAS | Filebrowser（smb/sftp） | 课题组数据集中存放 |
| NSIDC | SMAP 在线（如 `SPL3SMP_E` v6），需 Earthdata 账号 | SMAP 亮温 L3 |
| Earthdata | NASA Earthdata 统一认证 | 多源遥感产品 |
| ECMWF CDS | 节点 `cds_download`：主路径 `cdsapi` 排队轮询，回退 legacy 静态直链（Range 续传） | ERA5/ORAS5 再分析（含风场再分析待下载项）；凭据经门户 `ecmwf_cds` 或 `BACKEND_CDS_API_KEY` |
| NOAA NOMADS | 节点 `nomads_grib_download`：主路径 `herbie`（model/product/cycle 参数化子集），回退 `filter_*.pl` / 全量直链 | GRIB2 数值预报（风场等），产物可直接进科学栅格链路 |
| Copernicus CDSE | 节点 `cdse_download`：主路径 OData（`cdsapi` 兼容栈 + JSON token），回退 legacy 直链 | 哥白尼数据空间产品 |

> **凭据安全**：所有服务器/隧道/账号凭据为私有信息，**禁止写入 `.ai/`、commit 或外传**。凭据已存于安全处（`.env` / 密钥库），接入时经 `config_routes.py` 的 remote-storage 加密凭证库与 `X-API-Key` 鉴权（development 未启用 keys 时可旁路）。

### SMAP 版本策略（2026-08-15 审计确认）

- **现状**：`ingest/nsidc_download.py` 固定 `SHORT_NAME=SPL3SMP_E`、`VERSION="6"`；节点 `nsidc_smap_download` 默认 v6，参数可覆盖 `version`/`short_name`（v5/v6 可经节点参数共存下载）。
- **revision 不解析**：文件名中的 NSIDC revision 段（如 `SMAP_L3_SM_P_20230110_R18290_001.h5` 的 `R18290`）**不参与下载选择与落盘命名**——同日不同 revision 会按同名覆盖（跳过条件为"本地存在且大小一致"）。当前课题组只消费 v6 单 revision，此为**已知接受的行为**。
- **触发升级的条件**：出现实际多版本共存需求（如 v5/v6 对比、R18290 之外的 reprocessing 融合）时，再为 `download_smap_range` 增加 revision 解析与按 revision 落盘；在那之前**不要**默认解析 revision（避免下游 `data_preprocessor`/`omega` 按日期匹配输入的假设被破坏）。
- **下游耦合提醒**：`data_access/data_preprocessor.py` 按文件名 8 位日期筛选 SMAP 输入（`_extract_date_from_filename`），改落盘命名前先核对 `build_retrieval_inputs` 的日期筛选与 `omega` 反演输入匹配。

## 3. 接入步骤

1. 在 `config_routes.py` / `config_service.py` 配置 remote-storage（URI + 加密凭证），对应 `/config/remote-storage` 接口。
2. 通过 `shared/remote_sources` 的 `download.py` 按 scheme 路由拉取；注意 `limits.py` 限流与 `protocol.py` 契约。
3. 数据落地到 `.gitignore` 已排除的路径（`imports_output`、`tmp`、`.pytest_run*` 等），**勿在排除路径落源码**。
4. 接入后跑对应验证（见 `.ai/rules/project-conventions.md`「改 X 则跑 Y」；测试集中在仓库根 `Test/`，用 `Env/Python312` 执行）：
   - 栅格/数据（仓库根）：`Env/Python312/python.exe -m pytest Test/backend/test_import_raster_crs.py Test/backend/test_crs_detector.py -q`
   - 远程源：`Env/Python312/python.exe -m pytest Test/backend/test_remote_sources.py -q`
   - 算法（`Code/algorithms/providers/Python`）：`Env/Python312/python.exe -m pytest Test/algorithms -q`（GRIB 链路：`Test/algorithms/test_grib_cfgrib_optional.py`，fixture 在 `Test/algorithms/fixtures/`）

## 4. 已知坑

- `ssh_sync` 表单字段为 `start_date`/`end_date`（与 NSIDC/GLDAS 一致）；后端同时兼容历史 `date_start`/`date_end`。`file_filter` 须传入 `sync_dataset`，否则扩展名筛选无效。
- 双路 NDVI 与 ancillary 静态参数路径要区分清楚，错用源会导致反演漂移（见 `omega-sf-inversion` 技能）。
- Windows 上 SFTP/SMB 客户端需注意编码与权限；非管理员终端可能连不上内网隧道。
- 大文件请勿走 bind mount 进 Docker；Open-Meteo volume 已是反面教材，数据接入同理避免 Windows 路径 bind mount。
- 公开权威接入说明见 `Docs/03-规范协议/远程存储接入说明.md`；改动接入行为前先读。
- GRIB 消费链（2026-08 落地）：`.grib2` 可直接上传进科学栅格链路（`POST /import/raster/inspect` 枚举变量 → `raster/commit` 抽取为 GeoTIFF，bounds 取自 cfgrib 经纬坐标）；算法侧 `variable_extract` / `format_convert` 节点同样支持 GRIB 输入。读取依赖 `cfgrib`+`xarray`（已入 requirements）；离线 fixture `Test/algorithms/fixtures/grib2_t2m_2x2.grib2`，再生成用同目录 `generate_grib2_fixture.py`（需 eccodes，NCEP 参数表：centre=kwbc + heightAboveGround level=2 才能解析出 `t2m`）。
- `herbie` 试装失败可降级为可选依赖（节点自动回退直链），但 `cfgrib`/`xarray` 为 GRIB 读取必需，不可省。
- NSMC 新门户（2026-08-20 逆向）：旧 PortalSite asmx 已 405 重写到 `/data/`，`{base}/{SAT}/MWRID/{date}/` 直链 404——勿再走旧方案。登录链路跨三子域（satellite→fy4 center→data tokensync），密码 RSA 公钥在登录页 `keyCN` 字段（base64url，每次刷新更换）；FY3F ORBA 在线仅 2023-12~2024 年中（与 NAS 3Ffinal 一致），2025+ 检索为空属数据源现实。账号频控提示为中文「您下载频率过于频繁」。
