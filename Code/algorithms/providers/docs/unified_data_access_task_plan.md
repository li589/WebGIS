# 统一数据访问改造任务计划

## 1. 任务目标

本计划用于把“缓存数据、在线数据、MinIO 对象、本地直接对象、多格式文件”的统一接入能力逐步落到代码，而不破坏当前 `run_job()`、模块注册和 WebGIS-facing 接口。

对应设计文档见：

1. [unified_data_access_design.md](file:///d:/Workspace/mat2py/docs/unified_data_access_design.md)

## 2. 约束

1. 不重写调度器
2. 不一次性重写所有模块
3. 先兼容现有 `DataSourceAdapter`
4. 优先保证 `run_job()` 主链稳定
5. 先做最小闭环，再扩格式与模块覆盖

## 3. 阶段拆解

### 阶段 A：契约与骨架

目标：

1. 建立新的统一数据访问契约
2. 不影响现有模块运行

任务：

1. 新增 `Python/data_access/contracts.py`
2. 新增 `ResourceRef`
3. 新增 `PreparedInput`
4. 新增格式注册表骨架
5. 新增数据源注册表骨架

验收标准：

1. 新契约对象可单独导入
2. 不修改现有模块即可通过基础导入测试
3. 与现有 `DataSourceAdapter` 的映射关系明确

### 阶段 B：来源适配器最小闭环

目标：

1. 打通四类来源

任务：

1. 实现 `local_fs` source
2. 实现 `minio` source
3. 实现 `http` source
4. 实现 `cache` source
5. 实现最小 `Locator/Resolver/Fetcher/Materializer`

验收标准：

1. 能根据统一请求得到 `ResourceRef`
2. 能返回物化后的本地资源
3. 能区分缓存命中与远端下载

### 阶段 C：格式适配第一批

目标：

1. 打通最关键格式

任务：

1. `mat` 适配器
2. `nc/hdf/h5` 适配器
3. `tif` 适配器
4. `csv` 适配器
5. `json` 适配器

验收标准：

1. 每种格式至少提供 `probe/load/materialize`
2. 能映射到统一逻辑类型
3. 能输出标准化加载结果或标准物化结果

### 阶段 D：接入 `dispatch.py`

目标：

1. 让统一数据访问底座正式进入执行主链

任务：

1. 改造 [dispatch.py](file:///d:/Workspace/mat2py/Python/runner/dispatch.py)
2. 让 `_prepare_required_datasets()` 产出 `PreparedInput`
3. 保留 `_prepared_bundles` 兼容字段
4. 增加结构化日志字段，标记来源、格式、缓存命中、物化路径

验收标准：

1. 旧入口不崩
2. 新字段可用于后续模块迁移
3. 兼容服务层、异步任务与 HTTP 路径

### 阶段 E：试点模块迁移

目标：

1. 找一个模块验证新底座真实可用

推荐试点：

1. `smap_daily`
2. `daily_bundle`

任务：

1. 模块优先消费标准化输入
2. 仅在兼容模式下回退到路径直连
3. 补试点模块回归测试

验收标准：

1. 同时支持本地与对象存储输入
2. 不需要模块自己解析 MinIO/HTTP/本地路径
3. 行为与原结果保持一致

### 阶段 F：扩格式与扩模块

目标：

1. 继续补齐格式和模块覆盖

任务：

1. 增加 `txt`
2. 增加 `excel`
3. 增加 `xml`
4. 增加 `shp`
5. 逐步迁移 `ndvi_daily`
6. 逐步迁移 `fy_daily`
7. 逐步迁移 `station_daily`

验收标准：

1. 新格式可在统一注册表中发现
2. 新模块不新增路径直连技术债

## 4. 建议任务顺序

建议按以下顺序执行：

1. 先完成阶段 A
2. 再完成阶段 B
3. 接着完成阶段 C
4. 然后改造阶段 D
5. 再做阶段 E
6. 最后进入阶段 F

## 5. 每阶段输出物

### 阶段 A 输出

1. 契约代码
2. 契约测试
3. 注册表骨架

### 阶段 B 输出

1. 来源适配器骨架
2. 本地/HTTP/MinIO/缓存基础测试

### 阶段 C 输出

1. 格式适配器
2. 样例输入测试

### 阶段 D 输出

1. `dispatch.py` 主链接入
2. `PreparedInput` 注入与日志输出

### 阶段 E 输出

1. 试点模块迁移
2. 回归测试与对比结果

### 阶段 F 输出

1. 扩格式支持
2. 扩模块支持
3. 文档补充

## 6. 风险点

1. 旧模块过度依赖裸路径
2. 同一格式在不同模块中的字段口径不一致
3. MinIO 与本地缓存的副本管理可能引入重复存储
4. `nc/hdf/h5/mat` 之间的加载表示需要统一，避免模块层再次分叉
5. 试点模块如果选得过重，会拉长首轮闭环时间

## 7. 建议测试清单

1. 本地目录命中 -> 直接物化
2. MinIO 对象 -> 下载到缓存 -> 本地物化
3. HTTP 资源 -> 下载到缓存 -> 格式识别
4. 缓存命中 -> 跳过重复下载
5. `mat` 读取
6. `h5` 读取
7. `tif` 读取
8. `csv` 读取
9. `json` 读取
10. 试点模块在新旧输入模式下结果一致

## 8. 新对话建议起步任务

新对话开始后，建议直接执行以下首个工作包：

1. 新建 `Python/data_access/` 目录
2. 落 `contracts.py`
3. 落 `registry.py`
4. 落 `sources/local_fs.py`
5. 落 `sources/http.py`
6. 落 `sources/minio.py`
7. 落 `sources/cache.py`
8. 补最小 `unittest`

## 9. 完成判据

当以下条件满足时，可视为第一轮目标完成：

1. `dispatch.py` 能生成标准化 `PreparedInput`
2. 至少一个模块不再直接依赖裸路径
3. 本地、HTTP、MinIO、缓存四类来源可统一接入
4. 至少五种格式已具备稳定适配能力
5. 新增测试覆盖核心来源与试点模块
