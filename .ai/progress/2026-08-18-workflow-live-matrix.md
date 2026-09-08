# Workflow smoke matrix

- Generated: 2026-08-19 02:27 中国标准时间
- API: http://127.0.0.1:8000
- DATA_ROOT: I:\Geograph_DataSet
- Definitions listed: 42

## Matrix

| batch | workflow_id | run_id | status | elapsed_s | blocker / detail |
|-------|-------------|--------|--------|-----------|------------------|
| A | `weather/tiles/temperature` | `` | succeeded | 0.05 | HTTP 200 bytes=99693 |
| A | `weather/tiles/wind-field` | `` | succeeded | 0.03 | HTTP 200 bytes=71792 |
| B | `weather_temperature_grid_demo` | `run-c416f4c45bb0` | succeeded | 2.05 |  |
| B | `weather_wind_field_demo` | `run-b4cc54e12fcc` | succeeded | 2.08 |  |
| C | `analysis_histogram` | `run-c72b7b8cce7b` | succeeded | 2.04 |  |
| C | `raster_timeseries_curve` | `run-fb135900b25a` | succeeded | 2.04 |  |
| C | `raster_zonal_stats_aligned` | `run-6bcc4d9c0f52` | succeeded | 2.12 |  |
| D | `smap_soil_moisture_local` | `run-1e698b2b1530` | succeeded | 2.04 |  |
| D | `open_data_noaa_grib_sample` | `run-391f2acf359d` | succeeded | 6.13 | NOMADS GFS filter gfs.20260818/12 http_open_data→variable_extract (t2m; archive skipped; cfgrib ok) |
| E | `open_data_nasa_earthdata_sample` | `run-0e8d7f7b0cf1` | succeeded | 4.08 | NASA LP DAAC MCD43A4 browse jpg (public) download-only, anonymous legacy (lp-prod-public 免登录；earthaccess 账号状态不阻断冒烟) |
| E | `open_data_nsidc_smap_sample` | `` | skipped | 0.0 | blocked:runtime (Earthdata ready; NSIDC SMAP granules too large for light smoke — needs curated small path) |
| E | `open_data_esa_product_sample` | `` | skipped | 0.0 | blocked:creds (copernicus profile missing; CDSE $value needs OIDC bearer auth — configure 设置页 copernicus username/password, or BACKEND_COPERNICUS_USERNAME/PASSWORD, or BACKEND_COPERNICUS_TOKEN) |
| F | `omega_block_smap_single` | `run-b9c191481f5c` | succeeded | 515.75 | time_range overridden to 2025-11-01..02 (available mats); compiled graph timeseries_bundle → omega_block |
| F | `omega_avg_daily_smap_single` | `run-828c1895ea03` | succeeded | 8.1 | compiled graph → omega_avg_daily; time_range→2025-12-03..05; parallel disabled for smoke; Stage D limited to 2025-12-07..11 (max 5 days) |
| F | `omega_avg_daily_fy_single` | `run-616fc0e6b5d5` | succeeded | 6.08 | compiled graph → omega_avg_daily; time_range→2025-12-03..05; parallel disabled for smoke; Stage D limited to 2025-12-07..11 (max 5 days) |
| F | `omega_avg_daily_smap_dual` | `run-cd0109f7a4bb` | succeeded | 6.08 | compiled graph → omega_avg_daily; time_range→2025-12-03..05; parallel disabled for smoke; Stage D limited to 2025-12-07..11 (max 5 days); DUAL temp_scheme with local GLDAS .mat; use_gldas_template=true |
| F | `omega_avg_daily_smap_online` | `` | skipped | 0.0 | blocked:config (online download template + needs h5→mat bridge; earthdata portal ready; not light-smoke) |
| F | `omega_avg_daily_gldas_online` | `run-8399fd0b7320` | succeeded | 78.85 | compiled graph → omega_avg_daily; time_range→2025-12-03..05; parallel disabled for smoke; Stage D limited to 2025-12-07..11 (max 5 days); gldas_online graph=D2 only (gldas_download/nc4→mat verified separately); use_gldas_template=true |
| F | `omega_sf_fenkuai_smap_single` | `run-d13c3c5e54f6` | succeeded | 121.4 | light-smoke: 2025-12-03..10 (1×8d block), bbox 110–115E/20–25N, max_pixels=400, serial; keeps output/map_layer |
| F | `omega_sf_fenkuai_fy_single` | `run-faf7d995537b` | succeeded | 119.34 | light-smoke: 2025-12-03..10 (1×8d block), bbox 110–115E/20–25N, max_pixels=400, serial; keeps output/map_layer |
| G | `preprocess_clip_reproject_basic` | `run-64d48dfc478a` | succeeded | 2.02 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_stub_b.tif / smoke_dem.tif / smoke_points.geojson / smoke_pour_points.geojson / smoke_zones.geojson / smoke_timeseries.json / smoke_timeseries_b.json) |
| G | `stats_mean_summary_report_basic` | `run-a9f2df4b0873` | succeeded | 2.05 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_stub_b.tif / smoke_dem.tif / smoke_points.geojson / smoke_pour_points.geojson / smoke_zones.geojson / smoke_timeseries.json / smoke_timeseries_b.json) |
| G | `fusion_idw_interpolate_basic` | `run-370e324ad0d7` | succeeded | 2.04 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_stub_b.tif / smoke_dem.tif / smoke_points.geojson / smoke_pour_points.geojson / smoke_zones.geojson / smoke_timeseries.json / smoke_timeseries_b.json) |
| H | `preprocess_mask_resample_basic` | `run-61315c759195` | succeeded | 2.06 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_stub_b.tif / smoke_dem.tif / smoke_points.geojson / smoke_pour_points.geojson / smoke_zones.geojson / smoke_timeseries.json / smoke_timeseries_b.json) |
| H | `stats_trend_anomaly_basic` | `run-30976c9df7b4` | succeeded | 2.04 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_stub_b.tif / smoke_dem.tif / smoke_points.geojson / smoke_pour_points.geojson / smoke_zones.geojson / smoke_timeseries.json / smoke_timeseries_b.json) |
| H | `fusion_multi_source_merge_basic` | `run-796b25976a6a` | succeeded | 2.05 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_stub_b.tif / smoke_dem.tif / smoke_points.geojson / smoke_pour_points.geojson / smoke_zones.geojson / smoke_timeseries.json / smoke_timeseries_b.json) |
| I | `stats_correlation_basic` | `run-658b4980ed6f` | succeeded | 2.05 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_stub_b.tif / smoke_dem.tif / smoke_points.geojson / smoke_pour_points.geojson / smoke_zones.geojson / smoke_timeseries.json / smoke_timeseries_b.json) |
| I | `stats_correlation_report_basic` | `run-055c65301991` | succeeded | 2.03 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_stub_b.tif / smoke_dem.tif / smoke_points.geojson / smoke_pour_points.geojson / smoke_zones.geojson / smoke_timeseries.json / smoke_timeseries_b.json) |
| I | `stats_summary_chart_basic` | `run-a8aa720f9acd` | succeeded | 2.04 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_stub_b.tif / smoke_dem.tif / smoke_points.geojson / smoke_pour_points.geojson / smoke_zones.geojson / smoke_timeseries.json / smoke_timeseries_b.json) |
| X | `analysis_buffer` | `run-734e33a28880` | succeeded | 2.05 |  |
| X | `analysis_clip` | `run-8058c2113993` | succeeded | 2.04 |  |
| X | `analysis_contour` | `run-8ed246ab36c9` | succeeded | 2.04 |  |
| X | `analysis_raster_calc` | `run-2f380df94fcf` | succeeded | 2.05 |  |
| X | `analysis_raster_to_vector` | `run-89c80c7c9053` | succeeded | 2.05 |  |
| X | `analysis_reclassify` | `run-5137bb211f14` | succeeded | 2.06 |  |
| X | `analysis_slope_aspect` | `run-3673808ab886` | succeeded | 2.02 |  |
| X | `analysis_vector_to_raster` | `run-44763f626ee0` | succeeded | 2.05 |  |
| X | `analysis_watershed` | `run-b5941067784f` | succeeded | 2.05 |  |
| X | `analysis_zonal_stats` | `run-e60758bccf7b` | succeeded | 2.03 |  |
| X | `cds_era5_reanalysis_download` | `run-790b06e786ea` | succeeded | 2.05 | request date 2026-08-11 (UTC-7d, ERA5 ~5d publish lag); cdsapi queue may take minutes |
| X | `cdse_sentinel_download` | `` | skipped | 0.0 | blocked:creds (no copernicus portal account) |
| X | `fy_tb_local_read` | `run-c43096195b16` | succeeded | 2.03 | synthetic FY MWRI HDF5 (Brightness_Temperature) under {DATA_ROOT}/_runtime/synthetic/fy_mwri (seed default {DATA_ROOT}/FY absent) |
| X | `fy_tb_online_read` | `run-1c52575c61fb` | succeeded | 2.05 | single day 2025-12-03 (NAS fy3dhdf2425 window); auto NSMC→NAS fallback |
| X | `ndvi_gee_read` | `` | skipped | 0.0 | blocked:gee-not-configured (accounts=0 enabled=0) |
| X | `ndvi_local_read` | `run-22cf67f100a4` | succeeded | 10.12 | synthetic 16-day NDVI GeoTIFFs (3 scenes, 2025-01/02) under {DATA_ROOT}/_runtime/synthetic/ndvi_16day |
| X | `ndvi_online_read` | `run-99c40ee30142` | succeeded | 113.3 | VNP13C1 16-day window 2025-05-01..16, max_results 5→1 (one ~30MB granule) |
| X | `nomads_gfs_grib_download` | `run-168cb474dab5` | succeeded | 12.15 | date={YYYYMMDD}→latest; search_string=:TMP:2 m subset |
| X | `omega_avg_daily_fy_online` | `run-1a02aee0b8ca` | succeeded | 24.28 | compiled graph → omega_avg_daily; time_range→2025-12-03..05; parallel disabled for smoke; Stage D limited to 2025-12-07..11 (max 5 days); fy_download {YYYYMMDD}→20251203..05 (aligns D2 window) |
| X | `omega_sf_fenkuai_fy_dual` | `run-0f71d8838ca3` | succeeded | 103.28 | light-smoke: 2025-12-03..10 (1×8d block), bbox 110–115E/20–25N, max_pixels=400, serial; keeps output/map_layer |
| X | `omega_sf_fenkuai_fy_online` | `run-150ef9029d93` | succeeded | 174.22 | light-smoke: 2025-12-03..10 (1×8d block), bbox 110–115E/20–25N, max_pixels=400, serial; keeps output/map_layer |
| X | `omega_sf_fenkuai_smap_dual` | `run-f7f5f7737f3a` | succeeded | 109.12 | light-smoke: 2025-12-03..10 (1×8d block), bbox 110–115E/20–25N, max_pixels=400, serial; keeps output/map_layer |
| X | `omega_sf_fenkuai_smap_online` | `run-969dd4ddaff7` | succeeded | 192.25 | light-smoke: 2025-12-03..10 (1×8d block), bbox 110–115E/20–25N, max_pixels=400, serial; keeps output/map_layer |

