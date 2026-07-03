# 字段映射与 Shape 契约

## 1. 文档目的

本文档描述当前 `Python/` 目录下已经落地的字段映射机制与 shape 契约。

它解决两个现实问题：

1. 后续真实数据的变量名不一定和当前测试样本一致。
2. 不同模块对输入数组形状的要求必须统一，否则多日、多像元任务会因为广播不一致而失败。

本文档以当前代码实现为准，重点覆盖：

- `ingest/daily_bundle.py`
- `ingest/timeseries_bundle.py`
- `algorithms/omega.py`
- `algorithms/block_inversion.py`
- `algorithms/physics.py`

## 2. 总体原则

当前实现采用“默认字段名 + 可配置别名”的方式：

1. 默认字段名保持与已有 MATLAB 中间产物和当前 Python 测试样本兼容。
2. 当真实数据字段名不同，只需要通过 `JobRequest.algorithm_params` 传入别名，不需要修改源码。
3. pipeline 只负责把 `algorithm_params` 透传给 config builder。
4. 算法层不直接写死外部 MAT 字段名，而是通过字段配置对象取值。

## 3. 入口与 Builder

当前已落地的字段配置 builder 包括：

| 模块 | Builder | 作用 |
|---|---|---|
| `ingest/daily_bundle.py` | `build_daily_bundle_config()` | 配置原始日 MAT、静态场、GLDAS、template 字段名 |
| `algorithms/omega.py` | `build_omega_field_config()` | 配置 `timeseries bundle` 或外部 MAT 的字段名 |
| `algorithms/block_inversion.py` | `build_block_field_config()` | 配置 `block_inversion` 输入 MAT 的字段名 |

这些 builder 都从 `algorithm_params` 读取参数。

## 4. Daily Bundle 字段映射

`daily_bundle` 用于把按日的原始数据组装成标准 bundle。当前支持以下别名参数：

### 4.1 日产品变量

- `tbv_aliases`
- `tbh_aliases`
- `ia_aliases`
- `ts_aliases`
- `vwc_aliases`
- `smap_sm_aliases`
- `ddca_sm_aliases`
- `ndvi_daily_aliases`

### 4.2 静态辅助场

- `landcover_aliases`
- `lat_aliases`
- `lon_aliases`
- `albedo_aliases`
- `b_aliases`
- `sf_static_aliases`
- `bulk_density_aliases`
- `h_aliases`
- `clay_fraction_aliases`
- `ndvi_v_max_aliases`
- `ndvi_v_min_aliases`

### 4.3 GLDAS 与 DUAL 温度

- `gldas_tc_aliases`
- `gldas_tsoil1_aliases`
- `gldas_tsoil2_aliases`
- `gldas_template_slot_index_aliases`
- `gldas_template_day_offset_aliases`

### 4.4 DUAL 温度行为参数

- `temp_scheme`
- `dual_tg_mode`
- `ct_smref`
- `ct_exp`
- `use_gldas_template`
- `save_match_info`
- `fy3d_desc_local_hour`
- `fy3b_desc_local_hour`
- `smap_desc_local_hour`
- `gldas_time_tol_hours`

## 5. Omega 字段映射

`omega.py` 当前把输入分成两类：

1. `timeseries bundle` 的时序矩阵
2. 静态向量、固定 omega 先验、Exp0 标定结果

### 5.1 时序矩阵别名

- `tbv_mat_aliases`
- `tbh_mat_aliases`
- `ia_mat_aliases`
- `ts_mat_aliases`
- `tc_mat_aliases`
- `tg_mat_aliases`
- `smref_mat_aliases`
- `ndvi_mat_aliases`
- `sf_mat_aliases`

### 5.2 静态向量别名

- `albedo_aliases`
- `b_aliases`
- `clay_fraction_aliases`
- `bulk_density_aliases`
- `h_static_aliases`
- `landcover_aliases`
- `ndvi_v_max_aliases`
- `ndvi_v_min_aliases`

### 5.3 固定 omega / Exp0 标定别名

- `omega_fixed_aliases`
- `omega_pft_aliases`
- `exp0_h_aliases`
- `exp0_alpha_aliases`

### 5.4 OMEGA 算法参数

除了字段别名外，`build_omega_config()` 还支持：

