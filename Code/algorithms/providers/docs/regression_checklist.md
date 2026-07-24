# 轻量级跨模块回归测试清单

本文档用于当前 MATLAB -> Python 迁移阶段的轻量回归收口。
目标不是一次性覆盖全部科学细节，而是优先卡住最近几轮审计中已经修复过的高价值契约与口径风险。

## 1. 使用原则

- 优先覆盖会导致结果偏差、契约漂移或调度链失效的问题。
- 每条用例尽量使用最小输入，避免依赖真实全量数据。
- 优先验证 `ProductManifest`、`ProductRef.type`、关键字段命名、跨日期行为和错误语义。
- 能用合成小矩阵或临时目录完成的，不引入额外大型样例。

## 2. P0 清单

### 2.1 `SMAP-01` 时间窗过滤与产品标签

- 目标：目录中存在范围外文件时，只转换 `time_range` 内文件。
- 断言：
  - 仅输出时间窗内的 `YYYYMMDD.mat`
  - `ProductRef.type == "smap_daily_mat"`
  - `ProductRef.tags["date_key"]` 与文件名一致
- 涉及文件：
  - `Python/ingest/smap.py`
  - `Python/pipelines/smap_products.py`

### 2.2 `NDVI-02` 跨年年度拆分与多年聚合

- 目标：跨自然年时间窗时，`VI_viirs_YYYY.mat` 必须按年拆分，`VI_v_qa.mat` 只合并本次运行年度结果。
- 断言：
  - 当次运行覆盖的每个自然年都生成一个 `VI_viirs_YYYY.mat`
  - 复用 `quality_output_dir` 且目录内存在历史年度文件时，`VI_v_qa.mat` 不被污染
  - `ProductRef.type` 分别为 `ndvi_yearly_qa_mat` 与 `ndvi_multi_year_qa_mat`
- 涉及文件：
  - `Python/algorithms/ndvi.py`
  - `Python/pipelines/ndvi_products.py`

### 2.3 `Station-02` 筛选阈值与 `site -> grid -> net` 聚合

- 目标：站点筛选阈值与 MATLAB `C2/C4` 风格验证链保持一致。
- 断言：
  - 深度、SM 范围、过境小时筛选生效
  - 产出 `site/grid/net` 三层验证 MAT
  - network 聚合先做 grid 内平均，再做 network 平均
  - 验证文件类型为 `station_site_validation_mat`、`station_grid_validation_mat`、`station_net_validation_mat`
- 涉及文件：
  - `Python/algorithms/station.py`
  - `Python/pipelines/station_products.py`

### 2.4 `Bundle-03` 时序 bundle 缺日与结构异常语义

- 目标：`timeseries_bundle` 只把真实缺文件记入 `missing_dates`，结构错误继续上抛。
- 断言：
  - 缺日文件触发 `missing_dates`
  - 字段缺失或 shape 错误触发 `KeyError/ValueError`
  - 不允许把结构错误伪装成缺日
- 涉及文件：
  - `Python/ingest/daily_bundle.py`
  - `Python/ingest/timeseries_bundle.py`
  - `Python/pipelines/timeseries_bundle_products.py`

### 2.5 `Retrieval-02` OMEGA 固定 8 天块与断档重置

- 目标：OMEGA 主链保持当前已审定的 MATLAB 对齐行为。
- 断言：
  - 分块按年内 DOY 锚定固定 8 天块
  - 大时间断档后 `omega_prev` 被重置
  - `Exp1a` 缺失 `Exp0` 标定时直接报错
  - `qc_condk_mat` / `qc_sratio_mat` 为真实计算结果而非占位值
- 涉及文件：
  - `Python/algorithms/omega.py`
  - `Python/pipelines/retrieval_workflow_products.py`

### 2.6 `Dispatch-01` `run_job()` 主流程闭环

- 目标：统一入口必须稳定执行 `plan -> prepare -> execute -> write_manifest`。
- 断言：
  - `plan()` 先于 `execute()` 调用
  - `DataSourceAdapter` 经历 `discover -> resolve -> acquire -> materialize`
  - `_prepared_bundles` 被注入 `request.datasource_selection`
  - 成功时返回 `JobResult.status == "success"` 且 `manifest_uri` 非空
- 涉及文件：
  - `Python/runner/dispatch.py`
  - `Python/runner/registry.py`

### 2.7 `D2-01` omega_avg_daily 四阶段闭环

- 目标：D2 avg-omega 在合成小数据上 Stage A–D 可复现，产物类型稳定。
- 输入：`Tools/test_data/omega_avg_daily_inputs/`（omega_block / smap_daily / ndvi_daily / anc）
- 断言：
  - Stage A–D 均产出预期中间/最终文件
  - `ProductRef.type` 覆盖 SM / VOD / OMEGA 日 MAT（见模块实现）
  - 系统种子 `omega_avg_daily_smap_single` 等 JSON 可被定义服务加载
- 涉及命令 / 文件：
  - `pytest Code/backend/tests/test_omega_avg_algorithm.py Code/backend/tests/test_omega_avg_daily_module.py -q`
  - `python Tools/test_data_production_e2e.py --category C --no-pytest`（可选）
  - `Python/modules/omega_avg_daily.py`、`Python/algorithms/omega_avg.py`

### 2.8 `NDVI-A1A2` HDF → 9 km GeoTIFF

