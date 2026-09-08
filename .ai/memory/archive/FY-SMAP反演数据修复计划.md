# FY/SMAP 反演数据修复计划

## 摘要

当前 omega_sf_fenkuai 流水线产出的 FY 和 SMAP 反演数据存在严重问题：输出数据破碎、非洲南部连成一片、无 8 天带状特征。经全面代码审计，根因涵盖**变量名不匹配导致 SM 参考数据丢失**、**FY 模式下入射角来源错误**、**NDVI 极值文件名不匹配**、**工作流 bbox 与 GLOBAL 域不一致**、**时间序列交集过度收窄**等多个层面。本计划按严重程度分级修复，目标是通过 UI 全流程跑通并产出与 Matlab 参考一致的 8 天分块反演结果。

## 现状分析

### 数据流全链路

```
[SMAP HDF5] → ingest/smap.py → SMAP YYYYMMDD.mat (sm_dca/vwc/Ts/TBv/TBh/IA)
[FY HDF]    → ingest/fy.py + fy_preprocess.py → FY YYYYMMDD.mat (TBv/TBh/IA)
[NDVI]      → ingest/ndvi_hdf_preprocess.py → NDVI DOY climatology (1.mat~366.mat)
[Ancillary] → IGBP_9km_12.mat / Albedo.mat / B.mat / SF.mat / BD.mat / H.mat / CF.mat / VI_v_qa.mat
                                    ↓
              omega_sf.py::retrieve_omega_sf_daily()
                1. _build_time_series() — 扫描文件夹取日期交集
                2. _load_ancillary() — 加载静态辅助库
                3. make_viirs8_blocks() — 8 天分块
                4. _preload_chunk() — 逐 chunk 预读每日数据 ★问题集中区
                5. execute_pixel_inversion() — 逐像元反演
                6. 汇总输出 → block YYYYMMDD_YYYYMMDD.mat
```

### 已确认的问题清单

| # | 严重度 | 问题 | 位置 | 影响 |
|---|--------|------|------|------|
| 1 | **致命** | SM 参考变量名不匹配：代码查找 `("SM","SM_mat","soil_moisture")`，SMAP MAT 实际为 `sm_dca` | `omega_sf.py` L1896 | `sm_ref` 全 NaN → `ok_base` 全 False → 所有像元反演失败 → 输出全 NaN |
| 2 | **致命** | FY 模式 IA 来源错误：`tb_source="FY"` 时 IA 始终从 SMAP 文件读取，应从 FY 文件读取 | `omega_sf.py` L1882-1886 | 入射角错误 → 前向模型错误 → 反演结果错误 |
| 3 | **严重** | NDVI 极值文件名不匹配：代码查找 `NDVI_extrema.mat`，实际文件为 `VI_v_qa.mat` | `omega_sf.py` L1707 | `NDVI_v_max/min` 未加载 → Tau VWC2 计算使用错误极值 |
| 4 | **严重** | Tau 计算使用 NDVI 气候态极值替代 NDVI 历史极值 | `omega_sf.py` L1355-1360 | Matlab 用 `NDVI_v_max/min`（VI_v_qa.mat），Python 用 `ndvi_clim_max/min`（NDVI_clim 文件夹），两者来源和数值不同 |
| 5 | **严重** | 工作流 bbox 仅覆盖中国（73-137°E, 15-59°N），但 `run_domain="GLOBAL"` | workflow seeds JSON | 域不一致，可能导致数据过滤混乱 |
| 6 | **中等** | 时间序列交集过度收窄：任何数据源缺日均会减少可用日期 | `omega_sf.py` L1527-1568 | FY 数据缺天多时可用天数骤降 → 每 8 天块内有效天不足 → 输出破碎 |
| 7 | **中等** | FY3B→FY3D 匹配未在预读中调用 | `omega_sf.py` `_preload_chunk` | `fy_platform="3B"` 时亮温未校正 → 反演偏差 |
| 8 | **中等** | MAT v7.3 转置一致性未校验 | `mat_bundle.py` | 若服务器 MAT 为 v7.3 且转置处理不一致 → 像元错位 |
| 9 | **低** | `make_viirs8_blocks` 硬编码 8 天，未使用 `config.block_days` | `omega_sf.py` L293 | 改 `block_days` 非默认值时分块与 gap 检测不一致 |
| 10 | **低** | NDVI 气候态构建未考虑闰年 DOY 366 | `omega_sf.py` L1751-1792 | 闰年最后一天可能缺数据 |

