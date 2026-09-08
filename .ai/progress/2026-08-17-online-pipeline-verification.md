# 在线管线端到端验证与两个上游根因修复（2026-08-17）

接续 2026-08-16 数据源系统收尾（`2026-08-16-data-source-system-completion.md`）。本轮聚焦 FY/SMAP 在线反演种子（`omega_sf_fenkuai_{fy,smap}_online`）的端到端打通：两个运行期根因（NSMC 自签证书、NSIDC version 格式）修复 + 三图层产出验证 + 全量回归。

## 一、运行期根因与修复

### R1. NSMC 门户自签证书 → FY 下载全线失败

**现象**：`fy_download` 所有账号报 `SSL: CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain`，归为 transient_upstream 重试 3 次后失败。

**诊断**：`satellite.nsmc.org.cn` 使用内部自签 CA（Python `ssl` 默认验证与 `openssl s_client` 均确认 `self-signed certificate in certificate chain`），公共信任库无法验证——站点现状，非本机环境问题。

**修复**（`data_access/sources/http.py`）：
- 新增 `ssl_context_for(uri, meta)`：域名白名单级放宽。默认白名单仅 `satellite.nsmc.org.cn`（精确主机名匹配，子域不放行），其余 HTTPS 保持严格验证。
- 环境变量 `CGDA_HTTP_INSECURE_HOSTS` 可覆盖（逗号分隔；空串恢复全严格）。
- 请求级 `metadata["ssl_verify"]=false` 可显式放宽。
- 每次放宽记 `logger.warning` 便于审计。
- `_download` 与 `_conditional_revalidate` 的 `urlopen` 均接入 context。

**测试**：`Test/algorithms/test_http_source_ssl.py`（7 项：默认白名单/其他域严格/env 覆盖/空串恢复/请求级放宽/子域不放宽）。

**安全边界**：凭据为 token 基础；放宽仅限显式域名；默认值含 NSMC 是因为该门户证书长期自签（科研内网站点现状），可通过环境变量一键收回。

### R2. NSIDC CMR version 格式 → SMAP"0 文件下载成功"

**现象**：`Downloaded: 0/0 skipped=0 failed=0`（1 秒完成），下游 `No SMAP HDF5 files found`，重试 3 次失败。表面看像"该日无数据"。

**诊断**（CMR 实测）：
- `SPL3SMP_E` + `version=6` + 2025-12-27 → **0 hits**
- `SPL3SMP_E` + `version=006` + 2025-12-27 → **1 hit**（`SMAP_L3_SM_P_E_20251227_R19240_001.h5`）
- V6 数据实际覆盖至 2026-08-15（非常新），V5 已下线（0 hits）。

CMR `version_id` 惯例 3 位零填充（`006`），节点模板/用户习惯写 `6`，earthaccess 原样透传导致 0 命中。

**修复**（`ingest/nsidc_download.py`）：
- 新增 `_version_variants()`：纯数字短版本追加 `zfill(3)` 变体（`"6"` → `["6", "006"]`）；非数字（GLDAS `"2.1"`）原样。
- `search_granules()` 按变体顺序查询，首个非空结果胜出。

**测试**：`Test/algorithms/test_nsidc_version_variants.py`（7 项：变体生成/earthaccess 回退/首个命中即停/CMR 回退路径）。

### R3.（既有）僵尸 run 清理策略实战验证

跨两次服务重启的 run-0bcd69bf7e71（retry_pending）/run-bb47d0e7e77b（running@35%）停止在下载节点；`cleanup_stale_workflow_runs` 正确未误杀（running 不清理策略生效），经 cancel+retry 路径重新派发。G2 重派发洪水修复（queue_dispatch_service task_id 去重）在 Beat 周期下未再出现重复投递。

## 二、端到端验证（在线 run，终态已确认）

| 阶段 | FY（NSMC 多账号） | SMAP（NSIDC Earthdata） |
|------|-------------------|--------------------------|
| 凭据 | 门户凭据库 nsmc 3 账号（account_count=3） | 门户凭据库 earthdata（URS token） |
| 下载 | R1 修复后 ✓（SSL 白名单生效） | R2 修复后 ✓（granule 命中 + HDF5 提取通过） |
| 反演 | **✓ succeeded**（run-a4d9f44b72e7，2026-08-16 19:59 UTC） | **✓ succeeded**（run-92437dfb54c9，2026-08-16 21:44 UTC 派发） |
| 三图层 | **✓ main_layers=[SM, VOD, OMEGA]**（manifest `run-a4d9f44b72e7.json`） | **✓ main_layers=[SM, VOD, OMEGA]**（manifest `run-92437dfb54c9.json`） |

