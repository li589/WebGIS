# Unified Data Access Design

## 1. 文档定位

本文档描述当前 Python 计算包中统一数据接入体系的设计，用于说明如何把本地文件、缓存数据、远程对象、HTTP 资源和不同格式的输入统一纳入同一套访问与物化流程。

本文档关注：

1. 数据如何被发现。
2. 数据如何被解析。
3. 数据如何被物化。
4. 数据如何被缓存。
5. 数据如何被格式适配。

## 2. 设计目标

统一数据接入体系的目标是：

- 让模块不再直接依赖具体文件路径
- 让不同来源的数据采用同一套访问语义
- 让缓存、远程对象、本地文件、HTTP 资源都可统一处理
- 让上层 workflow 能基于统一输入构造执行链

## 3. 当前状态

当前代码库已经拥有以下相关能力：

- `data_access/` 目录
- `data_access/sources/`
- `data_access/format_adapters/`
- `data_access/resolver.py`
- `data_access/materializer.py`
- `data_access/cache_store.py`
- `data_access/prepared_input.py`
- `data_access/fetcher.py`
- `data_access/registry.py`
- `data_access/contracts.py`
- `data_access/consumers.py`

这说明统一数据接入已经不是纯设计，而是正在落地的基础设施层。

## 4. 核心原则

### 4.1 统一入口

所有数据源都应先进入统一 data access 层，再交给 `ingest` 和 `modules`。

### 4.2 先解析，再物化

系统应先知道“这是哪个数据”，再决定是否下载、复制或转换。

### 4.3 适配与读取分离

不同文件格式、不同对象存储和不同编码方式应通过 format adapters 分离处理。

### 4.4 缓存是底层能力，不是业务分支

缓存命中时不应改变上层模块语义，只是减少物化成本。

## 5. 当前分层

```text
sources/          数据源发现与基础访问
format_adapters/  各格式文件适配器
resolver.py       解析与路由
materializer.py   物化与落盘
fetcher.py        拉取与获取逻辑
cache_store.py    缓存层
prepared_input.py  预处理输入对象
registry.py       数据源与适配器注册
consumers.py      数据消费侧辅助逻辑
```

## 6. 统一数据流

当前推荐的数据流顺序为：

1. 调用方提供输入描述
2. data access 解析输入
3. resolver 选择数据源与适配器
4. fetcher / materializer 完成可消费数据准备
5. prepared_input 挂回执行上下文
6. 上层 workflow / module 使用统一输入

## 7. 适配器类别

### 7.1 Source Adapter

负责从本地、远程、缓存或对象存储获取原始内容。

### 7.2 Format Adapter

负责把不同格式统一转成上层可消费结构。

### 7.3 Cache Adapter

负责记录缓存键、命中状态与可复用结果。

## 8. 数据接入边界

统一数据接入层应承担以下责任：

- 数据发现
- 数据解析
- 数据拉取
- 数据物化
- 格式转换
- 缓存控制

不应承担：

- 科学计算逻辑
- 前端展示逻辑
- 平台任务治理逻辑

## 9. 与其他层的关系

### 9.1 与 `contracts`

数据接入层应尽量依赖统一契约对象，而不是散乱字段。

### 9.2 与 `workflow`

workflow 通过数据接入层获得统一输入，而不是自己直接处理底层文件类型。

### 9.3 与 `modules`

modules 不应该感知数据来源细节，只需要消费准备好的输入。

## 10. 当前演进方向

未来统一数据接入可以继续朝以下方向演进：

1. 增加更多标准化数据源
2. 提高远程对象与对象存储的统一处理能力
3. 强化缓存索引与缓存失效策略
4. 提高格式适配器的可插拔性
5. 减少模块内部对原始路径的直接依赖

## 11. 与迁移计划的关系

统一数据接入不是单独孤立的模块，而是 Python 计算包工程化的重要基础。随着它的完善，模块才能更容易从历史脚本迁移到稳定的输入输出体系上。

## 12. 结论

统一数据接入层的目标不是简单包装读文件，而是把所有数据来源都转成统一的、可缓存的、可物化的、可调度的输入对象。它是 workflow 和 modules 能否稳定演进的关键底座。
