# OMEGA Residual Solver Deep Plan

## 目标

本方案用于指导 OMEGA 下一阶段的深层性能优化，范围限定在：

1. `block_residual_function`
2. `_resid_omega_block_single_temp_prepared`
3. `_resid_omega_block_dual_temp_prepared`
4. `solve_block_omega`

本阶段目标不是继续抠前向模型包装层，而是明确：

1. residual/solver 边界上哪些路径还值得投入
2. 哪些局部实现方式已经被证伪
3. 下一轮原型应如何进入，才能避免再次出现“局部看起来更轻，但正式层变慢”

## 当前判断

结合最近多轮 `formal96` / `dual96` / `cprofile96`，当前结论如下：

1. 前向模型内核化方向已经成立
   - 单温和双温的热点都已迁移到标量核
   - `with_context` 包装层已经退化成薄包装

2. 继续抠 residual/Jacobian 的局部微调性价比很低
   - 单温 residual 局部 helper：单测可过，但正式层显著退化
   - Jacobian 内部状态切换微调：分支语义可过，但正式层显著退化

3. 真正还值得设计的是“更高一层的边界”
   - 不是换一个更短的 loop
   - 而是重新定义 residual 与 solver 的交界方式

## 不可触碰边界

以下边界必须同时满足：

1. 不改 MATLAB 代码
2. 不改求解策略
3. 不改差分语义
4. 不改 residual 向量定义与顺序
5. 不改 block 平滑项语义
6. 不改变公开输入输出契约
7. 新实现必须可随时回退到当前稳定路径

## 已证伪路线

本阶段设计必须显式避开以下路线：

1. 在 `_resid_omega_block_single_temp_prepared()` 里单独拆局部 helper 替换 context 热路径
   - 现象：`formal96` 退化到约 `16.7 ~ 18.6 s`

2. 在 `_finite_difference_jacobian_from_base()` 内做单试探向量顺序评估
   - 现象：`formal96` 退化到约 `16.5 ~ 20.0 s`

3. 继续做去 `float(...)`、局部别名、临时数组更换等小包装优化
   - 现象：收益不稳定或已被证明无效

设计上的直接含义是：

- 不再优先尝试“函数内部更紧凑一点”的局部替换
- 只考虑能减少 solver/residual 交界重复工作的边界重构

## 当前热点边界

当前值得继续设计的热点边界可简化为：

```text
solve_block_omega
  -> objective(omega_value)
    -> residual_fun(omega_value)
      -> _resid_omega_block_*_prepared(...)
        -> _tb_forward_*_kernel(...)
```

关键观察：

1. `solve_block_omega()` 会反复调用 `residual_fun`
2. `residual_fun` 每次都会重新生成完整 residual 向量
3. `objective()` 只需要 `dot(residual, residual)`
4. 最终收尾时又会重新取一次 residual 和 scalar Jacobian

这说明当前边界上仍可能存在两个值得设计的方向：

- residual 计算结果的“结构化复用”
- solver 目标函数与 residual 函数的“接口分层”

## 推荐设计路线

### 路线 A：结构化 Residual Evaluator

核心想法：

- 不再让 solver 只拿到一个“匿名 residual 向量函数”
- 改为构造一个结构化 evaluator 对象，统一暴露：
  - `residual(omega)`
  - `cost(omega)`
  - `scalar_jacobian(omega)`

目标不是改变数学逻辑，而是把当前分散在：

- `block_residual_function`
- `objective`
- `solve_block_omega`

之间的重复准备逻辑，集中到一个稳定边界中。

建议接口草案：

```python
@dataclass(slots=True)
class OmegaBlockEvaluator:
    ...

    def residual(self, omega_value: float) -> np.ndarray:
        ...

    def cost(self, omega_value: float) -> float:
        ...

    def scalar_jacobian(self, omega_value: float) -> np.ndarray:
        ...
```

第一版要求：

- 内部仍然调用当前稳定 residual 实现
- 不直接内联整段 residual 主循环
- 先解决“接口分层”和“重复路径聚合”的问题

### 路线 B：Residual Metadata 固定化

当前 `block_residual_function()` 已经预绑定了：

- `tbv_block`
- `tbh_block`
- `tau_block`
- `sm_block`
- `ia_block`
- `h_values`
- `alpha_values`
- `smooth_weight`

但这仍然停留在闭包层。

建议进一步固定成显式数据对象，例如：

