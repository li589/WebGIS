# OMEGA Formal96 Comparison And Next Steps

## 样本范围

本文档对比两次 `formal96` 离线正式基线结果，并据此判断当前 `64x96` 规模下的稳定区间与下一阶段仍值得投入的优化方向。

对比样本：

1. `20260703_033324`
2. `20260703_033850`

## 两次结果

### 样本 1：`20260703_033324`

- `execute_omega_retrieval.avg_ms = 13098.743`
- `execute_omega_retrieval.std_ms = 916.236`
- `single_pixel_solver.avg_ms_per_pixel = 145.925`
- `single_pixel_solver.std_ms_per_pixel = 21.913`

### 样本 2：`20260703_033850`

- `execute_omega_retrieval.avg_ms = 12168.557`
- `execute_omega_retrieval.std_ms = 170.702`
- `single_pixel_solver.avg_ms_per_pixel = 127.892`
- `single_pixel_solver.std_ms_per_pixel = 2.171`

## 对比结论

1. 第二次样本明显更稳定
   - `std_ms` 从 `916.236` 降到 `170.702`
   - `std_ms_per_pixel` 从 `21.913` 降到 `2.171`

2. 第一次样本大概率受到环境噪声影响
   - 作为“正式层第一版样本”有效
   - 但不宜单独作为唯一决策依据

3. 当前 `64x96` 更可信的正式参考区间应偏向第二次样本
   - `execute_omega_retrieval` 可暂按 `12.0 ~ 12.6 s` 估计
   - `single_pixel_solver` 可暂按 `126 ~ 133 ms/pixel` 估计

4. 如果后续再引入新优化
   - 只要正式层均值没有稳定低于上述区间，就不建议保留

## 热点一致性

`cprofile96` 结果表明热点排序仍稳定：

1. `_tb_forward_single_temp_with_context`
2. `_resid_omega_block_single_temp_prepared`
3. `trf_bounds`
4. `_minimize_scalar_bounded`
5. `fresnel_reflectance_from_context`
6. `_finite_difference_jacobian_from_base`

这说明当前系统的主要耗时不再是零碎的 Python 接线层，而是：

- 前向模型本体
- block residual 主循环
- SciPy 求解器内部
- 有限差分 Jacobian

## 不建议继续优先尝试的方向

以下方向已被证明收益不稳定或边际过小，不建议继续优先投入：

1. `ddca cost_func` 小数组构造微调
2. `block residual` 逐元素去 `float(...)` 包装
3. context-only helper 的轻量替换
4. `scan_exp2_lambda` 的无平滑 residual 闭包复用
5. 其他类似“看起来更轻、但只改 Python 包装”的零散微优化

## 下一阶段仍值得投入的方向

在不改变数值语义的前提下，仍有价值的方向如下。

### 1. 前向模型内核级加速

目标函数：

- `_tb_forward_single_temp_with_context`
- `fresnel_reflectance_from_context`
- `mironov_dielectric_from_context`

原因：

- 这条链是当前最稳定的头号热点
- 调用次数巨大，任何稳定收益都会被放大

建议方式：

- 评估 Numba/JIT 路线
- 严格保持输入输出与数值口径不变
- 用正式基线和回归测试双重验证

### 2. block residual 主循环的更深层实现优化

目标函数：

- `_resid_omega_block_single_temp_prepared`

原因：

- 它仍是第二大热点
- 但 Python 层微调已基本见顶

建议方式：

- 不再做逐元素包装微调
- 只考虑更深层的实现替换，例如 JIT 或更紧凑的数据路径

### 3. Jacobian 路径优化

目标函数：

- `_finite_difference_jacobian_from_base`

原因：

- 它持续稳定地占据热点前列
- 当前仍有显著累计时间

建议方式：

- 保持同样的差分语义
- 重点考虑更低开销的实现方式，而不是改动差分公式

### 4. 正式层扩展验证

建议新增：

- `formal192`
- `dual96`

原因：

- 先确认现有稳定区间在更大规模和双温路径上是否成立
- 避免在单一路径上做出过拟合优化

## 当前建议

下一阶段不建议直接回到 `omega.py` 做新的接线层微调。

更合理的顺序是：

1. 用当前脚本补跑 `formal192`
2. 视需要补跑 `dual96`
3. 如果仍要继续提速，优先评估“前向模型 / residual / Jacobian”的更深层实现优化路线

当前这份对照应作为后续所有 OMEGA 优化是否值得保留的正式参考入口。