### 关键根因分析

**"数据破碎"根因**：问题 #1 导致 `sm_ref` 全 NaN，`ok_base` 掩码全 False，绝大多数像元反演失败。即使部分像元因数据文件变量名恰好匹配而通过，有效像元也极为稀疏，导致输出破碎。

**"非洲南部连成一片"根因**：问题 #2（IA 来源错误）和 #4（NDVI 极值错误）导致反演参数错误，OMEGA 值在同类植被区域趋于一致。结合 `omega_fixed_mode="PFT"` 模式，同类 PFT 像元被赋予相同 OMEGA，使整个非洲南部 savanna 区域呈现为一片均匀值。

**"无 8 天带状特征"根因**：问题 #6 导致可用天数不足，8 天块内有效数据稀疏，无法形成完整空间覆盖的带状图。Matlab 参考实现中，8 天块输出为完整的 2D 网格（每像元取块内有效 OMEGA 中位数），应呈现连续空间覆盖。

## 修复方案

### 修复 1：SM 参考变量名对齐（致命）

**文件**：`Code/algorithms/providers/Python/algorithms/omega_sf.py`
**位置**：`_preload_chunk` 函数，约 L1896

**现状**：
```python
for key in ("SM", "SM_mat", "soil_moisture"):
    if key in smap_data:
```

**修复**：对齐 `daily_bundle.py` 的 `smap_sm_aliases`，将 `sm_dca` 加入首选：
```python
for key in ("sm_dca", "SM", "SM_mat", "soil_moisture", "sm"):
    if key in smap_data:
```

同时修复 `sm_source="DDCA"` 时的变量名查找（DDCA SM 文件变量名为 `SM`，已正确，但需确保别名列表一致）。

### 修复 2：FY 模式入射角来源修正（致命）

**文件**：`Code/algorithms/providers/Python/algorithms/omega_sf.py`
**位置**：`_preload_chunk` 函数，约 L1848-1886

**现状**：IA 始终从 `smap_data`（SMAP 文件）读取，无论 `tb_source` 是 FY 还是 SMAP。

**修复**：当 `tb_source="FY"` 时，IA 应从 FY TB 文件读取（与 TBv/TBh 同源）：
```python
# 在 FY TB 加载块中追加 IA 读取
if config.tb_source.upper() == "FY":
    tb_folder = fy3d_folder if config.fy_platform.upper() == "3D" else fy3b_folder
    tb_file = Path(tb_folder) / f"{date_str}.mat"
    if tb_file.exists():
        tb_data = load_mat_file(str(tb_file))
        # TBv / TBh（已有）
        for key in ("TBv_mat", "TBv"):
            ...
        # IA 从 FY 文件读取（新增）
        for key in ("IA", "IA_mat"):
            if key in tb_data:
                vals = np.asarray(tb_data[key], dtype=np.float64).ravel()
                ia_mat[k, : len(vals)] = vals[lin_pix]
                break
else:
    # SMAP 模式：IA 从 SMAP 文件读取（已有逻辑保留）
    for key in ("IA", "IA_mat"):
        if key in smap_data:
            ...
```

**注意**：需将现有 IA 加载块从"始终从 SMAP 读取"改为"仅 SMAP 模式从 SMAP 读取，FY 模式从 FY 文件读取"。

### 修复 3：NDVI 极值文件名修正（严重）

**文件**：`Code/algorithms/providers/Python/algorithms/omega_sf.py`
**位置**：`_load_ancillary` 函数，约 L1707

**现状**：
```python
ndvi_extrema_path = root / "NDVI_extrema.mat"
```

