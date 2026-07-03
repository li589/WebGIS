# OMEGA Forward Kernel Boundary Design

## 状态

- 文档角色：前向模型边界拆分设计稿
- 当前状态：本文中的核心边界已经落地到代码，尤其是 `Mironov`、`Fresnel`、单温 TB、双温 TB 的标量核与 context 薄包装
- 注意：本文仍有少量“第一阶段只做边界设计”的措辞，现应理解为设计阶段背景，而非当前代码状态

## 目标

本设计文档将“前向模型内核优化方案”推进到可实施边界，重点回答三件事：

1. 哪些热点函数先拆
2. 拆成什么样的纯标量签名
3. 如何在不改数值语义的前提下接回当前实现

约束保持不变：

- 不改 MATLAB 代码
- 不改求解策略
- 不改差分语义
- 不改公开输入输出契约
- 第一阶段只做边界设计，不直接替换主路径

## 当前热点链

单温路径上的稳定热点链如下：

1. `omega.py::_tb_forward_single_temp_with_context`
2. `physics.py::mironov_dielectric_from_context`
3. `physics.py::fresnel_reflectance_from_context`

当前调用关系可简化理解为：

```text
_tb_forward_single_temp_with_context
  -> mironov_dielectric_from_context
  -> fresnel_reflectance_from_context
  -> rough reflectance + canopy radiative transfer
```

这条链的共同特点是：

- 调用频率高
- 输入基本都是标量
- 现有 dataclass/context 适合 Python 包装，但不适合直接送进 JIT

## 设计原则

### 原则 1：把 context 边界留在 Python 层

`MironovContext`、`FresnelContext`、`OmegaTbForwardContext` 继续保留，用于：

- 预计算常量
- 维持当前代码可读性
- 作为稳定回退路径

内核层只接收纯标量，不直接接收：

- `dict`
- `dataclass`
- 闭包对象
- Python `complex` 作为第一阶段边界

### 原则 2：先拆小核，再拼大核

拆分顺序固定为：

1. Mironov 内核
2. Fresnel 内核
3. 单温 TB 前向模型内核

原因是前两者更小、更纯，也更容易先验证数值一致性。

### 原则 3：先保留纯 Python 等价版，再考虑 Numba

第一版先新增纯标量 helper，确保：

- 签名稳定
- 测试容易补
- 可以直接做 Python A/B 对照

只有纯 Python 标量版稳定后，才进入 `numba.njit` 原型。

补充现状：

- `physics.py` 已落地 `Numba` 可回退装载逻辑
- `omega.py` 已落地单温与双温前向标量核
- 当前仍未保留的是 residual/solver/Jacobian 的后续深层原型

## 建议内核签名

### 1. Mironov 标量内核

建议新增：

```python
def _mironov_dielectric_kernel(
    soil_moisture: float,
    zxmvt: float,
    znd: float,
    zkd: float,
    znb: float,
    zkb: float,
    znu: float,
    zku: float,
) -> tuple[float, float]:
    ...
```

输出不直接返回 `complex`，而是：

- `epsilon_real`
- `epsilon_imag`

这样做的好处：

- 降低 JIT 边界复杂度
- 避免下游第一阶段继续依赖 Python `complex`
- 便于 Fresnel 内核直接消费标量实部/虚部

对应包装层：

```python
def mironov_dielectric_from_context(soil_moisture: float, context: MironovContext) -> complex:
    epsilon_real, epsilon_imag = _mironov_dielectric_kernel(
        soil_moisture,
        context.zxmvt,
        context.znd,
        context.zkd,
        context.znb,
        context.zkb,
        context.znu,
        context.zku,
    )
    return complex(epsilon_real, epsilon_imag)
```

### 2. Fresnel 标量内核

建议新增：

```python
def _fresnel_reflectance_kernel(
    epsilon_real: float,
    epsilon_imag: float,
    cos_theta: float,
    sin_theta_sq: float,
) -> tuple[float, float]:
    ...
```

输出：

- `rh`
- `rv`

注意点：

- 第一阶段允许内核内部继续使用复数中间量
- 但边界上不再把 `complex` 作为 API 契约
- 如果后续 Numba 对复数支持不稳定，再进一步拆成实部/虚部运算版本

对应包装层：

```python
def fresnel_reflectance_from_context(epsilon: complex, context: FresnelContext) -> tuple[float, float]:
    return _fresnel_reflectance_kernel(
        float(epsilon.real),
        float(epsilon.imag),
        context.cos_theta,
        context.sin_theta_sq,
    )
```