## Notes

- Batch A is weather tile hot path (not a system seed).
- Batch X = every system seed not in a hardcoded batch; runner
  mappings patch dates/paths per seed (directory scan is the
  source of truth, batches are ordering hints only).
- Template seeds with `{YYYYMMDD}` / `{YYYY-MM-DD}` date
  placeholders get concrete windows patched at submit time
  (cds/cdse/nomads/ndvi_online/fy_online heads).
- Cred-gated seeds (cds/cdse/nsmc/earthdata heads) are skipped
  as `blocked:creds` when the portal store + env are empty;
  `ndvi_gee_read` probes GEE accounts and skips as
  `blocked:gee-not-configured` when none are enabled.
- `fy_tb_local_read` / `ndvi_local_read` run on synthetic
  fixtures under `{DATA_ROOT}/_runtime/synthetic/` (seed default
  paths `{DATA_ROOT}/FY` / `{DATA_ROOT}/NDVI` have no local data).
- Open-data seeds with `REPLACE_*` placeholders were skipped as `blocked:config` / `blocked:creds` (no forged portal paths), except `open_data_noaa_grib_sample` (live NOMADS filter probe) and `open_data_nasa_earthdata_sample` (LP DAAC browse download-only).
- `analysis_histogram` used temp GeoTIFF under `{DATA_ROOT}/_runtime/smoke_hist.tif`.
- `smap_soil_moisture_local` path overridden to `Soil_Moisture/SMAP` (seed default `{DATA_ROOT}/SMAP` missing).
- `omega_block_smap_single` time window overridden to 2025-11-01..02 to match available local mats (seed default Dec 2025).
- `omega_avg_daily` Stage D light-smoke cap enabled (max 5 days) to avoid 365-day long runtimes / OOM.
- Heavy omega chains may fail for missing GLDAS / online deps; recorded without inventing production datasets.