产物证据（两端一致，`I:\Geograph_DataSet\_runtime\python_provider\products\omega_sf_fenkuai\run-*\`）：
- `omega_pft.mat` / `omega_pixel.mat`（Ω 反演）、`block_000.mat` + `20251227_20251231.mat`（SM/VOD/Ω 分块）。
- FY run：n_pixels_success=146218（FY 轨道覆盖范围），grid [1624,3856]；SMAP run 断点续传（`.omega_sf_chunk_checkpoint.json`）生效，重试后 ~20 分钟完成。

**孤儿 run 处置**：SMAP 首派发 run-00f198a9ba8b 在昨夜 worker 重启后滞留 running@35%（事件停于 chunk 22/32）；cancel + retry 后由断点检查点续跑成功。再次验证 cancel+retry 是 worker 重启后孤儿任务的标准恢复路径。

## 二b、合并组图层 readiness 修复（本轮新增）

**问题**：合并组虚拟图层（`fy-omega-inversion` 风云 ω 反演 / `smap-omega-inversion` SMAP ω 反演 / `soil-moisture` / `precipitation-static`）在 `/layers` 中因 `overlay_registry` 无对应资产被标 `blocked`，未聚合成员状态——即使全部成员源就绪也显示"未就绪"。

**修复**（`app/services/workflow_request_resolver.py`）：新增 `_describe_merged_group_readiness`，`describe_layer_run_readiness` 对 `is_merged_group and members` 的描述符优先走成员聚合：任一成员 ready → 组 ready，summary 形如"合并组虚拟条目：N/M 个成员源就绪"，未就绪成员列入 notes。

**测试**：`Test/backend/test_workflow_request_resolver.py` 新增 3 项（全就绪聚合 / 部分就绪 / 全阻塞），已随全量回归通过。

**实测**（`GET /layers`）：`fy-omega-inversion` ready(2/2)、`smap-omega-inversion` ready(2/2)、`soil-moisture` ready(4/4)、`precipitation-static` ready(2/2)；目录 52 层无 `omega_sf_fenkuai_**` 占位图层。注意 `layer_router` 有 30s readiness 缓存，修复后需等缓存过期或重启后端生效。

## 二c、CDS ERA5 提交链路修复与许可阻塞

- `_tmp_submit_cds.py` 初版以画布形态直提 `workflow_definition`（缺 `outputs`），执行期 `Missing required field: workflow_definition.outputs` 失败；改为经 `compile_litegraph_to_workflow_definition` 编译后提交（outputs 自动生成 `node:n1.manifest`），提交链路打通。
- run-805faa56132d 失败根因：**403 `required licences not accepted`**——CDS 账号未在网页端接受 `reanalysis-era5-single-levels` 数据集许可。
- **08-17 复测**（run-0704cfd155cb，06:25 本地）：用户已注册账号并配置 API Key（`BACKEND_CDS_API_KEY` 已入 `Code/backend/.env`），cdsapi 检索已成功到达 CDS API，但仍返回同一 403——数据集许可仍未在网页端勾选。代码侧无遗留；用户登录后打开 https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels?tab=download#manage-licences 接受许可，重跑 `_tmp_submit_cds.py` 即可。
- **08-17 终态：许可接受后全链路打通**（run-4b2495310a17，07:57 succeeded）。插曲：账号队列一度被 8 个外部大请求（GRIB/全年份/全月日时次/海气-植被-土壤三组变量，非 CGDA 发出——CGDA 仅发过单变量小区块验证请求）占满，触发 CDS 平台限流（每用户 CDS-MARS 并发 1 Running + 每数据集排队上限，报 400 "temporarily limited"）；用户清空队列后重提即成功。产物 `I:\Geograph_DataSet\_runtime\python_provider\data_access\cds\reanalysis-era5-single-levels_44246c38.zip` 经 xarray 校验：u10、2025-12-27、20.25–25.5°N/109.8–117.2°E、22×31、-7.08~0.80 m/s，CF/cfgrib 转换正确。
- 小瑕疵（**08-17 已修**）：`download_format=unarchived` 时内容为裸 NetCDF 但文件名仍按模板落 `.zip` 后缀。修复：`cds_download.default_filename` 新增 `_target_extension`——unarchived 时按 `data_format` 落 `.nc`/`.grib`（未声明按 CDS 默认 GRIB），zip/未声明保持 `.zip`。测试 +4 项（Test/algorithms/test_cds_download_node.py 共 29 passed）；`restart backend` 后实拉复验：同请求落盘 `reanalysis-era5-single-levels_44246c38.nc`（run-40118aa81803 succeeded）。

## 二d、Earthdata 凭据纠偏与门户多账号核验（前端会话补录）

**问题**：SMAP 在线下载全线 401/锁定。排查发现门户凭据库 `earthdata` 条目被误存为 **tessa / **********（******** 实为风云账号 415114178@qq.com 的密码，用户名 tessa 亦非本人 Earthdata 账号）；08-16 实测通过的是 **Rejoyce / **********（`_tmp_probe2.py` 中 Basic auth 实证）。错误用户名反复尝试触发 URS 账号锁定。

**修复**：经后端 API 将 `earthdata` 凭据更新为 Rejoyce，earthaccess 真实登录探测通过；重提 SMAP 在线 run 后下载/反演全链路成功（见第二节终态）。

**多账号核验**（V5）：nsmc 3 账号（轮换就绪）✓、earthdata=Rejoyce enabled ✓。

## 二e、结果图层导出链路打通（前端会话补录）

- 后端 `export_layer.py` 新增 overlay registry 分支：`POST /export/layer?layer_id=<overlay_id>` 对物化结果图层（`imported-*`）直接导出，不再要求 importedRaster 之外的路径。
- 在线 API 实测（FY run 三物化图层）：tif 706,230 B ✓ / mat 1,500,096 B ✓ / png 158,373 B ✓ / nc 671,292 B ✓ / geojson 正确 400 ✓ / 不存在 id 正确 404 ✓。
- 导出 TIF 经 rasterio 校验：EPSG:6933（EASE2 9km）、1624×3856、nodata -9999、有效最大值 0.7216 与 MAT 分析一致。
- 新增 `Test/backend/test_export_layer_overlay.py`（7/7 通过）。


## 三、回归测试

| 套件 | 结果 |
|------|------|
| pytest Test/backend + Test/algorithms（全量，第一轮） | **1854 passed, 2 skipped**（560s） |
| pytest 全量复跑（08-17 早，`--basetemp=Test/.pytest-be`） | 1029 passed / 307 errors / 7 failed——**basetemp 目录 `Test/.pytest-be` 损坏（WinError 5 拒绝访问）**，307 error 全部源于 fixture 建目录失败，非代码回归 |
| pytest 全量复跑（换新 basetemp `.pytest-bet8`） | **1885 passed / 4 failed / 2 skipped**（496s）；4 个 failed 均为 `test_http_materialize_status.py` 的 `fake_urlopen` 桩未接收 R1 修复新增的 `context=` 参数（测试桩漂移，非产品缺陷），补 `context=None` 后该文件 6/6 复绿 |
| 新增 `test_bounding_box_contract.py` | 13 passed |
| 新增 `test_http_source_ssl.py` | 7 passed |
| 新增 `test_nsidc_version_variants.py` | 7 passed（含既有 credentials 3 项共 10 passed） |
| 新增 `test_export_layer_overlay.py` | 7 passed |
| `npm run check:openapi` | OK（east/west maximum=360 已同步） |
| `npm run check:catalog` | OK（52 items + 7 categories） |
| `npm run lint` | 0 errors（2 项既有 warning，非本轮引入） |
| `npm run build` | ✓（5.65s） |
| `npm run test`（vitest） | 08-16：943/943 passed + 11-12 个 worker errors（当时归因 CPU 满载）；**08-17 空载复跑 ×2（默认 / `--maxWorkers=4`）：938/938 tests、132/132 files 全绿，但同样 13 个 `[vitest-pool] Failed to start forks worker` error 依旧，且为确定性同批文件**——排除 CPU 竞争假设。根因：vitest dist 硬编码 `START_TIMEOUT=6e4`（60s fork→started 握手），本机 worker 冷启动（fork + import + 跨 root transform，累计 transform ~480s）超时被杀；无配置项可调。CI Ubuntu 快速 fork 不受影响。缓解建议：为仓库目录与 node.exe 添加 Windows Defender 排除项 |

## 四、ECMWF 风场再分析缺口（已关闭）

代码链路与用户侧配置均已就绪并实证：`BACKEND_CDS_API_KEY`（`Code/backend/.env`）→ `portal_credentials["ecmwf_cds"]` → `download/cds_download` 节点（`ingest/cds_download.py`）→ CDS 排队下载 → 本地 NetCDF（见二c 终态，run-4b2495310a17 succeeded、产物经 xarray 校验）。后续经工作流「CDS 下载」节点即可拉取 ERA5 风场再分析。

## 五、遗留清单

1. ~~`Test/.pytest-be*` 损坏 basetemp 目录~~ **用户已于 08-17 在管理员终端删除**，回归 basetemp 问题关闭。
2. ~~ECMWF CDS 实拉验证~~ **已完成**（run-4b2495310a17，见二c 终态）；~~`unarchived` 格式 `.zip` 后缀命名小瑕疵~~ **已修**（见二c 末条，run-40118aa81803 实拉复验 `.nc` 命名）。
3. vitest worker-start errors（13 个，确定性）：已定性为环境问题（见第三节），非代码回归；如需消除，为仓库与 node.exe 配置 Defender 排除项后观察。