**修复**：增加 `VI_v_qa.mat` 作为首选文件名：
```python
for fname in ("VI_v_qa.mat", "NDVI_extrema.mat", "ndvi_extrema.mat"):
    ndvi_extrema_path = root / fname
    if ndvi_extrema_path.exists():
        data = load_mat_file(str(ndvi_extrema_path))
        for key in ("NDVI_v_max", "ndvi_v_max"):
            if key in data:
                anc["ndvi_v_max"] = np.asarray(data[key], dtype=np.float64).ravel()
                break
        for key in ("NDVI_v_min", "ndvi_v_min"):
            if key in data:
                anc["ndvi_v_min"] = np.asarray(data[key], dtype=np.float64).ravel()
                break
        break
```

### 修复 4：Tau 计算使用正确的 NDVI 极值（严重）

**文件**：`Code/algorithms/providers/Python/algorithms/omega_sf.py`
**位置**：`retrieve_omega_sf_daily` 函数中的 `execute_pixel_inversion` 调用，约 L1355-1360

**现状**：
```python
ndvi_max=float(ndvi_clim_max[lin_idx])  # 气候态极值
ndvi_min=float(ndvi_clim_min[lin_idx])  # 气候态极值
```

**修复**：优先使用 `NDVI_v_max`/`NDVI_v_min`（历史极值），回退到气候态极值：
```python
ndvi_v_max = anc.get("ndvi_v_max", np.full(npix, np.nan))
ndvi_v_min = anc.get("ndvi_v_min", np.full(npix, np.nan))

# 在调用 execute_pixel_inversion 时：
ndvi_max=float(ndvi_v_max[lin_idx]) if np.isfinite(ndvi_v_max[lin_idx]) else float(ndvi_clim_max[lin_idx])
ndvi_min=float(ndvi_v_min[lin_idx]) if np.isfinite(ndvi_v_min[lin_idx]) else float(ndvi_clim_min[lin_idx])
```

**依据**：Matlab `Tau.m` 使用 `NDVI_v_max`/`NDVI_v_min`（来自 `VI_v_qa.mat`）做 VWC2 归一化；`NDVI_clim_max`/`NDVI_clim_min`（来自 NDVI_clim 文件夹）仅用于 SF 倒推。两者用途不同，不可混用。

### 修复 5：工作流 bbox 修正（严重）

**文件**：
- `Code/backend/workflow_seeds/system/omega_sf_fenkuai_fy_single.json`
- `Code/backend/workflow_seeds/system/omega_sf_fenkuai_smap_single.json`

**现状**：bbox 节点设为中国区域（west=73, south=15, east=137, north=59），但 `run_domain="GLOBAL"`。

**修复**：将 bbox 改为全球范围（与 GLOBAL 一致），或移除 bbox 节点：
```json
{
  "west": -180.0,
  "south": -90.0,
  "east": 180.0,
  "north": 90.0,
  "crs": "EPSG:4326"
}
```

### 修复 6：时间序列构建策略优化（中等）

**文件**：`Code/algorithms/providers/Python/algorithms/omega_sf.py`
**位置**：`_build_time_series` 函数，约 L1527-1568

**现状**：取所有数据源的日期**交集**，任何数据源缺天都会减少可用天数。

**修复**：改为保留全日期列表，在逐日预读时按实际可用性处理缺天（数据为 NaN），而非提前剔除日期。这样 8 天块结构保持完整，块内缺天数据为 NaN 不影响块级中位数聚合：
```python
def _build_time_series(config, smap_folder, ndvi_folder, fy3d_folder, fy3b_folder, ddca_sm_folder):
    start = datetime.strptime(config.start_date, "%Y%m%d")
    end = datetime.strptime(config.end_date, "%Y%m%d")
    tvec_req = [start + timedelta(days=i) for i in range((end - start).days + 1)]

    # 仅做日志记录各数据源可用日期数，不再取交集
    t_smap = _scan_folder_dates(smap_folder)
    logger.info("[TIME] SMAP 可用日期：%d", len(t_smap))
    if config.tb_source.upper() == "FY":
        tb_folder = fy3d_folder if config.fy_platform.upper() == "3D" else fy3b_folder
        t_tb = _scan_folder_dates(tb_folder)
        logger.info("[TIME] FY TB 可用日期：%d", len(t_tb))
    # ... 其他数据源日志

    # 保留完整日期序列，缺天数据在 _preload_chunk 中为 NaN
    return sorted(tvec_req)
```

