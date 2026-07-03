# OMEGA Formal192 Judgement And Deep Plan

## 目的

本文档完成两件事：

1. 判读用户提供的 `formal192` 正式基线结果
2. 在此基础上设计下一阶段深层优化方案

前提约束保持不变：

- 不修改 MATLAB 代码
- 准确性和可靠性优先于性能
- 不改数值语义
- 不改求解策略
- 不再优先尝试零散的 Python 接线层微优化

## formal192 结果

### 样本 1

用户本地执行命令：

```powershell
cd d:\Workspace\mat2py\Python
python debug_omega_profile.py --nt 64 --npix 192 --repeats 1 --pixel-repeats 1 --pixel-samples 8 --trial-count 5 --warmup 2 --exp-mode Exp2
```

结果摘要：

- `single_pixel_solver.avg_ms_per_pixel = 158.407`
- `single_pixel_solver.std_ms_per_pixel = 14.085`
- `single_pixel_solver.min_ms_per_pixel = 139.426`
- `single_pixel_solver.max_ms_per_pixel = 174.865`
- `mean_n_use = 64.0`

- `execute_omega_retrieval.avg_ms = 34215.058`
- `execute_omega_retrieval.std_ms = 3338.253`
- `execute_omega_retrieval.min_ms = 31441.565`
- `execute_omega_retrieval.max_ms = 40564.431`
- `shape = (64, 192)`
- `finite_ratio = 1.0`

### 样本 2