- `freq_ghz`
- `temp_scheme`
- `exp_mode`
- `tau_rel_frac`
- `kmin`
- `alpha0`
- `lambda_alpha`
- `bounds_h`
- `bounds_alpha`
- `omega0`
- `bounds_omega`
- `lambda_smooth`
- `lambda_tau`
- `lambda_list`
- `block_days`
- `pixel_chunk_size`
- `use_fixed_omega_for_halpha`
- `use_fixed_omega_in_blocks`
- `fixed_omega_fallback`
- `save_exp2_omega_by_lambda`
- `qc_domega`
- `qc_dtau`
- `qc_dh`

## 6. Block Inversion 字段映射

`block_inversion.py` 当前支持以下别名：

- `tbv_mat_aliases`
- `tbh_mat_aliases`
- `ia_mat_aliases`
- `ts_mat_aliases`
- `ndvi_mat_aliases`
- `sf_mat_aliases`
- `albedo_aliases`
- `b_aliases`
- `clay_fraction_aliases`
- `porosity_aliases`
- `landcover_aliases`
- `ndvi_v_max_aliases`
- `ndvi_v_min_aliases`
- `h_static_aliases`
- `dh_aliases`

## 7. Shape 契约

### 7.1 统一约定

当前代码统一采用以下约定：

- 时序输入：`(nt, npix)`
- 静态输入：`(npix,)`
- 单个标量：允许自动广播
- 单日单像元：允许 `(1, 1)`、`(1,)` 或标量形式

### 7.2 `physics.py`

`vwc_from_ndvi()` 和 `tau_from_ndvi()` 会先把：

- `ndvi_max`
- `ndvi_min`
- `landcover`
- `stem_factor`
- `b_param`
- `theta_deg`

显式广播到与 `ndvi` 相同的目标 shape。

这意味着以下输入组合都可以接受：

1. `ndvi=(nt,npix)`，静态量为 `(npix,)`
2. `ndvi=(nt,npix)`，角度为 `(nt,npix)`
3. `ndvi=(1,npix)`，静态量为标量或 `(npix,)`

### 7.3 `block_inversion.py`

`execute_block_inversion()` 入口会先做两步规范化：

1. `_as_time_pixel_matrix()`：把 `TBv/TBh/IA/Ts/NDVI/SF` 统一成 `(nt, npix)`
2. `_as_static_vector()`：把 `Albedo/B/CF/porosity/LC/NDVI_v_max/NDVI_v_min/H` 统一成 `(npix,)`

这保证了：

1. 多日样本不再依赖手写 `None, :` 广播。
2. 单日样本与多日样本共享同一算法入口。
3. 使用字段别名时，不会因为输入 shape 略有不同而额外修改代码。

## 8. MATCH_INFO 与温度诊断

当 `temp_scheme="DUAL"` 且 `save_match_info=true` 时，当前 `daily_bundle` / `timeseries_bundle` 会保存：

- `match_slot_index`
- `match_day_offset`
- `match_picked_file`
- `match_picked_utc`

时序层对应输出：

- `match_slot_index_mat`
- `match_day_offset_mat`
- `match_picked_file_mat`
- `match_picked_utc_mat`

## 9. QC 诊断

当前 `omega.py` 已接入 `qc_block_jacobian_cond` 的 Python 版，真实输出：

- `qc_condk_mat`
- `qc_sratio_mat`

它们不再是占位常数，而是基于 block Jacobian 的有限差分近似计算。

## 10. 参数示例

下面给一个典型 `algorithm_params` 例子：

```python
algorithm_params = {
    "temp_scheme": "DUAL",
    "use_gldas_template": True,
    "save_match_info": True,
    "exp_mode": "Exp2",
    "lambda_list": "1,10,100,1000",
    "tbv_aliases": "TBV,tbv",
    "smap_sm_aliases": "SM_ref,sm_dca,SM",
    "gldas_tc_aliases": "TC_gldas,Ts_gldas,TC",
    "tbv_mat_aliases": "tbv_custom",
    "smref_mat_aliases": "smref_custom",
    "omega_fixed_aliases": "omega_fix_map,omega_fixed_vec",
}
```

## 11. 推荐做法

为了后续接入真实数据更稳，建议遵守以下实践：

1. 新数据源先只改 `algorithm_params` 别名，不要先改源码。
2. 原始日文件和时序 bundle 的字段名最好分别维护，不要混用。
3. 如果新增模板字段、固定先验字段或 Exp 标定字段，也优先通过 builder 扩展。
4. 任何新模块进入主链前，都应明确自己消费的是“时序矩阵”还是“静态向量”。
