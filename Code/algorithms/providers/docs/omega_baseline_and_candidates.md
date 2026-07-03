# OMEGA Baseline And Candidates

## 状态

- 更新时间：2026-07-03
- 当前代码状态：前向模型标量核已接入单温与双温主路径；residual/solver/Jacobian 的后续深层原型均未保留
- 阅读建议：本文件用于查看“当前稳定基线 + 已证伪候选”；历史路线图请结合 `omega_forward_kernel_optimization_plan.md` 与 `omega_residual_solver_deep_plan.md` 一起看

## 目标

本文档用于收口 OMEGA 当前阶段的性能工作，明确以下内容：

- 哪些优化已经验证有效并保留
- 哪些候选已经被证伪，不应重复尝试
- 当前可参考的稳定基线是什么
- 后续离线正式基线应如何运行，避免继续在 IDE 交互时限内做高噪声判断

约束前提：

- 不修改 MATLAB 代码
- 准确性和可靠性优先于性能
- 不改数值语义、不改求解策略、不改边界定义
- Python 侧优化仅允许减少包装、闭包、重复准备和局部固定开销

## 当前保留的稳定优化

以下改动已经通过多轮 profiling 验证，收益相对稳定，可以保留：

1. `solve_block_omega()` 的 residual 闭包预绑定
   - 位置：`Python/algorithms/omega.py`
   - 作用：减少 block 求解路径上的重复字典取值、重复包装和闭包内参数搬运

2. `solve_block_omega()` 的 `objective()` 直接消费 residual 向量
   - 位置：`Python/algorithms/omega.py`
   - 作用：避免 `np.asarray(...).reshape(-1)` 的重复往返

3. `halpha` 求解入口显式闭包化
   - 位置：`Python/algorithms/omega.py`
   - 作用：减少 `lambda` 和 `float(...)` 包装层的重复开销

4. prepared residual 中的 `count` 获取改为 `len(tbv)`
   - 位置：`Python/algorithms/omega.py`
   - 作用：减少一次高频 `np.asarray(...).size`

## 已证伪候选

以下候选已经做过实测。结论是收益不稳定、无明显收益或直接回退，后续不建议重复尝试。

1. 将 `ddca/halpha` 切换到新的 2 参数有界优化 helper
   - 现象：真实规模 profiling 明显变慢
   - 处理：已回退，继续使用 `least_squares + 专用 Jacobian`

2. 对 `_resid_omega_block_*_prepared()` 和 `_finite_difference_jacobian_from_base()` 做局部缓存/别名微优化
   - 现象：收益不稳定，部分场景回退
   - 处理：已回退

3. 在 `ddca_single_temp()` / `ddca_dual_temp()` 中把 `np.array([...])` 改成 `np.empty(3)` 再逐项赋值
   - 现象：单次结果偶尔变好，但复测后全量路径收益不稳定
   - 处理：已回退

4. 在 `_resid_omega_block_single_temp_prepared()` 最热分支中去掉循环内 `float(...)` 包装
   - 现象：单像元和全量路径均可能变慢
   - 处理：已回退

5. 为 block residual 单独拆 context-only helper 并替换 prepared residual 调用
   - 现象：全量路径偶尔变好，但多轮复测不稳定
   - 处理：已回退

6. 在 `scan_exp2_lambda()` 中预创建并复用“无平滑 residual 闭包”
   - 现象：从代码直觉上更轻，但真实路径没有稳定收益
   - 处理：已回退

7. 为单温 `_resid_omega_block_single_temp_prepared()` 的 context 热路径单独拆紧凑 helper
   - 现象：单元测试与 `cProfile` 可通过，但两轮 `formal96` 明显退化到约 `16.7 ~ 18.6 s`
   - 处理：已回退，不建议继续沿这个方向做局部循环层替换

8. 将 `_finite_difference_jacobian_from_base()` 改为单试探向量顺序评估 forward/backward
   - 现象：分支语义测试可通过，但两轮 `formal96` 明显退化到约 `16.5 ~ 20.0 s`
   - 处理：已回退，不建议继续沿这个方向做 Jacobian 内部状态切换微调

9. 将 `block_residual_function -> solve_block_omega` 改造成显式 evaluator 边界，并引入 `cost()/residual()/scalar_jacobian()`
   - 现象：语义测试与基础回归可通过，但 `formal96` 退化到约 `18.9 s`，且 `cProfile` 中新 `cost()` 分发进入热点前列
   - 处理：已回退，设计稿可保留，但第一版 evaluator 原型代码不建议保留

## 当前热点结论

在当前稳定代码状态下，热点已经较清楚，继续靠微调 Python 接线层获取收益的空间较小。主要耗时集中在：

