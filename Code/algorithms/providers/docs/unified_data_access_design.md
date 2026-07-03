# 统一数据访问与格式适配设计

## 1. 文档目标

本文档用于规划 `Python/` 目录后续的统一数据访问底座，使模块与工作流能够以一致方式消费以下来源的数据：

1. 缓冲数据
2. 在线数据
3. MinIO / S3 对象
4. 本地直接对象
5. 内存对象

同时覆盖以下常见格式：

1. `nc`
2. `csv`
3. `hdf/h5`
4. `tif`
5. `shp`
6. `excel`
7. `txt`
8. `json`
9. `xml`
10. `mat`

设计目标不是重写调度器，而是为现有的模块化工作流体系提供统一的数据获取、缓存、物化、格式识别与转换能力。

## 2. 背景与问题

当前仓库已经具备数据源协议雏形：

1. `DataSourceAdapter` 定义在 [datasource.py](file:///d:/Workspace/mat2py/Python/interfaces/datasource.py)
2. `DataRequest` 与 `DataBundle` 定义在 [data.py](file:///d:/Workspace/mat2py/Python/contracts/data.py)
3. `run_job()` 会统一调用 `discover -> resolve -> acquire -> materialize`，实现见 [dispatch.py](file:///d:/Workspace/mat2py/Python/runner/dispatch.py)

但现状仍有明显限制：

1. 很多模块仍直接从 `datasource_selection` 中读取本地路径或目录
2. `DataBundle` 只表达了 `local_paths / remote_refs`，不足以描述对象存储、缓存命中、格式转换过程
3. 不同格式的读取逻辑分散在模块与 `ingest/` 中，缺少统一注册表
4. 缓存、远端下载、格式转换、物化目录管理尚未下沉为独立基础设施
5. 模块层尚未形成“声明输入能力，底层自动适配来源与格式”的模式

因此，后续必须把“数据源统一描述”和“格式适配统一入口”一起建设，而不是仅扩展现有路径透传能力。

## 3. 设计原则

1. 模块不直接关心数据来自本地、缓存、HTTP 还是 MinIO
2. 模块优先消费标准化输入对象，而不是原始路径字符串
3. 数据访问必须区分“发现、解析、下载、缓存、物化、格式转换”六个阶段
4. 原有 `run_job()` 主链尽量保持兼容，逐步替换而非一次性重写
5. 新设计必须兼容当前 `FastAPI + Celery + Redis + MinIO` 的服务形态
6. 迁移过程必须允许旧模块继续工作，新模块优先接入新底座

## 4. 目标能力

### 4.1 数据来源

统一支持以下来源类型：

1. `cache`
2. `online`
3. `object_storage`
4. `local_file`
5. `local_dir`
6. `memory`

### 4.2 数据格式

统一识别并逐步支持：

1. `mat`
2. `nc`
3. `hdf`
4. `h5`
5. `tif`
6. `shp`
7. `csv`
8. `excel`
9. `txt`
10. `json`
11. `xml`

### 4.3 访问模式

统一支持以下访问模式：

1. `lazy`
2. `partial`
3. `full`
4. `stream`

### 4.4 物化模式

统一支持以下物化模式：

1. `auto`
2. `memory`
3. `local_file`
4. `local_dir`

## 5. 核心对象设计

### 5.1 `ResourceRef`

`ResourceRef` 用于统一描述任何可被模块消费或被底层访问的资源对象。

建议字段：

1. `uri`
2. `source_kind`
3. `logical_type`
4. `format`
5. `media_type`
6. `storage_backend`
7. `bucket`
8. `object_key`
9. `local_path`
10. `version`
11. `checksum`
12. `size_bytes`
13. `metadata`

其中：

1. `uri` 保留原始地址
2. `source_kind` 描述来源类型，如 `cache`、`online`、`object_storage`
3. `logical_type` 用于表达标准逻辑输入类型，而不是底层文件扩展名

### 5.2 `DataRequestV2`

建议在现有 `DataRequest` 基础上扩展：

1. `dataset_name`
2. `variables`
3. `selector`
4. `accepted_formats`
5. `preferred_format`
6. `materialization_mode`
7. `access_mode`
8. `allow_cache`
9. `allow_streaming`
10. `converter_hints`

其中 `selector` 用于承载时间、区域、深度、文件模式、业务标签等筛选信息。

### 5.3 `PreparedInput`

模块最终消费的标准输入对象建议为 `PreparedInput`，而不是裸路径字典。

建议字段：

1. `request`
2. `resources`
3. `materialized_resources`
4. `warnings`
5. `conversion_trace`
6. `cache_hits`

其职责是统一表达：

1. 原始命中的候选资源
2. 最终被下载或物化后的本地资源
3. 中间发生过的格式转换
4. 是否命中缓存

## 6. 逻辑类型分层

建议把底层格式统一映射到以下逻辑类型：

1. `array`
2. `raster`
3. `vector`
4. `table`
5. `document`
6. `blob`

映射建议如下：

1. `mat / nc / hdf / h5` -> `array`
2. `tif` -> `raster`
3. `shp` -> `vector`
4. `csv / excel / txt` -> `table`
5. `json / xml` -> `document`
6. 其他二进制对象 -> `blob`

## 7. 底层组件拆分

建议不要把所有职责继续堆在 `DataSourceAdapter` 里，而是拆成以下内部组件：

1. `Locator`
2. `Resolver`
3. `Fetcher`
4. `CacheStore`
5. `Materializer`
6. `FormatAdapter`

职责如下：

1. `Locator`：发现候选资源，支持本地目录、MinIO、HTTP、缓存索引
2. `Resolver`：根据 `DataRequestV2` 选择最终资源集合
3. `Fetcher`：执行远端下载、对象复制或在线拉取
4. `CacheStore`：处理索引缓存、文件缓存、转换缓存与过期策略
5. `Materializer`：将远端对象落地为本地文件或目录
6. `FormatAdapter`：执行格式识别、加载、标准化与导出

## 8. 目录建议

建议新增数据访问底座目录：

1. `Python/data_access/contracts.py`
2. `Python/data_access/registry.py`
3. `Python/data_access/locator.py`
4. `Python/data_access/resolver.py`
5. `Python/data_access/fetcher.py`
6. `Python/data_access/cache_store.py`
7. `Python/data_access/materializer.py`
8. `Python/data_access/prepared_input.py`
9. `Python/data_access/format_adapters/`
10. `Python/data_access/sources/local_fs.py`
11. `Python/data_access/sources/minio.py`
12. `Python/data_access/sources/http.py`
13. `Python/data_access/sources/cache.py`

## 9. 格式适配策略

### 9.1 格式适配器统一接口

每种格式适配器建议至少提供：

1. `probe(resource)`
2. `load(resource)`
3. `materialize(resource, target_dir)`
4. `export(value, target_format)`

### 9.2 推荐首批支持格式

第一阶段优先支持：

1. `mat`
2. `nc/hdf/h5`
3. `tif`
4. `csv`
5. `json`

第二阶段补充：

1. `txt`
2. `excel`
3. `xml`
4. `shp`

### 9.3 当前库与建议库

建议复用或引入如下库：

1. `h5py`
2. `scipy.io`
3. `rasterio`
4. `pandas`
5. `xarray` / `netCDF4`
6. `geopandas` / `fiona`
7. `openpyxl`
8. `xml.etree.ElementTree`

## 10. 缓存设计

缓存分两层：

1. 元数据缓存
2. 物化缓存

元数据缓存建议存储：

1. `dataset_name`
2. `selector`
3. `source_uri`
4. `format`
5. `version`
6. `checksum`
7. `etag`

物化缓存建议存储：

1. 原始副本路径
2. 转换后副本路径
3. 生成时间
4. 过期时间
5. 生成参数摘要

## 11. 与现有代码的集成方式

### 11.1 短期兼容方案

短期内保留现有 `DataSourceAdapter` 外形：

1. `discover`
2. `resolve`
3. `acquire`
4. `materialize`

但其内部实现改为调用新的 `data_access` 底座。

### 11.2 `dispatch.py` 的改造点

`dispatch.py` 需要从“向 `datasource_selection` 注入裸 bundle 信息”改为：

1. 统一构建 `PreparedInput`
2. 把标准输入对象注入运行时上下文
3. 保留 `_prepared_bundles` 作为兼容字段

### 11.3 模块层迁移策略

模块迁移遵循以下顺序：

1. 新模块优先消费 `PreparedInput`
2. 旧模块可继续读取 `datasource_selection`
3. 试点模块迁移完成后，再逐步把路径直连逻辑收缩为兼容层

## 12. 非目标

本设计当前不包含以下内容：

1. 重写现有 WebGIS 调度器
2. 一次性替换所有旧模块
3. 在第一阶段实现全格式全来源的完全功能覆盖
4. 在第一阶段实现复杂异步分块下载调度

## 13. 迁移路线

### 13.1 第一阶段

建立最小闭环：

1. 本地文件/目录
2. MinIO 对象
3. HTTP 在线资源
4. 缓存命中

并先支持：

1. `mat`
2. `nc/hdf/h5`
3. `tif`
4. `csv/json`

### 13.2 第二阶段

1. 改造 `dispatch.py`
2. 输出标准 `PreparedInput`
3. 让首个试点模块接入新底座

### 13.3 第三阶段

1. 迁移 `daily_bundle`
2. 迁移 `smap_daily`
3. 迁移 `ndvi_daily`
4. 迁移 `fy_daily`
5. 迁移 `station_daily`

## 14. 建议试点

优先建议从以下模块中选一个试点：

1. `smap_daily`
2. `daily_bundle`

原因：

1. 输入格式相对集中
2. 依赖路径较明确
3. 能快速验证本地、缓存、对象存储三类来源

## 15. 相关文档

进一步背景与接口上下文可参考：

1. [backend_integration_contract.md](file:///d:/Workspace/mat2py/docs/backend_integration_contract.md)
2. [workflow_extension_design.md](file:///d:/Workspace/mat2py/docs/workflow_extension_design.md)
3. [platform_queue_worker_integration.md](file:///d:/Workspace/mat2py/docs/platform_queue_worker_integration.md)