## Verified today (ABCD sprint)

- D1/D2 graph path: `omega_block_*` / `omega_avg_daily_*` submit compiled `workflow_definition` (no smoke flatten).
- fenkuai + `output_map_layer`: SMAP/FY light-smoke keep map_layer (manifest→data accepted).
- NOAA: cfgrib+eccodes available locally → `http_open_data→variable_extract` (`t2m`); CGI `.pl` cache sniff/rename.
- NASA Earthdata: download-only LP DAAC browse JPG.
- `output_map_layer` ArtifactRef-on-`data` fix remains in effect.

## Follow-ups remaining

1. `open_data_nsidc_*` / `esa_*` / `omega_avg_daily_smap_online` (large granules / Copernicus / h5→mat).
2. HPC paper template sync (tunnel/direct still blocked).
3. ~~`omega_avg_daily_gldas_online` may fail when worker lacks Earthdata username/password even if portal token exists in UI.~~ 已解决：worker 门户凭据传播修复后本矩阵实跑成功（78.85s）。

---

## 收口终态（2026-08-19 02:27，最终验收矩阵）

> 本节为人工收口，覆盖上方工具生成内容中已过时的表述。矩阵总计 **52 条：46 succeeded / 0 failed / 6 blocked**（blocked 均为诚实预检拦截，非运行失败）。

