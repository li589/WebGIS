# Brooks-Lint Review

**Mode:** PR Review · Numerical Audit（自定义数值风险码：N1 溢出/偏移、N2 精度截断、N3 数值不稳定、N4 NaN 语义、N5 单位/常数、N6 可复现性、N7 容差/约束缺失）
**Scope:** `Code/algorithms/providers/Python/**`（算法核 / 数据访问 / ingest / analysis / modules / publish），13 个源文件修改 + 7 个新测试文件
**Health Score:** 12/100（审计时点）→ 100/100（修复后复审，全部 12 项确认修复并有测试锁定）

**Trend:** First run — no trend data（按本仓约定不创建 `.brooks-lint-history.json`，保持仓库根整洁）

数值工程质量整体高于典型科研代码（全程 float64、`expm1` 抗相消贯穿、golden fixture rtol=1e-9 锁死 8 组合、随机源全固定），但 4 处 Critical 缺陷集中在"输入校验缺失"与"隐式契约违反"两类，均已在本次提交中修复。

---

## Findings

<!-- 全部 12 项确认缺陷已修复（状态列 ✅）；"接受不改"6 项见文末 -->

### 🔴 Critical

**[N3+N7] C1 — 反演初值未 clamp 进 bounds，单坏像元崩整批**
Symptom: `algorithms/inversion.py` `x0=[0.2, 0.5]` 固定初值未夹入 `bounds=(0.02..porosity, 0..5)`；`ddca_retrieve_grid` 的 valid_mask 缺 porosity 检查。porosity∈(0.02, 0.2) 的像元触发 scipy `ValueError: x0 is infeasible`。`omega.py:1233` 同款问题此前已修，此处属修复遗漏。
Source: The Pragmatic Programmer — Design by Contract（bounds 前置条件被隐式违反）
Consequence: 批量反演中一个低孔隙度像元即令整批任务崩溃，生产链路不可用。
Remedy: ✅ 入口处 porosity 无效（≤0.02 或非有限）直接返回 `(nan, nan)`；`x0` 双分量 clamp 进 bounds；`ddca_retrieve_grid` valid_mask 增加 porosity 检查。新增 `Test/algorithms/test_inversion_x0_bounds.py`（porosity=0.1 单像元不抛、坏像元 NaN 不扩散）。

**[N4+N5] C2 — NetCDF 双重缩放 + 掩码丢失**
Symptom: `data_access/universal_reader.py` 读 netCDF4 变量时未关 auto maskandscale（默认读出已缩放掩码数组），随后又手工 `*scale+offset` 二次缩放；掩码数组经 `np.asarray` 丢弃 mask，fill 值以物理值形态泄漏。另 `:373` 存在 astype 后恒 False 的死条件。
Source: A Philosophy of Software Design — Information Leakage（netCDF4 隐式缩放契约泄漏进读取层）
Consequence: 带 scale/offset 属性的 NetCDF（部分 ERA5/GLDAS 产品）数值整体失真且无任何报错；填充值污染统计。
Remedy: ✅ `var.set_auto_maskandscale(False)` 关闭自动缩放，手工清洗/缩放管线成为唯一真源；MaskedArray 防御性兜底 `filled(fill_value)`；修死条件（仅以原始 `var.dtype == np.int16` 判定）。新增探针测试 `test_universal_reader_netcdf_scaling.py`（先红后绿，断言"恰好一次缩放"）。

**[N1] C3 — 插值目标格网与返回坐标错开半像素**
Symptom: `data_access/spatial_aligner.py` `_coordinate_based_resample` 插值目标用 `np.linspace` 边点轴，而返回坐标用像素中心轴（代码内注释明言"禁止 linspace 边点"），两条路径自相矛盾。
Source: The Pragmatic Programmer — DRY（同一语义两处实现即漂移）
Consequence: HDF5/NetCDF/MAT 全部源的插值结果与坐标系统性错开半像素（0.25° 网格 = 0.125°），SMAP 多源融合空间配准偏差。
Remedy: ✅ 统一改用 `pixel_center_axis(north, south, target_height)`。新增 `test_spatial_aligner_grid_consistency.py`（规则网格源上目标中心处插值值 == 源同位置值，插值轴 == 返回坐标轴）。

