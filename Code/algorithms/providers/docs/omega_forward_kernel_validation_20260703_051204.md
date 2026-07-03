# OMEGA Forward Kernel Validation 20260703_051204

## 目的

本记录用于验证以下改动是否已经在正式口径上体现稳定收益：

1. `Mironov + Fresnel` 标量内核原型
2. 单温 TB 前向模型标量内核原型

约束保持不变：

- 不改数值语义
- 不改求解策略
- 不改 residual 公式

## 本轮代码状态

本轮已接入的热点链如下：

- `physics.py::_mironov_dielectric_kernel`
- `physics.py::_fresnel_reflectance_kernel`
- `omega.py::_tb_forward_single_temp_kernel`

包装层仍然保留：

- `physics.py::mironov_dielectric_from_context`
- `physics.py::fresnel_reflectance_from_context`
- `omega.py::_tb_forward_single_temp_with_context`

## 运行命令

```powershell
.\scripts\run_omega_offline_baseline.ps1 -Profiles formal96 -PythonExe "d:\Workspace\mat2py\venv\Scripts\python.exe"
.\scripts\run_omega_offline_baseline.ps1 -Profiles cprofile96 -PythonExe "d:\Workspace\mat2py\venv\Scripts\python.exe"
```

日志目录：

- `D:\Workspace\mat2py\tmp\omega_offline_baseline\20260703_051204`
- `D:\Workspace\mat2py\tmp\omega_offline_baseline\20260703_051417`

## formal96 结果

- `execute_omega_retrieval.avg_ms = 12725.158`
- `execute_omega_retrieval.std_ms = 208.312`
- `execute_omega_retrieval.min_ms = 12276.155`
- `execute_omega_retrieval.max_ms = 12958.122`
- `shape = (64, 96)`
- `finite_ratio = 1.0`

- `single_pixel_solver.avg_ms_per_pixel = 128.036`
- `single_pixel_solver.std_ms_per_pixel = 1.365`
- `single_pixel_solver.min_ms_per_pixel = 124.856`
- `single_pixel_solver.max_ms_per_pixel = 129.148`

## 与当前稳定基线对照

当前较可信的 `64x96` 稳定区间为：

- `execute_omega_retrieval`: `12.0 ~ 12.6 s`
- `single_pixel_solver`: `126 ~ 133 ms/pixel`

对照判断：

1. `single_pixel_solver` 已落在稳定区间内
   - `128.036 ms/pixel`

2. `execute_omega_retrieval` 略高于当前主参考区间上沿
   - 本轮 `12.725 s`
   - 相比 `12.0 ~ 12.6 s`，没有形成明确的正式层收益

3. 稳定性本身是好的
   - `std_ms = 208.312`
   - 与第二次稳定样本 `170.702` 同一量级

## cProfile 结果

Top 热点按 `tottime`：

1. `omega.py::_tb_forward_single_temp_kernel = 1.943s`
2. `omega.py::_resid_omega_block_single_temp_prepared = 1.725s`
3. `trf.py::trf_bounds = 1.468s`
4. `_optimize.py::_minimize_scalar_bounded = 1.387s`
5. `omega.py::_finite_difference_jacobian_from_base = 0.848s`
6. `physics.py::_mironov_dielectric_kernel = 0.532s`
7. `omega.py::_tb_forward_single_temp_with_context = 0.519s`
8. `physics.py::_fresnel_reflectance_kernel = 0.400s`

## 与旧热点对照

旧 `cprofile96` 关键热点为：

- `_tb_forward_single_temp_with_context = 2.029s`
- `fresnel_reflectance_from_context = 1.249s`
- `mironov_dielectric_from_context = 0.587s`

本轮关键热点为：

- `_tb_forward_single_temp_kernel = 1.943s`
- `_tb_forward_single_temp_with_context = 0.519s`
- `_mironov_dielectric_kernel = 0.532s`
- `_fresnel_reflectance_kernel = 0.400s`

判读：

1. 热点已经明显迁移到新的标量核
2. `with_context` 包装层的内部耗时显著下降
3. `fresnel` 路径内部耗时下降最明显
4. 说明“内核化方向”是对的

但同时：

1. 正式层总时间还没有稳定优于当前 `formal96` 保留阈值
2. 这说明仅完成“前向模型链内核化”还不足以单独带来明确的端到端收益
3. 第二热点 `_resid_omega_block_single_temp_prepared` 和 Jacobian 路径仍然在吞噬主要收益

## 结论

结论分两层：

### 方向判断

- `保留方向`
- 前向模型内核化是有效方向，热点迁移符合预期

### 当前代码状态判断

- `暂不以 formal96 收益为依据宣布阶段成功`
- 原因是端到端总时间尚未稳定压低到当前主正式基线以下

## 下一步建议

当前最合理的下一步有两种，优先推荐第一种：

1. 继续把同样模式应用到双温前向模型
   - 先让 `_tb_forward_dual_temp_with_context` 也进入同样的标量内核路径

2. 或开始评估 residual 主循环的更深层集成
   - 仅在保持当前边界清晰的前提下推进

不建议当前就宣布“本轮优化保留并完成”。

更准确的说法应是：

- 前向模型内核化原型已经验证方向正确
- 但还需要继续扩展或更深层集成，才能在正式口径上形成清晰收益