**注意**：这与 Matlab 行为一致——Matlab 中 `T_base = intersect(tvec_req, T_tb) ∩ T_smap` 取交集，但 Matlab 的 SMAP/FY 数据通常覆盖完整。Python 端若数据不完整，改为保留全日期更稳健。需确保 `_preload_chunk` 和 `execute_pixel_inversion` 正确处理 NaN 天（已有 NaN 处理逻辑）。

### 修复 7：FY3B→FY3D 匹配在预读中调用（中等）

**文件**：`Code/algorithms/providers/Python/algorithms/omega_sf.py`
**位置**：`_preload_chunk` 函数

**现状**：`match_fy3b_to_fy3d` 函数已定义（L330）但未在 `_preload_chunk` 中调用。当 `fy_platform="3B"` 且 `match_enable=True` 时，FY3B 亮温未校正到 FY3D 等效。

**修复**：在 `_preload_chunk` 中，当 `fy_platform="3B"` 且 `match_enable=True` 时，预加载 2019 年训练期 FY3B/FY3D 数据，计算 bias 参数，并在逐日加载 FY3B TB 时应用校正：
```python
# 在 chunk 循环前，若需要匹配则预计算
if (config.tb_source.upper() == "FY"
    and config.fy_platform.upper() == "3B"
    and config.match_enable):
    match_info = _precompute_fy3b_match(config, fy3b_folder, fy3d_folder)
    # 在每日 FY3B TB 加载后应用校正
    # tbv_corrected = match_info.bias_v * tbv + match_info.bias_intercept_v
```

**注意**：当前工作流种子使用 `fy_platform="3D"`，此修复为 `3B` 模式的正确性保障。

### 修复 8：MAT v7.3 转置校验（中等）

**文件**：`Code/algorithms/providers/Python/algorithms/omega_sf.py`
**位置**：`_preload_chunk` 函数和 `_load_ancillary` 函数

**修复**：在加载数据后增加网格形状一致性校验：
```python
# 在 _preload_chunk 中，首次加载 SMAP/FY 数据时校验
if k == 0 and len(vals) > 0:
    expected_size = nrows * ncols
    if len(vals) != expected_size:
        logger.warning(
            "[CHECK] %s 变量 %s 大小 %d != 网格大小 %d，可能存在转置/维度问题",
            f.name, key, len(vals), expected_size
        )
```

同时确认 `mat_bundle.py` 的 `_normalize_hdf5_mat_value` 对 v7.3 MAT 的转置处理覆盖所有读取路径。

### 修复 9：make_viirs8_blocks 参数化（低）

**文件**：`Code/algorithms/providers/Python/algorithms/omega_sf.py`
**位置**：`make_viirs8_blocks` 函数，约 L270-313

**修复**：将硬编码的 `8` 替换为参数：
```python
def make_viirs8_blocks(tvec: Sequence[datetime], block_days: int = 8) -> BlockStructure:
    ...
    blk_starts_raw = [
        datetime(y, 1, 1) + timedelta(days=block_days * ((d - 1) // block_days))
        for y, d in zip(yy, doy)
    ]
```

在 `retrieve_omega_sf_daily` 调用处传入 `config.block_days`：
```python
block_struct = make_viirs8_blocks(tvec, config.block_days)
```

### 修复 10：增加诊断日志和健康检查（工程化保障）

**文件**：`Code/algorithms/providers/Python/algorithms/omega_sf.py`