**[N4] C4 — GLDAS 插值 NaN 线性涂抹 + 坐标单调性未校验**
Symptom: `ingest/gldas_nc4_to_mat.py` 将含 NaN 的 field 直接交给 `RegularGridInterpolator`（NaN 点进入插值输入），且无 lat/lon 单调性校验。
Source: Code Complete — Defensive Programming（外部数据输入未验证）
Consequence: NaN 沿线性权重涂抹到相邻有效目标格点，海洋边缘陆地像元成片丢失；降序坐标轴触发插值器未定义行为。
Remedy: ✅ 坐标单调性校验（降序翻转、乱序 raise）；全有限走 RegularGridInterpolator 快路径，含 NaN 改 `griddata` 仅以有限点插值。`test_gldas_nc4_to_mat.py` 增补"中心 NaN 邻域不得变 NaN"用例。

### 🟡 Warning

**[N4] W1 — JSON 出口 NaN 字面量非法**
Symptom: `modules/statistics.py` / `stats_histogram.py` 的 `json.dumps` 默认 `allow_nan=True`，全 NaN 栅格时产出含 `NaN` 字面量的非法 JSON。
Source: The Pragmatic Programmer — Crash Early（坏数据应在边界拦截而非外泄）
Consequence: 前端 `JSON.parse` 抛错，图表/表格崩。
Remedy: ✅ 两处加 `_json_safe()`（非有限 float → None）+ `allow_nan=False` 硬门。新增 `test_stats_json_nan_safety.py`（全 NaN 栅格 stats → `json.loads` 可解析且含 null）。

**[N2+N3] W2 — 拟合模块无阶数上限 + inf 落盘**
Symptom: `modules/fitting.py` polyfit 无阶数上限；exp 拟合 p0=(1.0, 0.01) 无量纲感知；`fitted` 对全时间轴求值，b>0 时溢出 inf 且直接写入 MAT。
Source: Code Complete — Defensive Programming（病态输入与越界输出均未设防）
Consequence: 高阶拟合病态；MAT 存入 inf 污染下游消费端。
Remedy: ✅ `1 ≤ degree ≤ 6` 否则 ValueError + RankWarning 转显式日志；exp p0 取 `nanmax(values)`（量纲感知）；落盘前 `fitted[~isfinite] = nan`。新增 `test_fitting_numerics.py`（增长型数据 → MAT 无 inf）。

**[N3] W3 — omega.py h/alpha 初值未 clamp（C1 同模式第 3 处）**
Symptom: `algorithms/omega.py:2502-2507` h/alpha `least_squares` 的 `x0=[h0, alpha0]` 未 clamp 进 bounds。
Source: Refactoring — Duplicated Code（三处复制各自漂移，只修了两处）
Consequence: 上游越界时同样 x0 infeasible 崩溃。
Remedy: ✅ h0/alpha0 clamp 进 `halpha_lower_bounds/halpha_upper_bounds`。

**[N2] W4 — 方差一阶矩公式灾难性相消**
Symptom: `modules/_raster_ops.py` 分块方差用 `E[X²]−E[X]²`：TB~300 K、σ~1 时两个 ~9e4 大数相减丢约 8 位有效数字，跨块朴素累加进一步放大。
Source: The Pragmatic Programmer — 算法选择（正确性与精度先于便利公式）
Consequence: std 相对误差可达 1e-4~1e-3，质检统计不可信。
Remedy: ✅ 改 Welford 逐块 (count, mean, M2) + Chan 合并公式，`var = max(M2/count, 0)`。新增 `test_raster_ops_std_precision.py`（mean=300、σ=1、N=1e6 vs `np.std`，rtol 1e-12；旧公式该场景 ~1e-4）。