- 目标：A1/A2 预处理契约（日期解析、QA 掩膜、输出命名）稳定；Matlab 树只读。
- 断言：
  - `parse_ydoy_from_filename` 对齐 Matlab `hdfname(10:16)`
  - `apply_ndvi_qa_mask`：`QA>=2` 与越界值置 NaN，再 `*1e-4`
  - 模块名 `ndvi_hdf_preprocess`，产物类型 `ndvi_9km_tif`
- 涉及文件：
  - `Python/ingest/ndvi_hdf_preprocess.py`
  - `Python/modules/ndvi_hdf_preprocess.py`
  - `Python/tests/test_ndvi_hdf_preprocess.py`

### 2.9 `NDVI-SG` SG polyorder 偏差说明

- Matlab `vi_sg_interp` 历史默认 **polyorder=6**（window=9）。
- Python 核心 `algorithms/ndvi.py` 默认 **polyorder=3**（自由度更稳健；无法严格复现旧结果）。
- `modules/ndvi.py` / `pipelines/ndvi_products.py` 默认已对齐为 3；严格 Matlab 回放请显式传 `algorithm_params.sg_polyorder=6`。

## 3. P1 清单

### 3.1 `FY-01` 计划模式与数据模式分支

- 目标：`fy_daily_pipeline` 的 `plan_only` 与 `data_products` 契约稳定。
- 断言：
  - `execute_commands = false` 时只产出 `fy_daily_job_plan` / `fy_daily_command_plan`
  - `execute_commands = true` 且输出存在时，额外登记 `fy_daily_tif` 与 `fy_daily_mat`
  - `main_layers` 只在数据产物存在时包含 `TBv/TBh/IA`
- 涉及文件：
  - `Python/pipelines/fy_products.py`
  - `Python/algorithms/fy.py`

### 3.2 `FY-02` TIF 解包为物理量

- 目标：多波段 FY TIF 解包后的 `TBv/TBh/IA` 与当前 MATLAB B2/B3 口径一致。
- 断言：
  - `TB = packed * scale + offset`
  - `IA = packed * scale`
  - 波段数不足时直接报错
- 涉及文件：
  - `Python/pipelines/fy_products.py`
  - `Python/algorithms/fy.py`

### 3.3 `NDVI-01` 日产品与 QA 开关

- 目标：`emit_quality_products` 开关只控制 QA 产物，不影响逐日 NDVI。
- 断言：
  - 开启时生成 `daily_ndvi_mat`、`ndvi_yearly_qa_mat`、`ndvi_multi_year_qa_mat`
  - 关闭时仅生成 `daily_ndvi_mat`
- 涉及文件：
  - `Python/pipelines/ndvi_products.py`

### 3.4 `Bundle-02` DUAL 温度层与匹配诊断层可发现性

- 目标：`TEMP_SCHEME=DUAL` 且 `save_match_info=True` 时，manifest 需显式暴露温度层与匹配层。
- 断言：
  - `daily_bundle` 暴露 `TC/Tsoil1/Tsoil2/Ct/TG`
  - `timeseries_bundle` 暴露对应 `*_mat`
  - `match_slot_index/day_offset/picked_file/picked_utc` 被登记到 manifest
- 涉及文件：
  - `Python/pipelines/daily_bundle_products.py`
  - `Python/pipelines/timeseries_bundle_products.py`

### 3.5 `Retrieval-01` `dh/ddca/omega` 三模式输出分支

- 目标：统一 workflow 管线按模式输出正确的 block 产物与按日产物。
- 断言：
  - `dh` 产出 `dh_block_mat` 与 `dh_daily_mat`
  - `ddca` 产出 `sm_vod_block_mat`、`sm_daily_mat`、`vod_daily_mat`
  - `omega` 产出 `omega_block_mat`、`omega_daily_mat`，并挂载 `qc_layers`
- 涉及文件：
  - `Python/pipelines/retrieval_workflow_products.py`
  - `Python/algorithms/block_inversion.py`
  - `Python/algorithms/omega.py`

## 4. P2 清单

### 4.1 `SMAP-02` 数据清洗语义

- 目标：无效填充值、越界温度、越界 TB/VWC 统一转 `NaN`。
- 涉及文件：
  - `Python/ingest/smap.py`

### 4.2 `NDVI-03` climatology 缺字段错误语义

- 目标：DOY climatology 缺失 `NDVI_clim` 时抛 `KeyError`，不静默跳过。
- 涉及文件：
  - `Python/pipelines/ndvi_products.py`

### 4.3 `Station-01` `daily/am6` 双产物命名

- 目标：ISMN 与 CASMOS 都稳定产出 `station_daily_mat` 与 `station_am6_mat`。
- 涉及文件：
  - `Python/pipelines/station_products.py`

### 4.4 `Dispatch-02` 失败闭环

- 目标：任一步骤抛异常时，`run_job()` 必须回传失败结果并通知调度器。
- 涉及文件：
  - `Python/runner/dispatch.py`

## 5. 最小执行组合

如果当前只做一轮“轻量但足够可信”的回归，建议至少执行以下 6 条：

- `SMAP-01`
- `NDVI-02`
- `Station-02`
- `Bundle-03`
- `Retrieval-02`
- `Dispatch-01`

## 6. 落地建议

- 单模块用例优先用临时目录 + 合成小矩阵构造输入。
- `run_job()` 验收优先使用假 pipeline + 假 adapter，先锁定统一入口契约，再逐步替换成真实 pipeline。
- 真数据 smoke test 保留在最后阶段，只作为科学口径补充验证，不替代契约回归。
