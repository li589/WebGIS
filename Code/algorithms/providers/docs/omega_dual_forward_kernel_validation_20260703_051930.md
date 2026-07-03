# OMEGA Dual Forward Kernel Validation 20260703_051930

## 目的

本记录用于验证双温前向模型原型是否已经完成与单温路径一致的内核化接入，并观察双温正式口径下的热点分布。

本轮关注点：

1. 双温正式口径是否稳定
2. 双温热点是否迁移到新的标量内核
3. 是否出现数值异常信号

## 本轮代码状态

当前双温链已接入：

- `physics.py::_mironov_dielectric_kernel`
- `physics.py::_fresnel_reflectance_kernel`
- `omega.py::_tb_forward_dual_temp_kernel`

包装层仍保留：

- `omega.py::_tb_forward_dual_temp_with_context`

## 执行命令

```powershell
.\scripts\run_omega_offline_baseline.ps1 -Profiles dual96 -PythonExe "d:\Workspace\mat2py\venv\Scripts\python.exe"
```

```powershell
d:\Workspace\mat2py\venv\Scripts\python.exe debug_omega_profile.py --nt 64 --npix 96 --repeats 1 --pixel-repeats 1 --pixel-samples 2 --trial-count 1 --warmup 0 --exp-mode Exp2 --temp-scheme DUAL --cprofile --cprofile-top 30
```

## dual96 结果

- `execute_omega_retrieval.avg_ms = 12067.264`
- `execute_omega_retrieval.std_ms = 191.000`
- `execute_omega_retrieval.min_ms = 11727.379`
- `execute_omega_retrieval.max_ms = 12295.666`
- `shape = (64, 96)`
- `finite_ratio = 1.0`

- `single_pixel_solver.avg_ms_per_pixel = 124.436`
- `single_pixel_solver.std_ms_per_pixel = 1.319`
- `single_pixel_solver.min_ms_per_pixel = 122.881`
- `single_pixel_solver.max_ms_per_pixel = 126.108`

## 判读

1. `dual96` 当前样本稳定性较好
   - `std_ms = 191.000`
   - `std_ms_per_pixel = 1.319`

2. 当前没有数值异常信号
   - `finite_ratio = 1.0`

3. 双温链端到端耗时已进入一个可信的正式区间
   - 当前可暂记为约 `11.7 ~ 12.3 s`

## cProfile 结果

按 `tottime` 的关键热点：

1. `omega.py::_tb_forward_dual_temp_kernel = 2.239s`
2. `omega.py::_resid_omega_block_dual_temp_prepared = 2.069s`
3. `trf.py::trf_bounds = 1.664s`
4. `_optimize.py::_minimize_scalar_bounded = 1.610s`
5. `omega.py::_finite_difference_jacobian_from_base = 0.974s`
6. `physics.py::_mironov_dielectric_kernel = 0.624s`
7. `omega.py::_tb_forward_dual_temp_with_context = 0.568s`
8. `physics.py::_fresnel_reflectance_kernel = 0.452s`

## 结论

1. 双温热点已与单温路径一样，迁移到新的标量内核
2. `with_context` 包装层已退化为薄包装，不再是前向链主要热点
3. 这说明前向模型内核化方案在双温路径上同样成立

但当前仍不能据此单独宣布“端到端优化已经完成”，原因是：

1. 双温还缺少多轮历史样本用于严格对照
2. residual 与 Jacobian 仍位于热点前列

## 下一步建议

当前最合理的下一步是转向更深层的热点，而不是继续停留在前向包装层：

1. 优先评估 `single/dual residual` 主循环的更深层集成
2. 同时保留当前前向内核边界，不再回退到旧的前向包装实现
3. 如需正式保留决策，可补一轮同规格 `dual96` 复测