**[N4] W5 — FY 预处理 FillValue 属性名不合规且与数据体不一致**
Symptom: `ingest/fy_preprocess.py` 数据体写 NaN、声明 FillValue=-32767 两者不一致；且 `var.FillValue=` 是写数据后设的普通属性，非 CF 标准 `_FillValue`。
Source: Release It! — 隐性契约破坏（下游按标准自动掩膜的消费端无法掩蔽）
Consequence: 标准消费端（xarray/netCDF4 自动掩膜）掩不住填充值；非标准属性名无人识别。
Remedy: ✅ 变量创建期 `createVariable(..., fill_value=np.nan)` 设置标准 `_FillValue`，删除写后属性赋值；执行前已 grep 确认无消费端依赖旧属性名。新增 `test_fy_netcdf_fillvalue.py`。

### 🟢 Suggestion

**[N6] S1 — nanmean 全 NaN 列告警未抑制（与 ndvi.py 不一致）**
Symptom: `algorithms/omega_avg.py` 逐像元 nanmean 在全 NaN 列触发 RuntimeWarning（结果正确仍为 NaN），ndvi.py `_safe_nanmean` 有抑制。
Source: The Pragmatic Programmer — 告警卫生（噪音告警稀释真告警）
Consequence: 告警噪音。
Remedy: ✅ 局部 `catch_warnings + simplefilter("ignore", RuntimeWarning)` 包裹，不引跨模块依赖。

**[N7] S2 — 未知重采样方法名静默回退**
Symptom: `data_access/spatial_aligner.py` `_get_resampling_enum` 未知名静默替换为 bilinear。
Source: The Pragmatic Programmer — Crash Early（fail-loud 优于静默替换）
Consequence: nearest 的"不混合邻域"意图被悄悄丢弃且无提示。
Remedy: ✅ 映射表覆盖 rasterio 全部常用方法（nearest/bilinear/cubic/cubic_spline/lanczos/average/mode/gauss/max/min/med/q1/q3/sum/rms），映射外 ValueError。

**[N2] S3 — 站点均值用朴素 sum（风格不一致）**
Symptom: `algorithms/station.py` Python `sum` 顺序累加。
Source: The Pragmatic Programmer — 风格一致性
Consequence: 量级可忽略（每组仅数条记录），但与全仓数值风格不一致。
Remedy: ✅ 改 `math.fsum(valid_values) / len(valid_values)`。

---

## 接受不改项（核实后决策，就地注释或仅报告记录）

| 位置 | 内容 | 不改依据 |
|---|---|---|
| `physics.py` ε₀=8.854e-12 | 仅 4 位有效数字 | 影响远小于 Mironov 系数经验拟合不确定度；改动需重生成 golden fixture，收益为负。已就地注释锁定原因 |
| `omega.py` `xatol=1e-4` | OMEGA 收敛容差偏松 | 有意设计的产品精度让步，仅文档记录 |
| `preprocess_ops.py` / `gis_ops.py` 111320 m/° | 球面近似，中纬 ~0.2% | 改椭球会改变既有对齐输出，仅报告记录 |
| `timeseries_analysis.py` Kendall tau 分母 | 未修 ties | 统计口径问题非浮点缺陷 |
| float32 落盘（`_raster_ops` / `gis_ops` / `raster_writer`） | 量化 ~1e-7 相对误差 | 文件头已声明"float64 计算、float32 落盘"设计决策 |
| `inversion.py` (inf,inf) 物理罚 | 非有限解惩罚 | TRF 算法约定内的一致语义 |

## Summary

本次数值专项审计确认 4 Critical + 5 Warning + 3 Suggestion 共 12 项缺陷，全部以 TDD（先红后绿）方式修复并以 7 个新测试文件永久锁定；最重要的收获是 C2（NetCDF 双重缩放——静默数值失真）与 C3（半像素配准偏移——多源融合系统性偏差）这两类无报错却持续腐蚀结果的缺陷。golden fixture（rtol=1e-9）原样通过，证明修复未触碰 omega 正向数值路径。全量验证：`Test/algorithms` 581 passed + 28 subtests、backend 算法关联 96 passed、pre-commit Python 侧（ruff / ruff-format / mypy / 通用检查）全部通过；node hooks（frontend eslint/prettier）因 pre-commit 4.6.1 Windows 环境 bug 在启动即崩（`xargs.py len(cmd_exe)` NoneType），本次零前端改动不受影响，已单独记录。