### 三段汇总

| 段 | 数量 | 明细 |
|---|---|---|
| 成功 | 46 | 瓦片热路径 2 + 天气 demo 2 + 分析/统计/预处理/融合 15 + 本地数据 2 + 开放数据 2（NOAA/NASA）+ omega 全族 10（block 1、avg_daily 4、fenkuai 5）+ X 批 13（含 cds/fy_local/fy_online/ndvi_local/ndvi_online/nomads） |
| 失败 | 0 | 上轮 8 条失败（ndvi_local 422、fy_local 扩展名、fy_online 日期、cds T-1、gldas_online 凭据、esa 401、fenkuai_smap_online tessa 锁定、nsidc tessa 锁定）全部修复并在本矩阵转绿 |
| blocked | 6 | 见下表专节（凭据 2 / 结构缺口 2 / 数据规模 2） |

### 本轮修复清单（矩阵驱动，提交于 b5e30a6 与本轮提交 2）

| 种子 | 上轮症状 | 修复 | 终态 |
|---|---|---|---|
| `ndvi_local_read` | submit_http_422 | 烟测器注入合成 16 天 NDVI fixture（`datasource_selection.input_dir`） | succeeded 10.12s |
| `fy_tb_local_read` | 不支持的文件格式 .hdf5 | `ingest/fy.py` 扩展名大小写不敏感并接受 `.hdf/.hdf5` 变体 | succeeded 2.03s |
| `fy_tb_online_read` | `time data '20251203' does not match format '%Y-%m-%d'` | `ingest/fy_preprocess.py` 新增 `parse_fy_date`（YYYYMMDD/点分/ISO 宽容解析，与 fy_download 对齐） | succeeded 2.05s |
| `cds_era5_reanalysis_download` | run_failed（T-1 过新） | 烟测器日期补丁 T-1 → T-7（ERA5 ~5d 滞后惯例） | succeeded 2.05s |
| `omega_avg_daily_gldas_online` | worker 缺 Earthdata 账密 | worker 门户凭据解析链修复（portal store 传播） | succeeded 78.85s |
| `open_data_esa_product_sample` | run_failed 401（无凭据硬跑） | 预检诚实化：`portal_creds_ready` 先载 .env 再判凭据；ESA 种子无凭据 → blocked:creds；CDSE OIDC 账密换 Bearer 鉴权链就位（`BACKEND_COPERNICUS_USERNAME/PASSWORD` 主路径） | blocked:creds（诚实） |
| `ndvi_online_read` / `omega_sf_fenkuai_smap_online` | URS 401 [tessa] 被锁定 | 门户凭据存储 earthdata 条目修正为可用账号 | succeeded 113.3s / 192.25s |

