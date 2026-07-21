# Python Processing Package

`Code/algorithms/providers/Python/` 是本项目算法计算包的统一落点。这里承载从 MATLAB 迁移而来的核心科学计算、数据接入、工作流组织、产品输出与服务桥接能力。当前它已经不是单纯的脚本集合，而是一套面向平台调用的工程化 Python 包。

## 当前定位

这个包的目标是让算法能力以统一方式被平台调度，而不是散落在不同脚本或临时入口中。当前设计重点包括：

- 统一任务入口
- 统一数据源接口
- 统一日志接口
- 统一产品输出接口
- 统一工作流与模块化执行方式
- 兼容 MATLAB 迁移阶段的历史流程

## 当前工程结构

```text
Python/
├─ contracts/        # 任务、数据、产品、事件与校验契约
├─ interfaces/       # 调度器、数据源、日志、产品输出等适配接口
├─ runner/           # 统一入口、运行时上下文与分发逻辑
├─ workflow/         # 工作流定义、执行、序列化与校验
├─ service/          # HTTP、队列、平台适配与服务封装
├─ data_access/      # 数据源发现、解析、物化与格式适配
├─ modules/          # 原生算法模块
├─ ingest/           # 原始数据读取与装配
├─ algorithms/       # 科学计算核心
├─ pipelines/        # 兼容层与历史流水线入口
├─ publish/          # 产品写出与 manifest 构建
├─ storage/          # 缓存、中间文件与路径组织
├─ utils/            # 辅助工具
├─ tests/            # 测试
├─ pyproject.toml
├─ requirements.txt
└─ README.md
```

## 核心设计思路

### 1. 统一入口

当前算法包强调通过 `run_job()` 或等价服务入口进入执行，而不是直接调用散落的脚本。

### 2. 工作流优先

当前包已经从“pipeline 主导”逐步收敛到“`modules + workflow` 主导，`pipelines` 仅作兼容层”的结构。

### 3. 数据与计算分离

- `data_access` 负责数据发现、解析、物化与格式适配
- `ingest` 负责原始数据读取与装配
- `algorithms` 负责数值计算核心
- `publish` 负责产品输出与清单构建

### 4. 服务化接入

`service/` 中已经包含 HTTP 服务、平台适配器、队列、worker 和结果封装等能力，用于把本地计算包接入更大的平台系统。

## 当前关键能力

- 原生模块：SMAP / NDVI / FY / station / inversion / omega / bundles 等
- **数据链路模块**（2026-07-21）：`remote_fetch`、`http_open_data`、`archive_extract`、`config_read`、`variable_extract`、`format_convert`，以及画布参数节点 `data_source` / `output_map_layer` 等（见 `modules/data_access_nodes.py`、`modules/graph_io.py`）
- `data_access`：本地 / HTTP / remote(SMB/SFTP) / MinIO / CacheStore（支持 `BACKEND_STATIC_CACHE_TTL_SECONDS`）
- 平台侧 LiteGraph 画布经后端编译后以 `workflow_definition` 进入本包 `WorkflowRunner`
- 支持 Job / Workflow / Module 的统一调度思路
- 支持本地执行与平台化执行两种接入方式
- 支持数据接入、格式适配、结果落盘与 manifest 输出
- 支持原生模块与兼容 pipeline 并存
- 支持平台队列、worker、HTTP 服务和 mock 测试路径

更多：`Code/docs/课题组数据全链路-2026-07-21.md`、`docs/unified_data_access_design.md`、`docs/workflow_extension_design.md`。

## 典型执行链路

当前概念上的标准链路可以理解为：

1. 平台传入任务请求
2. `runner` 创建运行时上下文
3. `data_access` 与 `ingest` 准备数据
4. `algorithms` 执行科学计算
5. `publish` 生成产品与 manifest
6. `service` 或平台适配层回传结果

## 当前包的角色边界

这个包负责的是“算法执行与产品生成”，不负责前端展示，也不负责平台级任务治理。它应尽量保持：

- 输入明确
- 输出明确
- 运行流程明确
- 与调用方解耦

## 推荐阅读顺序

如果你在接手 Python 算法包，建议按以下顺序阅读：

1. `Code/algorithms/providers/Python/README.md`
2. `Code/algorithms/providers/docs/detailed_design.md`
3. `Code/algorithms/providers/docs/backend_integration_contract.md`
4. `Code/algorithms/providers/docs/workflow_extension_design.md`
5. `Code/algorithms/providers/docs/unified_data_access_design.md`

## 说明

- 当前包已经进入工程化阶段，不再是单纯的科研脚本目录
- `pipelines` 仍保留兼容意义，但主方向是统一模块与工作流
- 文档与代码应持续对齐，尤其是入口命名、数据契约和输出结构