# OMEGA Offline Result 20260703_033324

## 基本信息

- 日期：2026-07-03
- 记录人：TRAE
- 工作区状态：未继续修改 `omega.py` 数值路径，仅运行离线正式基线
- 分支或提交号：未记录
- 本轮是否包含新代码改动：否
- 改动摘要：使用既有稳定代码状态，执行 `formal96 + cprofile96` 基线

## 运行环境

- 机器：本地 Windows 工作站
- 电源模式：未显式记录
- Python 解释器：`python`
- 依赖环境是否固定：按当前工作区环境执行
- 是否关闭其他高负载程序：未显式记录

## 执行命令

```powershell
.\scripts\run_omega_offline_baseline.ps1 -Profiles formal96,cprofile96 -OutputRoot .\tmp\omega_offline_baseline_runs
```

- Profiles：`formal96,cprofile96`
- OutputRoot：`D:\Workspace\mat2py\tmp\omega_offline_baseline_runs`
- 日志目录：`D:\Workspace\mat2py\tmp\omega_offline_baseline_runs\20260703_033324`

## 结果摘要

### `execute_omega_retrieval`

- `avg_ms`：`13098.743`（`formal96`，7 次 trial）
- `std_ms`：`916.236`
- `min_ms`：`12247.370`
- `max_ms`：`15116.810`
- `shape`：`(64, 96)`
- `finite_ratio`：`1.0`

### `single_pixel_solver`

- `avg_ms_per_pixel`：`145.925`
- `std_ms_per_pixel`：`21.913`
- `min_ms_per_pixel`：`124.903`
- `max_ms_per_pixel`：`186.526`
- `mean_n_use`：`64.0`

## cProfile Top 10

按 `tottime` 统计：

1. `_tb_forward_single_temp_with_context`：`2.029s`
2. `_resid_omega_block_single_temp_prepared`：`1.765s`
3. `trf_bounds`：`1.466s`
4. `_minimize_scalar_bounded`：`1.395s`
5. `fresnel_reflectance_from_context`：`1.249s`
6. `_finite_difference_jacobian_from_base`：`0.822s`
7. `CL_scaling_vector`：`0.643s`
8. `mironov_dielectric_from_context`：`0.587s`
9. `_linalg.norm`：`0.528s`
10. `make_strictly_feasible`：`0.494s`

补充高相关热点：

- `cost_func`：`0.432s`
- `objective`：`0.378s`
- `numpy.array`：`0.333s`
- `numpy.asarray`：`0.222s`

## 与上一轮对比

- 对比基线来源：IDE 交互参考层 `64x48`
- `execute_omega_retrieval` 是否更快：否，`64x96` 本就属于更大正式层，主要用于正式口径，不应与 `64x48` 直接比快慢
- `std_ms` 是否明显放大：是，`formal96` 的方差较大，说明正式层仍存在环境噪声，需要后续继续积累样本
- `single_pixel_solver` 是否同步变化：是，单像元平均约 `145.925 ms/pixel`
- 热点排序是否符合预期：是，仍然集中在前向模型、block residual、SciPy 求解框架和 Jacobian
- 是否命中了已证伪候选：否，本轮没有引入新微优化

## 判定

1. `formal96` 已成功建立一组可复用的离线正式基线
2. 当前结果适合作为后续 `64x96` 规模上的第一版正式对照样本
3. 由于 `std_ms` 仍较大，后续如果要判定“某次优化是否值得保留”，仍建议至少补一轮同规格复测
4. 本轮没有新代码改动，因此不存在“保留/回退代码”的决策，只是建立正式口径

## 最终结论

- 判定：`保留`
- 原因：本轮结果作为离线正式基线样本有效，且热点分布与已有结论一致
- 下一步建议：
  - 先补跑一次同规格 `formal96` 复测，缩小噪声不确定性
  - 若下一轮确有新优化，再使用本结果作为正式对照
  - 在进入更大规模判断前，可补跑 `formal192`

## 附注

- 是否需要补跑 `formal192`：建议
- 是否需要补跑 `dual96`：如后续关注双温路径，建议
- 是否需要补跑 `cprofile96`：当前已有一份，可在新改动后再补