1. `_tb_forward_single_temp_kernel` / `_tb_forward_dual_temp_kernel`
2. `_resid_omega_block_single_temp_prepared` / `_resid_omega_block_dual_temp_prepared`
3. `scipy.optimize` 内部的 `trf_bounds`
4. `solve_block_omega()` 中的 `objective()` 与 `minimize_scalar`
5. `_finite_difference_jacobian_from_base`

这说明后续若仍坚持“不改数值语义、不改求解策略”，就不应再反复尝试零散的逐元素微优化。

补充说明：

- `_tb_forward_single_temp_with_context` 与 `_tb_forward_dual_temp_with_context` 现在主要承担 context 拆包职责，不再是前向链的真实计算主体
- physics 层的 `Mironov/Fresnel` 标量核与 `Numba` fallback 机制已落地，但端到端正式层收益尚不足以单独宣布“前向阶段完成”

## IDE 内稳定参考基线

由于 IDE 交互运行存在明显环境噪声，下面的结果只应视为“在线参考区间”，不应作为最终正式结论。

推荐参考命令：

```powershell
python debug_omega_profile.py --nt 64 --npix 48 --repeats 1 --pixel-repeats 1 --pixel-samples 6 --trial-count 3 --warmup 1 --exp-mode Exp2
```

当前在线参考区间：

- `single_pixel_solver` 约 `128 ~ 135 ms/pixel`
- `execute_omega_retrieval` 约 `6.25 ~ 6.45 s`

说明：

- 超出上述区间的单次结果，优先视为环境噪声或调度波动，不要直接据此决定保留/回退代码
- 在线结果更适合做“明显变快/明显变慢”的快速筛查，不适合作为最终基准

## 离线正式基线方案

后续性能工作建议转到离线、长时限、低噪声环境中执行正式基线。推荐步骤如下。

### 1. 环境要求

- 使用固定 Python 环境，不在 IDE 交互时限内运行
- 接电源并使用高性能电源模式
- 关闭无关的 CPU/IO 重负载程序
- 同一批基线不要混用不同 Python 解释器或不同依赖版本

### 2. 基线分层

先做 3 层基线，而不是直接只跑一个规模：

1. 交互参考层
   - `nt=64, npix=48`
   - 目的：快速判断是否有明显回退

2. 中等正式层
   - `nt=64, npix=96`
   - 目的：更接近真实规模，适合作为主要比较口径

3. 大规模正式层
   - `nt=64, npix=192`
   - 目的：验证优化在更接近批处理负载下是否仍成立

### 3. 推荐命令

中等正式层：

```powershell
python debug_omega_profile.py --nt 64 --npix 96 --repeats 1 --pixel-repeats 1 --pixel-samples 8 --trial-count 7 --warmup 2 --exp-mode Exp2
```

大规模正式层：

```powershell
python debug_omega_profile.py --nt 64 --npix 192 --repeats 1 --pixel-repeats 1 --pixel-samples 8 --trial-count 5 --warmup 2 --exp-mode Exp2
```

热点核对：

```powershell
python debug_omega_profile.py --nt 64 --npix 96 --repeats 1 --pixel-repeats 1 --pixel-samples 2 --trial-count 1 --warmup 0 --exp-mode Exp2 --cprofile --cprofile-top 30
```

如需覆盖双温路径，可额外执行：

```powershell
python debug_omega_profile.py --nt 64 --npix 96 --repeats 1 --pixel-repeats 1 --pixel-samples 8 --trial-count 5 --warmup 2 --exp-mode Exp2 --temp-scheme DUAL
```

### 4. 结果判定规则

离线正式基线建议按以下规则判断是否保留改动：

1. 先看 `execute_omega_retrieval` 的均值
   - 这是最重要的正式口径

2. 再看标准差和最小/最大值
   - 若均值下降很小，但标准差明显变大，不应认定为稳定收益

3. 再看 `single_pixel_solver`
   - 它只用来辅助解释热点，不应单独决定保留/回退

4. 必须配合 `cProfile`
   - 若总时间变快，但热点没有明显对上，优先怀疑样本噪声

### 5. 建议记录格式

每次正式基线都建议记录以下字段：

- git 提交或工作区状态标识
- 命令全文
- `trial_count`
- `warmup`
- `avg_ms` / `std_ms`
- `avg_ms_per_pixel` / `std_ms_per_pixel`
- `finite_ratio`
- cProfile 前 10 个热点
- 最终结论：保留 / 回退 / 待复测

## 后续策略

当前阶段建议：

1. 停止继续微调 `omega.py` 的 Python 接线层
2. 不再重复尝试本文档中“已证伪候选”
3. 后续如需继续优化，先跑离线正式基线
4. 只有在离线正式基线显示稳定收益时，才考虑保留新增改动

这份文档应作为下一阶段 OMEGA 性能工作的入口清单。