**修复**：在关键节点增加诊断日志，便于排查：
1. **时间序列构建后**：打印各数据源可用日期数和交集后日期数
2. **辅助库加载后**：打印各变量形状、有效像元数
3. **每个 chunk 预读后**：打印各变量非 NaN 像元比例
4. **反演完成后**：打印成功/失败比、各 PFT 类成功数
5. **输出保存后**：打印各 block 文件的有效像元数

```python
# 示例：chunk 预读后诊断
for var_name in ("tbv", "tbh", "ia", "ts", "sm_ref", "ndvi", "sf"):
    arr = chunk_data[var_name]
    valid_ratio = np.isfinite(arr).sum() / arr.size
    logger.info("[DIAG] chunk %d %s 有效率: %.1f%%", ci, var_name, valid_ratio * 100)
```

## 验证步骤

### 单元测试验证

1. **变量名匹配测试**：
   ```bash
   cd Code/algorithms/providers/Python
   pytest tests/ -k "omega_sf" -v
   ```

2. **物理量计算测试**：
   ```bash
   pytest tests/test_physics_kernels.py tests/test_omega_forward_kernels.py -v
   ```

### 集成验证（需数据）

3. **小范围端到端测试**：使用少量天数（如 1 月 1-16 日，2 个 8 天块）和子区域数据运行 omega_sf_fenkuai，验证：
   - `sm_ref` 非全 NaN
   - IA 在 FY 模式下来自 FY 文件
   - 输出 block 文件中 SM/VOD/OMEGA 网格有有效值
   - 8 天块数量和日期范围正确

4. **与 Matlab 参考对比**：使用相同输入数据和配置运行 Matlab `omega_sf_fenkuai.m` 和 Python `retrieve_omega_sf_daily`，对比：
   - OMEGA_pft（17 个值）
   - 逐 block OMEGA 网格（数值差异 < 1e-3）
   - 逐像元 OMEGA 中位数图

### UI 全流程验证

5. **工作流种子验证**：
   ```bash
   cd Code/backend
   pytest tests/test_workflow_routes.py tests/test_business_regression.py -q
   ```

6. **UI 端到端**：
   - 启动后端 `Env\Python312\python.exe launch.py start fastapi`
   - 启动前端 `Env\Python312\python.exe launch.py start frontend`
   - 在 UI 中选择 "SF 块反演全流程（FY 单温度）" 工作流
   - 配置数据源路径指向本地/远程数据
   - 运行工作流，观察：
     - 进度日志显示各变量有效率 > 0%
     - 输出 block 文件按 8 天间隔生成
     - 前端图层渲染显示带状空间覆盖（非破碎/非均匀一片）
     - 时间轴上每个 8 天块可切换查看

## 假设与决策

1. **数据可用性假设**：假设 SMAP 逐日 MAT、FY3D 逐日 MAT、辅助库（IGBP/Albedo/B/SF/BD/H/CF/VI_v_qa）、NDVI 气候态均已落盘且变量名与 Excel 配置一致。若实际数据变量名不同，需在修复时调整别名列表。

2. **PFT 模式决策**：保留 `omega_fixed_mode="PFT"` 作为默认（与 Matlab 一致），但在 Exp0 首次运行时 `omega_fixed=None`（无预存 PFT 文件），走逐像元 OMEGA 反演路径。PFT 聚合仅用于后续实验（Exp1a/1b）的固定 OMEGA。

3. **时间序列策略决策**：从严格交集改为保留全日期（缺天为 NaN），以保持 8 天块结构完整。这与 Matlab 在数据完整时行为一致，在数据不完整时更稳健。

4. **bbox 决策**：将工作流种子的 bbox 改为全球范围，与 `run_domain="GLOBAL"` 一致。bbox 仅用于前端可视化范围提示，不用于数据过滤。

5. **不修改的范围**：不修改 `daily_bundle.py` / `omega_avg.py` 的数据加载逻辑（已正确处理 `sm_dca` 别名）；不修改 `physics.py` / `inversion.py` 的物理模型实现（已与 Matlab 对齐）；不修改前端渲染逻辑（假设前端能正确渲染 MAT 网格数据）。