### 3. 单温 TB 前向模型内核

建议新增：

```python
def _tb_forward_single_temp_kernel(
    soil_moisture: float,
    tau_value: float,
    h_value: float,
    alpha_value: float,
    omega_value: float,
    ts_value: float,
    scale: float,
    zxmvt: float,
    znd: float,
    zkd: float,
    znb: float,
    zkb: float,
    znu: float,
    zku: float,
    cos_theta: float,
    sin_theta_sq: float,
    cos_theta_sq: float,
) -> tuple[float, float]:
    ...
```

内核职责限定为：

1. 计算 Mironov 介电常数
2. 计算 Fresnel 反射率
3. 计算 rough reflectance
4. 计算单温 TB 输出

不在这个内核里做的事：

- context 构建
- numpy 数组准备
- block payload 读取
- 参数裁剪策略调整

对应包装层：

```python
def _tb_forward_single_temp_with_context(..., model_context: OmegaTbForwardContext) -> tuple[float, float]:
    dielectric = model_context.dielectric
    fresnel = model_context.fresnel
    return _tb_forward_single_temp_kernel(
        soil_moisture,
        tau_value,
        h_value,
        alpha_value,
        omega_value,
        ts_value,
        scale,
        dielectric.zxmvt,
        dielectric.znd,
        dielectric.zkd,
        dielectric.znb,
        dielectric.zkb,
        dielectric.znu,
        dielectric.zku,
        fresnel.cos_theta,
        fresnel.sin_theta_sq,
        fresnel.cos_theta_sq,
    )
```

## 文件布局建议

第一阶段建议不新建太多模块，优先保证回退简单：

### 方案 A

直接在 `Python/algorithms/physics.py` 中新增：

- `_mironov_dielectric_kernel`
- `_fresnel_reflectance_kernel`

并在 `Python/algorithms/omega.py` 中新增：

- `_tb_forward_single_temp_kernel`

优点：

- 改动范围最小
- 与现有热点函数位置一致
- 回退简单

### 方案 B

若后续 Numba 原型逐渐增多，再新建单独模块，例如：

- `Python/algorithms/_omega_forward_kernels.py`

当前阶段不建议一开始就拆模块，避免把“边界设计”变成“结构重构”。

## 原型验证计划

### 第 1 层：标量函数对照

对 Mironov 和 Fresnel 各做随机样本对照：

- 输入覆盖典型物理区间
- 新旧实现逐样本比较
- 误差目标保持在机器精度量级

建议覆盖：

- `soil_moisture`
- `theta_deg`
- `clay_fraction`
- `tau`
- `h`
- `alpha`
- `omega`
- `ts`

### 第 2 层：前向模型函数对照

直接比较：

- 旧版 `_tb_forward_single_temp_with_context`
- 新版 `_tb_forward_single_temp_kernel + 包装层`

比较指标：

- `tbv_m`
- `tbh_m`
- 绝对误差
- 相对误差

### 第 3 层：局部 residual 对照

只抽单个 block 或单个像元，不直接跑整图。

目标：

- 确认内核替换后 residual 向量不变
- 把问题限制在最小范围内，便于定位

### 第 4 层：正式基线

通过前 3 层后，再跑：

1. `formal96`
2. `cprofile96`
3. 必要时 `formal192`

保留标准：

- `formal96` 明显变好
- `formal192` 不显著恶化
- `cProfile` 中前向模型链热点占比下降

## 实施顺序

建议严格按下面顺序推进：

1. 新增 Mironov 标量内核
2. 新增 Fresnel 标量内核
3. 用现有包装函数接回旧 API
4. 做标量一致性对照
5. 新增单温 TB 标量内核
6. 做函数级一致性对照
7. 再评估是否进入 Numba 原型

## 当前结论

当前最合理的下一步不是继续改 residual 主循环，而是先把前向模型链的“纯标量边界”落稳。

一旦这层边界稳定：

- Numba/JIT 才有清晰入口
- residual 集成才更容易判断收益来源
- 回退路径也会保持简单

## 落地状态

截至当前代码，以下项目已完成：

1. `Mironov` 标量核
2. `Fresnel` 标量核
3. 单温 TB 标量核
4. 双温 TB 标量核
5. `with_context` 包装层薄化

以下项目已尝试但当前未保留：

1. single residual 局部 helper 原型
2. Jacobian 内部状态切换微调
3. 显式 evaluator 边界原型