### blocked 专节（非失败，处置指引）

| 种子 | 阻塞 | 处置指引 |
|---|---|---|
| `open_data_esa_product_sample`、`cdse_sentinel_download` | blocked:creds（copernicus） | **用户资产**：设置页配置 copernicus 账号密码（OIDC 换 Bearer 主路径）或 `BACKEND_COPERNICUS_USERNAME/PASSWORD`；静态 token 仅 ~10 min 有效不适合长跑。配置后可直接复跑（鉴权链代码已就位并有单测覆盖） |
| `ndvi_gee_read` | blocked:gee-not-configured（accounts=0） | **用户资产**：设置页启用 GEE 账号后复跑 |
| `omega_avg_daily_smap_online` | blocked:config（h5→mat 桥 + 非轻量冒烟） | 结构性缺口（D9 决策，本轮范围外），保持记录 |
| `open_data_nsidc_smap_sample` | blocked:runtime（SMAP granule 过大） | Earthdata 凭据已就绪（预检通过）；需策划小样例路径（curated small granule）后转正式冒烟 |

### 节点通用性重构（N1/N4，随本轮提交 2）

- **N1 标量渲染收敛**：新增 `ScalarGridRenderNode` 参数化基类，dewpoint/humidity/precipitation/pressure/visibility/cloud_cover 六节点改薄壳（对外契约零变更）；temperature 审查后保留独立实现（高度层后缀动态解析为实质差异，docstring 落档）；wind-field 保留（矢量粒子流）。瓦片抽验 4 层全 200。
- **N4 阶段分类声明化**：`register_module` 的 `template_overrides` 支持 `phase` 声明，`_classify_stage` 声明优先、substring 降级；omega 族 / sf_invert / ddca / fy_preprocess / ssh_sync / nsidc / gldas 补声明。
- **N7/N9 文档**：`.ai/skills/workflow-design.md` 新增「新增算法节点接入清单」；portal preset 归一与模板自动派生标注 backlog。

### 回归与质量门（终态）

- 后端全量：`1417 passed, 2 skipped`；算法包全量：`617 passed + 28 subtests`；格式化后定向复验 `45 passed`。
- pre-commit 全量：ruff / ruff-format / mypy / eslint / prettier / 契约检查全过。
- backend 换世代重启后矩阵终态即上表。

