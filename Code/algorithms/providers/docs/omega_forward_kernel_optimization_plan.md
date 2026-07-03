# OMEGA Forward Kernel Optimization Plan

## 状态

- 文档角色：前向模型内核化阶段的设计归档
- 当前状态：本文件中的 Mironov / Fresnel / 单温前向核路线已经完成第一轮实现；双温前向核也已接入主代码
- 阅读建议：当前实现状态请优先结合 `omega_forward_kernel_boundary_design.md`、`omega_forward_kernel_validation_20260703_051204.md`、`omega_dual_forward_kernel_validation_20260703_051930.md` 阅读

## 目标

本方案用于指导 OMEGA 下一阶段的深层性能优化，范围限定在“前向模型内核”相关路径，不直接修改求解策略，也不改变数值语义。

优化目标：

1. 降低 `_tb_forward_single_temp_with_context` 的累计耗时
2. 同步压低 `fresnel_reflectance_from_context` 与 `mironov_dielectric_from_context` 的累计成本
3. 在正式基线 `formal96` / `formal192` 下验证收益是否稳定

## 当前判断

以下判断代表设计当时的起点，不再完全等同于当前代码状态。

根据 `formal96` 与 `formal192` 的已有结果，前向模型链仍然是最稳定的头号热点：

- `Python/algorithms/omega.py::_tb_forward_single_temp_with_context`
- `Python/algorithms/physics.py::fresnel_reflectance_from_context`
- `Python/algorithms/physics.py::mironov_dielectric_from_context`

说明：

- 继续抠 Python 接线层微优化的性价比已明显下降
- 真正还值得投入的，是这条链的更深层实现方式

## 约束

以下约束必须同时满足：

1. 不改 MATLAB 代码
2. 不改求解器策略
3. 不改差分语义
4. 不改前向模型数学口径
5. 不改变公开输入输出契约
6. 新实现必须可以随时回退到当前稳定路径

## 候选实现路线

### 路线 A：纯函数内核化

目标：

- 将前向模型链拆成更适合 JIT 的纯数值函数

候选函数：

1. 介电常数内核
   - 从 `mironov_dielectric_from_context` 提炼纯标量版本

2. 菲涅耳反射率内核
   - 从 `fresnel_reflectance_from_context` 提炼纯标量版本

3. 单温前向模型内核
   - 从 `_tb_forward_single_temp_with_context` 提炼纯标量版本

建议：

- 新增独立内核函数，不直接替换现有函数第一版实现
- 保留当前 Python 实现作为参考路径和回退路径

### 路线 B：Numba/JIT 原型

前提：

- 项目依赖中已包含 `numba`

适用场景：

- 标量数值路径
- 循环次数极多
- 输入类型和返回类型可稳定约束

不建议第一步直接做的事情：

- 不要一开始就尝试对整个 `omega.py` 大块函数 JIT
- 不要把 `dict`、`dataclass`、闭包对象直接送进 JIT

更安全的方式：

1. 先新增纯标量 helper
2. 再给 helper 做 Numba 原型
3. 通过一个很薄的 Python 包装层与现有上下文对象对接

## 推荐拆分边界

### 1. Mironov 内核

当前输入：

- `soil_moisture`
- `MironovContext`

建议拆分：

- Python 层负责从 `MironovContext` 取出标量
- 内核只接收纯标量：
  - `soil_moisture`
  - `zxmvt`
  - `znd`
  - `zkd`
  - `znb`
  - `zkb`
  - `znu`
  - `zku`

建议输出：

- `epsilon_real`
- `epsilon_imag`

原因：

- 避免在 JIT 路径中传递 Python `complex` 或 dataclass 对象作为第一步
- 有利于后续把 Fresnel 内核也改成接收实部/虚部标量

### 2. Fresnel 内核

当前输入：

- `epsilon: complex`
- `FresnelContext`

建议拆分：

- Python 层拆成纯标量：
  - `epsilon_real`
  - `epsilon_imag`
  - `cos_theta`
  - `sin_theta_sq`

建议输出：

- `rh`
- `rv`

原因：

- 先把复杂对象边界剥掉
- 后续更容易做 Numba 或更紧凑的纯数值实现

### 3. 单温前向模型内核

建议输入：

- `soil_moisture`
- `tau_value`
- `h_value`
- `alpha_value`
- `omega_value`
- `ts_value`
- `scale`
- Mironov 标量上下文
- Fresnel 标量上下文

建议输出：

- `tbv_m`
- `tbh_m`

原因：

- 这是最终最值得直接加速的函数级入口
- 只要保持输入输出完全一致，就可以安全做 A/B 比较

## 实施顺序

### 第 1 步：只做内核边界设计

产物：

- 内核函数签名草案
- Python 包装层对接方案
- 数值一致性验证点清单

目标：

- 不改现有执行路径
- 只把“怎么安全替换”设计清楚

### 第 2 步：先做 Mironov + Fresnel 原型

原因：

- 这两个函数更小、更纯
- 比直接动 `_tb_forward_single_temp_with_context` 风险低

验证：

- 标量级随机输入对比
- 结果误差阈值接近机器精度

### 第 3 步：再做单温前向模型原型

条件：

- 前两步原型验证通过

验证：

- 函数级对照
- `formal96` 快速复测
- 如有必要补 `formal192`

### 第 4 步：若收益成立，再考虑 residual 集成

说明：

- 只有当前向模型内核收益明确后，才值得进入 `_resid_omega_block_single_temp_prepared` 的更深层替换

## 验证标准

### 数值一致性

至少包含三层：

1. 标量随机样本对照
2. 单 block 对照
3. `formal96` / `formal192` 结果对照

### 性能判断

必须同时满足：

1. `formal96` 明显变好
2. `formal192` 不恶化
3. `cProfile` 热点变化与总时间变化对得上

### 回退条件

出现任一情况即回退：

1. 数值差异超出预期
2. `formal96` 收益不稳定
3. `formal192` 显著恶化
4. 热点变化与总时间变化不一致

## 本轮不做的事

1. 不直接修改 `_resid_omega_block_single_temp_prepared`
2. 不直接改 Jacobian 语义
3. 不直接把整个 `omega.py` JIT 化
4. 不在没有 `formal192` 复测的情况下做保留决策

## 后续状态

后续已完成事项：

1. `formal192` 复测与判读已补齐
2. `Mironov + Fresnel` 标量核已实现，并接入 `Numba` 可回退装载逻辑
3. 单温与双温前向标量核均已接入主代码路径
4. residual/solver/Jacobian 的后续深层原型已做过若干轮试验，但当前均未保留

当前更准确的下一步不是继续前向包装层重构，而是：

1. 以当前前向核实现为稳定基线
2. 将 residual/solver 深层方案保留在设计稿层面
3. 在接入 WebGIS 后端作业调度器前，优先补齐接口、输入契约和运行稳定性文档