```python
@dataclass(slots=True)
class OmegaBlockResidualInputs:
    tbv: np.ndarray
    tbh: np.ndarray
    tau: np.ndarray
    sm_ref: np.ndarray
    angle_or_context: ...
    h_values: np.ndarray
    alpha_values: np.ndarray
    smooth_weight: float
    omega_prev: float
```

用途：

- 让 residual/solver 边界从“闭包推理”变成“显式对象”
- 方便后续在不改语义的前提下做更高层缓存
- 方便单测直接构造最小 block 输入

注意：

- 这不是为了重写 residual 数学公式
- 只是为了把后续可能的深层优化入口固化成可测试边界

### 路线 C：Cost-First 只读接口

当前 `objective()` 的成本来自：

1. 先构造 residual 向量
2. 再 `np.dot(residual, residual)`

如果只是在 `minimize_scalar` 迭代阶段求 cost，那么一个值得设计的方向是：

- 显式引入 `cost_only` 路径
- 但仍然通过同一套 residual 公式逐项累加，不改变数值定义

建议接口草案：

```python
def residual_cost_only(self, omega_value: float) -> float:
    ...
```

这个路线的价值在于：

- 有机会减少部分中间向量对象的生命周期
- 但第一版不建议直接替换当前 `objective()`

原因：

- 只要没有正式证据，不应冒险改变 solver 的主要调用面
- 更安全的顺序是先把接口准备好，再做 A/B 原型

## 下一轮原型建议

结合已证伪路线，下一轮更合理的原型不是再改 loop，而是：

### 原型 1：Evaluator 边界成型，但内部仍调用稳定 residual

步骤：

1. 新增 `OmegaBlockEvaluator` 或等价显式对象
2. 将 `block_residual_function()` 重构为构造 evaluator
3. `solve_block_omega()` 改为调用：
   - `evaluator.cost()`
   - `evaluator.residual()`
   - `evaluator.scalar_jacobian()`

第一版不做的事：

- 不改 residual 内部公式
- 不改 `minimize_scalar` 调用方式
- 不做 cost-only 快路径

目标：

- 先验证“边界集中”本身不会带来正式层退化
- 为后续更深层原型准备稳定的测试与 profiling 入口

### 原型 2：只为 `objective()` 试做 cost-only 实现

前提：

- 原型 1 已通过正式层验证

步骤：

1. 在 evaluator 内部增加 `cost_only()`
2. 保留 `residual()` 原路径
3. 只让 `objective()` 走 `cost_only()`，其余路径保持不变

验证重点：

- `formal96` 是否稳定优于当前主基线
- `cprofile96` 中 `_resid_omega_block_single_temp_prepared` 占比是否下降
- `formal192` 是否不恶化

### 原型 3：再评估 residual 与前向核的更深层耦合

前提：

- 原型 1 和原型 2 都验证通过

只有到这一步，才值得讨论：

- 是否让 residual 主循环直接消费前向标量核
- 是否让 single/dual residual 共享更深层实现骨架

## 建议测试层级

### 第 1 层：Evaluator 结构测试

确保：

- evaluator 与原闭包在相同输入下给出相同 residual
- `cost()` 与 `np.dot(residual, residual)` 一致
- `scalar_jacobian()` 与现有 `_finite_difference_scalar_jacobian()` 一致

### 第 2 层：单 block 对照

对单个 block：

- 比较旧路径与新 evaluator 路径的 block 结果
- 比较 `omega_hat`
- 比较 `final_cost`
- 比较 `firstorderopt`

### 第 3 层：正式基线

最少跑：

1. `formal96`
2. `cprofile96`

如 `formal96` 有收益，再补：

3. `formal192`
4. `dual96`

## 保留标准

只有同时满足以下条件才建议保留：

1. `formal96` 稳定优于当前主正式区间
2. `formal192` 不恶化
3. `cProfile` 变化与总时间变化对得上
4. 没有新增数值异常信号

## 回退条件

出现任一情况即回退：

1. `formal96` 明显退化
2. `formal96` 方差显著放大
3. `cProfile` 看起来变好，但正式层不支持
4. 新边界让单测/最小 block 对照难以解释

## 当前建议

当前最合理的下一步不是继续写新的 residual loop helper，而是：

1. 先把 `block_residual_function -> solve_block_omega` 这层改造成显式 evaluator 边界
2. 第一版只做边界集中，不做 cost-only 快路径
3. 通过后再决定是否进入更深的 residual/solver 原型

这比继续尝试局部循环微调更符合当前已经得到的正式验证结果。