本地复测命令：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_omega_offline_baseline.ps1 -Profiles formal192 -PythonExe "d:\Workspace\mat2py\venv\Scripts\python.exe"
```

结果摘要：

- `single_pixel_solver.avg_ms_per_pixel = 132.615`
- `single_pixel_solver.std_ms_per_pixel = 10.280`
- `single_pixel_solver.min_ms_per_pixel = 124.181`
- `single_pixel_solver.max_ms_per_pixel = 152.179`
- `mean_n_use = 64.0`

- `execute_omega_retrieval.avg_ms = 35494.981`
- `execute_omega_retrieval.std_ms = 6401.447`
- `execute_omega_retrieval.min_ms = 25925.792`
- `execute_omega_retrieval.max_ms = 43004.883`
- `shape = (64, 192)`
- `finite_ratio = 1.0`

## 与 formal96 对照

### formal96 样本 1

- `execute_omega_retrieval.avg_ms = 13098.743`
- `execute_omega_retrieval.std_ms = 916.236`
- `single_pixel_solver.avg_ms_per_pixel = 145.925`

### formal96 样本 2

- `execute_omega_retrieval.avg_ms = 12168.557`
- `execute_omega_retrieval.std_ms = 170.702`
- `single_pixel_solver.avg_ms_per_pixel = 127.892`

### formal192 样本 1

- `execute_omega_retrieval.avg_ms = 34215.058`
- `execute_omega_retrieval.std_ms = 3338.253`
- `single_pixel_solver.avg_ms_per_pixel = 158.407`

### formal192 样本 2

- `execute_omega_retrieval.avg_ms = 35494.981`
- `execute_omega_retrieval.std_ms = 6401.447`
- `single_pixel_solver.avg_ms_per_pixel = 132.615`

## 判读结论

1. `formal192` 现在已有两轮样本，扩展压力口径比之前更可信
   - `shape = (64, 192)`
   - `finite_ratio = 1.0`
   - 两轮都没有看到数值失稳信号

2. `execute_omega_retrieval` 的放大趋势仍然合理，但方差比 `formal96` 明显更大
   - 从 `64x96` 的约 `12.2 ~ 13.1 s`
   - 放大到 `64x192` 的约 `34.2 ~ 35.5 s`
   - 两轮 trial 内部波动区间达到 `25.9 ~ 43.0 s`
   - 说明更大规模下外层调度、内存行为和求解波动都在被持续放大

3. `single_pixel_solver` 在 `formal192` 下同样表现出较强噪声
   - `formal96` 稳定样本约 `127.892 ms/pixel`
   - `formal192` 两轮样本均值分别为 `158.407` 和 `132.615 ms/pixel`
   - 这说明单像元链路确实会受大规模环境影响，但该指标本身波动也较大，因此只能作为辅助解释，不能单独用来做保留决策

4. 第二轮复测没有收敛方差，反而进一步证明 `formal192` 应作为扩展压力口径
   - 样本 1：`std_ms = 3338.253`
   - 样本 2：`std_ms = 6401.447`
   - 这意味着更大规模下，环境噪声、调度扰动或资源争用已经足以淹没小幅优化收益

5. 当前可以得到一个更清晰的正式基线分层
   - `64x96`：适合作为主要正式比较口径
   - `64x192`：适合作为扩展压力口径和回退否决口径

## 当前正式参考区间

在现有样本下，建议暂按以下方式理解：

### 主正式口径：`64x96`

- `execute_omega_retrieval`：约 `12.0 ~ 12.6 s`
- `single_pixel_solver`：约 `126 ~ 133 ms/pixel`

### 扩展压力口径：`64x192`

- 样本级均值：`execute_omega_retrieval` 约 `34.2 ~ 35.5 s`
- trial 区间：`execute_omega_retrieval` 约 `25.9 ~ 43.0 s`
- 样本级均值：`single_pixel_solver` 约 `132.6 ~ 158.4 ms/pixel`

说明：

- `64x192` 现在已有两轮样本，但方差仍明显偏大，仍不宜把它当作唯一的保留标准
- 如后续某次优化在 `64x96` 上看似有效，但 `64x192` 显著恶化，不建议保留
- 如某次优化只带来 `1% ~ 3%` 级别的收益，单靠 `formal192` 很难可靠判定，应优先依赖 `formal96 + cProfile`

## 下一阶段深层优化方案

下一阶段不再继续做零散的 Python 接线层微优化，而是转向三个高价值热点的深层实现路线。

### 路线 1：前向模型内核优化

目标：

- `_tb_forward_single_temp_with_context`
- `fresnel_reflectance_from_context`
- `mironov_dielectric_from_context`

原因：

- 这是最稳定、调用次数最高的热点链
- 一旦获得稳定收益，会在所有上层路径中被放大

策略：

1. 先做纯函数边界梳理
2. 评估是否可引入 Numba/JIT
3. 严格保持输入输出与数值口径不变
4. 用 `formal96` 和 `formal192` 双口径验证是否保留

### 路线 2：block residual 主循环深层实现

目标：

- `_resid_omega_block_single_temp_prepared`

原因：

- 它长期稳定排在第二热点
- 但 Python 层微调已经基本见顶

策略：

1. 停止逐元素包装层微调
2. 评估是否可将 residual 主循环与前向模型更紧地绑定
3. 如走 JIT 路线，优先处理单温路径，再考虑双温路径

### 路线 3：Jacobian 计算实现优化

目标：

- `_finite_difference_jacobian_from_base`

原因：

- 它在 `formal96` / `cprofile96` 中一直稳定排在前列
- 当前仍是显著的累计成本

策略：

1. 不改变差分语义
2. 优先考虑更低开销的实现，而不是更改数值公式
3. 新实现必须复用现有正式基线进行对照验证

## 建议执行顺序

建议按以下顺序推进，而不是同时大面积改动：

1. 为前向模型链做技术方案设计
   - 明确哪些函数可安全做 JIT / 内核化

2. 先在最小可控范围内做前向模型原型验证
   - 不直接大面积替换
   - 先比较函数级收益和数值一致性

3. 只有当前向模型链收益明确后，再进入 residual 或 Jacobian 路线

## 当前不建议做的事

1. 不建议再继续抠 `ddca cost_func`、`float(...)` 包装、闭包复用这类接线层微优化
2. 不建议在没有 `formal96 + cProfile` 对照的情况下保留任何新增性能改动
3. 不建议同时并行推进多个深层实现分支，容易混淆收益来源

## 最终建议

下一步最合理的动作不是直接修改 `omega.py`，而是：

1. 把 `formal192` 继续作为扩展压力口径，不再单独等待更多接线层复测
2. 进入“前向模型内核优化方案设计”

这会比继续做接线层微调更符合当前热点分布和正式基线结果。
