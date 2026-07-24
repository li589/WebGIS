# MATLAB 代码 Python 化与 WebGIS 后端重构蓝图报告

## 一、报告目的

这份报告不是把当前仓库简单理解为“若干 MATLAB 脚本需要翻译成 Python”，而是把它视为一个已经成形但仍停留在科研脚本阶段的遥感反演生产链。  
从代码和数据组织方式来看，它已经具备了比较完整的业务链条：

1. 前端数据预处理。
2. 多源遥感输入整理。
3. 地面站点验证数据整理。
4. 主反演与后处理。

但是，这套流程当前仍然主要服务于“本地离线实验”和“单次跑一个结果”的科研使用方式。  
而你们课题组要建设的是一个 WebGIS 平台，这意味着后端目标已经发生了根本变化：

1. 不能只支持单个脚本、单次实验。
2. 不能只产出一个最终结果文件。
3. 不能只面向研究者自己理解结果。
4. 必须支持多数据层、多时间序列、多源组合、多次重复调用。
5. 必须支持结果展示、查询、保存、下载与追溯。

因此，真正要做的事情是：

**把一套 MATLAB 科研脚本，重构为一套可扩展、可复现、可服务化的 Python 遥感产品后端。**

## 二、当前代码仓库的真实结构

当前仓库的核心目录是 `Matlab/`，按 A/B/C/D 四类模块组织。

### 2.1 A 模块：植被指数 NDVI 预处理

对应文件包括：

- `Matlab/A1_VNP13C1.m`
- `Matlab/A2_MOYD13C1.m`
- `Matlab/A3_VI_daily.m`
- `Matlab/A4_NDVI_diff_daily.m`
- `Matlab/A5_NDVI_diff_all.m`

它们的主要功能是：

1. 从 VIIRS 或 MODIS 原始产品中提取 NDVI 与 QA。
2. 做重投影、掩膜、升尺度。
3. 把 16 天合成 NDVI 进一步插值为逐日 NDVI。
4. 计算动态 NDVI 与气候态 NDVI 之间的差异指标。

这部分本质上是一个**时序栅格预处理链**。

### 2.2 B 模块：SMAP 与 FY 微波亮温输入整理

对应文件包括：

- `Matlab/B1_SMAPL3.m`
- `Matlab/B2_FY3D_TB.m`
- `Matlab/B3_FY3B_TB.m`
- `Matlab/FY3B.py`
- `Matlab/FY3dfinalfinal.py`

它们的主要功能是：

1. 从 SMAP L3 HDF5 中提取 `TBv/TBh/Ts/VWC/IA/SM/VOD`。
2. 从 FY-3B / FY-3D MWRI 条带数据中提取亮温和角度信息。
3. 对 FY 条带数据进行地理定位、拼接、重投影、裁剪和标准化。

这部分本质上是一个**多源微波遥感输入标准化链**。

### 2.3 C 模块：地面站点验证数据整理

对应文件包括：

- `Matlab/C1_ISMN_origin.m`
- `Matlab/C2_ISMN_5cm.m`
- `Matlab/C3_China_10cm.m`
- `Matlab/C4_China_10cm.m`

它们的主要功能是：

1. 读取 ISMN 原始站点文本。
2. 把站点时间序列整理成站点级、日均级、过境时刻级结果。
3. 把中国站点数据整理成统一的站点时间序列。
4. 把站点投到 SMAP 网格，用于后续验证与对比。

这部分本质上是一个**点观测时序整理与点-网格匹配链**。

### 2.4 D 模块：主反演与后处理

对应文件包括：

- `Matlab/D1_raw_omeg.m`
- `Matlab/D2_avg_sm_vod.m`
- `Matlab/Function/DDCA.m`
- `Matlab/Function/Tau.m`
- `Matlab/Function/Retrieve_DH.m`
- `Matlab/Function/F_sm.m`

它们的主要功能是：

1. 统一读取前面 A/B/C 产出的标准日文件。
2. 结合辅助静态场与温度方案执行反演。
3. 反演 `SM/VOD/OMEGA/h/alpha/QC` 等结果。
4. 进一步构建多年平均 `omega`，并回代逐日产品。

这部分本质上是一个**以逐像元数值优化为核心的反演生产链**。

## 三、当前代码的运行范式与根本局限

从工程角度看，这套代码是典型的科研脚本范式。

### 3.1 当前运行范式

目前代码的基本模式可以概括为：

1. 人工改脚本里的路径和年份。
2. 运行某一个脚本。
3. 在某个输出目录得到一批 `.mat` 或 `.tif`。
4. 再由下一个脚本继续消费这些结果。

这套方式对做论文、做局部实验是有效的，但对 WebGIS 平台有明显限制。

### 3.2 主要问题

#### 1. 路径硬编码严重

代码中大量出现：

- Windows 本地盘符路径
- 映射盘路径
- Linux 服务器共享路径

这意味着代码逻辑和运行环境是强耦合的。

#### 2. 输入输出接口是隐式的

很多脚本默认：

1. 文件名前 8 位就是日期。
2. 某个目录下所有 `.mat` 都满足同一变量结构。
3. 变量名固定，且不会变化。

这在单人研究环境中尚可接受，但在服务化场景中非常脆弱。

#### 3. 中间结果依赖 `.mat`

`.mat` 很适合 MATLAB 本地工作流，但不适合：

1. WebGIS 展示。
2. 增量更新。
3. 分块读取。
4. 元数据管理。
5. 前后端协作。

#### 4. 输出以“实验目录”为中心，而不是“产品目录”为中心

当前更像是：

“某次实验的某个输出文件夹”

而不是：

“某个标准产品在某个日期、某个层次、某个区域下的稳定输出”

#### 5. 算法层、I/O 层、配置层混在一起

这会导致后续 Python 重写时，如果不先拆层，就很容易把 MATLAB 的问题原样搬过去。

## 四、结合在线资料对关键数据源的核实

你提出的要求非常关键：报告不能只看代码，还要确认这些数据本身是不是时间序列数据、是不是多源数据，以及它们的时间和空间分辨率。  
这一部分我结合公开资料做了补充核实。

### 4.1 总体判断

当前项目处理的并不是单一静态数据，而是一组典型的**多源、多尺度、多时序遥感与地面观测数据**：

1. NDVI 是长时间序列植被指数数据。
2. SMAP 是日尺度被动微波土壤水分与亮温数据。
3. FY-3B/FY-3D 是轨道条带微波亮温数据，天然属于时序遥感观测。
4. ISMN 是多网络、多站点、多深度的原位时间序列数据。
5. 中国站点数据也属于多站点、多深度、按时间连续观测的数据。

因此，从平台设计角度看，这个项目天然就不是“单文件输入 -> 单文件输出”的任务，而应该被建模为：

**多源时空数据融合与产品生产系统。**

### 4.2 数据源事实表

下表把代码中主要数据源与公开资料核实结果放在一起。

| 数据源 | 代码位置 | 数据类型 | 是否时间序列 | 是否多源/多维 | 公开资料对应分辨率与特征 | 对 WebGIS 的意义 |
|---|---|---|---|---|---|---|
| VNP13C1（VIIRS NDVI） | `A1_VNP13C1.m` | 全球栅格 | 是 | 是，含 NDVI/EVI/EVI2/QA/反射率/角度等 | 公开产品描述为 16 天、0.05 度 CMG，约 5.6 km，全球连续序列 | 适合作为植被时序层、气候态层、异常层 |
| MYD13C1（MODIS Aqua NDVI） | `A2_MOYD13C1.m` | 全球栅格 | 是 | 是，和 MOD13C1 形成 Terra/Aqua 互补体系 | 公开产品描述为 16 天、0.05 度 CMG，约 5.6 km，全球连续序列 | 可与 VIIRS 共同构成跨传感器植被时间序列 |
| SMAP SPL3SMP_E | `B1_SMAPL3.m` | 全球栅格 | 是 | 是，含亮温、土壤水分、辅助变量 | 公开产品描述为日尺度、9 km、EASE-Grid 2.0，2015 年以来连续更新 | 是标准日产品，可直接形成 WebGIS 日图层 |
| FY-3B/FY-3D MWRI | `B2/B3/FY3B.py/FY3dfinalfinal.py` | 轨道条带栅格 | 是 | 是，5 个频率、双极化、升降轨、多通道 | 公开资料显示 MWRI 为圆锥扫描，幅宽约 1400 km，不同频率原始足迹不同；10.65 GHz 为空间足迹较粗通道 | 适合做多源亮温层、轨道到日图层转换、SMAP 对比层 |
| ISMN | `C1/C2` | 站点时序 | 是 | 是，多网络、多传感器、多深度 | ISMN 是国际土壤水分网络，文件结构本身就是按站点/变量/深度组织的时间序列 | 适合做站点验证、点查曲线、区域统计对比 |
| 中国站点网络（代码中 C3/C4） | `C3/C4` | 站点时序 | 是 | 是，多站点、多深度 | 从公开资料看，国内同类公开数据集常见为 30 分钟观测、5/10/20/40 cm 多深度，并可聚合到日尺度 | 适合做中国区域验证层与多深度时序展示 |

### 4.3 VNP13C1 / MYD13C1 的时间序列属性

从公开产品说明看：

1. `VNP13C1` 是 VIIRS 16 天合成、0.05 度全球 CMG 产品。
2. `MOD13C1/MYD13C1` 是 MODIS 16 天合成、0.05 度全球 CMG 产品。
3. 它们都不是单景静态影像，而是稳定发布的长时间序列产品。
4. 这些产品不只包含 NDVI，还通常带有 QA、反射率、角度、统计量等附加层。

这意味着：

1. A 模块本质上处理的是**多变量时序栅格数据**。
2. 平台层面不应该只产出一个 `NDVI`。
3. 应该同时考虑：
   - `NDVI daily`
   - `NDVI climatology`
   - `NDVI anomaly`
   - `NDVI valid-count`
   - `NDVI QA`

对 WebGIS 而言，这一类产品天然适合做：

1. 时序播放。
2. 某点历史曲线。
3. 区域平均曲线。
4. 气候态与异常对比图层。

### 4.4 SMAP 的时间序列与多变量属性

公开资料显示，`SPL3SMP_E` 属于：

1. 日尺度产品。
2. 9 km EASE-Grid 2.0 产品。
3. 含亮温与表层土壤水分等变量。
4. 自 2015 年以来持续更新。

而代码里 `B1_SMAPL3.m` 实际读取的变量包括：

1. `TBh`
2. `TBv`
3. `Ts`
4. `vwc`
5. `IA`
6. `sm_dca`
7. `sm_scav`
8. `vod_dca`
9. `vod_sca`

也就是说，SMAP 在当前项目里并不只是“一个土壤水分产品”，而是一个**多变量日尺度微波观测与反演数据包**。

这对后端设计的启发很直接：

1. 一个日期的 SMAP 产品应视为一个 bundle，而不是一个单变量文件。
2. WebGIS 应支持同一天多图层联动显示。
3. 平台应支持用户在 `TBv/TBh/SM/VOD/Ts/VWC` 之间切换。
4. 这些图层要能共享同一时间轴和同一空间网格。

### 4.5 FY-3B / FY-3D MWRI 的时间序列与多源属性

公开资料显示：

1. FY-3 系列 MWRI 为圆锥扫描微波成像仪。
2. 具有多频率、双极化观测。
3. 幅宽约 1400 km。
4. 原始空间足迹随频率不同而变化，低频通道足迹更粗，高频更细。

结合代码可以看出：

1. 当前项目主要使用 10 GHz 左右的 H/V 亮温。
2. 输入并不是已经规则化的网格日产品，而是条带轨道数据。
3. 需要经过地理定位、VRT 构建、warp、拼接、重投影后，才能进入标准网格。
4. 在日尺度上，FY 数据往往是“日内多轨道 -> 日产品”的过程。

这说明 FY 数据的时间特征与 SMAP 不同：

1. SMAP 更接近“官方标准日产品”。
2. FY 更接近“轨道观测集合，需要二次组织成日尺度产品”。

因此，FY 不能简单地当成静态输入处理。它需要单独的一层：

**轨道数据编排层**

这一层的职责不是反演，而是：

1. 发现轨道文件。
2. 区分升轨/降轨。
3. 组织某一天的所有轨道。
4. 进行投影与空间标准化。
5. 输出与 SMAP 可对接的统一网格日产品。

### 4.6 ISMN 的多网络、多深度、多时序属性

ISMN 本身就是一个国际原位土壤水分网络平台。公开说明表明：

1. 它是多网络汇聚，而不是单站点单格式数据。
2. 文件命名中明确包含站点、变量、深度、传感器和起止日期。
3. 原始记录具有严格的时间序列属性。
4. 深度信息是该数据的重要维度，不是附属属性。

从代码 `C1/C2` 可以看到，当前处理流程也正是：

1. 先读原始时序。
2. 再构造日均与过境时刻值。
3. 再构造成站点-日矩阵。
4. 最后映射到网格。

因此，ISMN 在后端中不应只作为“验证表格”存在，而应当建模成：

1. 点位图层。
2. 站点时间序列服务。
3. 站点与网格对应关系服务。
4. 多深度观测服务。

### 4.7 中国站点数据的判断

代码中使用的是 `China_10cm` 与 `casmos` 命名，但公开可直接检索到的更接近数据集，是面向高分辨率卫星应用的中国土壤水分观测网络数据。公开资料显示，这类中国站网数据一般具有以下特征：

1. 多站点。
2. 多深度。
3. 30 分钟级或更高频观测。
4. 可以聚合为日尺度。
5. 可用于像元尺度或站点尺度验证。

这与 `C3/C4` 的代码逻辑是高度一致的。  
也就是说，即便公开命名与仓库里的 `CASMOS` 不完全一致，从数据结构上看，它属于同一类问题：

**中国区域站点型土壤水分多深度时间序列数据。**

对于 WebGIS 来说，这类数据最适合做：

1. 中国区域验证点图层。
2. 站点 10 cm 曲线。
3. 多深度曲线对比。
4. 站点与遥感反演的匹配分析。

## 五、项目输入输出的重新定义

当前 MATLAB 脚本的输入输出是按文件和目录隐式组织的。  
Python 重写时必须把它显式化。

### 5.1 输入数据分类

建议把输入数据重定义为六类。

#### 第一类：原始遥感轨道/格网产品

包括：

- VNP13C1 / MYD13C1 HDF/HDF5
- SMAP HDF5
- FY-3B / FY-3D HDF

特点：

1. 原始格式异构。
2. 自带时间信息。
3. 需要 QA、投影、变量提取。

#### 第二类：标准化日尺度遥感产品

包括：

- 每日 NDVI
- 每日 SMAP `TBv/TBh/Ts/VWC/SM/VOD`
- 每日 FY `TBv/TBh/IA`

特点：

1. 统一日期维度。
2. 统一网格。
3. 可直接供反演消费。

#### 第三类：静态辅助栅格

包括：

- 土地覆盖
- 粘土含量
- 体密度
- 孔隙度
- 静态 SF
- 其他辅助场

特点：

1. 时间维度固定或很慢变化。
2. 是反演过程的重要先验场。

#### 第四类：准静态气候态产品

包括：

- `NDVI_clim`
- `omega_doy_avg`
- 年度 h 图等

特点：

1. 不是完全静态。
2. 但也不是逐时逐日原始观测。
3. 更像“按 DOY 或按年组织的背景场”。

#### 第五类：站点时间序列数据

包括：

- ISMN
- 中国站点网络

特点：

1. 点位数据。
2. 有深度维度。
3. 有时间维度。
4. 需要和网格产品联动。

#### 第六类：模型或外部驱动数据

包括：

- GLDAS 温度
- DDCA 中间结果
- 其他辅助再分析产品

特点：

1. 既是输入，也是后续融合对象。
2. 往往也具有完整时间序列。

### 5.2 输出产品分类

Python 后端不应只输出“一个结果”。  
应该把输出建模为产品包。

建议分为五类。

#### 1. 地图图层产品

例如：

- `ndvi_daily`
- `sm_daily`
- `vod_daily`
- `omega_daily`
- `tbv_daily`
- `qf_daily`

#### 2. 聚合统计产品

例如：

- 月平均
- 年平均
- DOY 平均
- 区域平均
- 异常图层

#### 3. 站点对比产品

例如：

- 站点实测与反演对比表
- 站点时序曲线
- 站点误差指标

#### 4. 质量控制产品

例如：

- 有效观测数
- 缺测掩膜
- 反演失败掩膜
- 条件数或稳定性指标

#### 5. 元数据与任务记录产品

例如：

- 运行配置
- 数据来源
- 产品版本
- 生成时间
- 处理日志

## 六、为什么必须从“单结果脚本”升级到“产品矩阵”

这是整个重构最关键的一点。

### 6.1 当前模式的问题

当前脚本更像这样：

1. 选一个数据源。
2. 指定一个年份。
3. 运行一次。
4. 生成一个输出目录。

这是一种“实验驱动”的组织方式。

### 6.2 WebGIS 需要的模式

WebGIS 更像这样：

1. 选一个区域。
2. 选一个时间范围。
3. 选一个数据主题。
4. 平台自动返回多个同步产品。

比如同一个请求可能需要同时产出：

1. `SM` 地图。
2. `VOD` 地图。
3. `OMEGA` 地图。
4. `QC` 地图。
5. 该区域平均时间序列。
6. 该区域站点对比曲线。
7. 该任务的元数据记录。

这已经不是“一个脚本出一个文件”的逻辑了，而是：

**一个任务出一个产品矩阵。**

### 6.3 产品矩阵的推荐维度

建议把后端产品组织成以下五个维度：

#### 变量维

- NDVI
- TBv
- TBh
- Ts
- SM
- VOD
- OMEGA
- QC

#### 来源维

- VIIRS
- MODIS Aqua
- MODIS Terra
- SMAP
- FY-3B
- FY-3D
- ISMN
- 中国站点网络

#### 时间维

- 每日
- 8 天块
- 月
- 年
- 多年平均
- DOY 气候态
- 异常

#### 空间维

- 全球
- 全国
- 流域
- 行政区
- 网格块
- 站点邻域

#### 处理阶段维

- 原始
- 标准化
- 匹配后
- 反演后
- 质量控制后
- 验证后

这五个维度一旦确立，后端结构才会真正适合 WebGIS。

## 七、面向 WebGIS 的目标架构

### 7.1 总体原则

目标架构必须实现以下分离：

1. 配置与代码分离。
2. 算法与 I/O 分离。
3. 中间数据与发布数据分离。
4. 任务编排与科学计算分离。
5. 数据产品与展示接口分离。

### 7.2 推荐五层架构

#### 第一层：数据接入层 `ingest`

负责：

1. 扫描目录。
2. 识别文件名中的日期和来源。
3. 读取 HDF/HDF5/TIFF/TXT/CSV。
4. 提取元数据。

这一层不做科学计算，只解决“把原始数据读进来”。

#### 第二层：标准化层 `standardize`

负责：

1. 重投影。
2. 重采样。
3. 单位转换。
4. NoData 处理。
5. 时间轴对齐。
6. 升降轨合并。
7. 点-网格映射。

这一层解决的是“把异构数据变成统一内部格式”。

#### 第三层：科学算法层 `algorithms`

负责：

1. SG 滤波与插值。
2. NDVI 气候态和异常计算。
3. Tau 计算。
4. 动态 h 反演。
5. DDCA 反演。
6. OMEGA 平均与回代。

这一层应该尽量纯粹，不依赖具体路径和目录结构。

#### 第四层：任务编排层 `pipelines`

负责：

1. 定义一次任务的开始与结束。
2. 明确依赖关系。
3. 分块执行。
4. 并行调度。
5. 失败重试。
6. 日志记录。

例如：

- 生成 2019 年全国日尺度 NDVI 产品。
- 生成 2020 年 5 月 FY-3D 日尺度亮温产品。
- 生成某区域某时间段的反演产品包。

#### 第五层：产品发布层 `publish`

负责：

1. 输出 WebGIS 可直接消费的产品。
2. 生成元数据清单。
3. 写入展示图层。
4. 写入时间序列表。
5. 写入下载包。

这是最贴近平台接口的一层。

## 八、推荐的 Python 仓库结构

考虑到后续要把整套 Python 代码整体复制到后端处理脚本目录，实际落点固定为 `d:\Workspace\mat2py\Python`。  
当前已确认不再使用早期设想中的 `Python/mat2py/` 二级包结构，而是直接在 `Python/` 根目录下分层组织。

```text
mat2py/
  docs/
    blueprint_report.md
    detailed_design.md
    field_mapping_contract.md
  Python/
    contracts/
    interfaces/
    runner/
    ingest/
    algorithms/
    pipelines/
    utils/
    README.md
    pyproject.toml
    requirements.txt
```

### 8.1 当前已落地的主干模块

目前已经落地的关键文件包括：

- `ingest/mat_bundle.py`
- `ingest/daily_bundle.py`
- `ingest/timeseries_bundle.py`
- `ingest/ndvi_hdf_preprocess.py`（Matlab **A1/A2**：VNP13C1/MOYD13C1 → 9 km TIF）
- `algorithms/physics.py`
- `algorithms/inversion.py`
- `algorithms/block_inversion.py`
- `algorithms/omega.py`
- `algorithms/omega_avg.py`（Matlab **D2**）
- `modules/ndvi_hdf_preprocess.py`
- `modules/omega_avg_daily.py`
- `pipelines/daily_bundle_products.py`
- `pipelines/timeseries_bundle_products.py`
- `pipelines/block_inversion_products.py`
- `pipelines/omega_block_products.py`
- `pipelines/retrieval_workflow_products.py`

**A4/A5**：仍嵌在 `ndvi_daily`（日插值与气候态差分/质量产物），未单独拆入口；需要时可后续加可选 module。

**SG polyorder**：Matlab 历史默认 6；Python `algorithms/ndvi.py` 与模块/pipeline 默认 **3**（见 `regression_checklist.md` §2.9）。

### 8.2 当前已注册的 pipeline

当前真正可直接被调度调用的兼容 pipeline 以 `runner/registry.py` 为准：

- `smap_daily_pipeline`
- `ndvi_daily_pipeline`
- `fy_daily_pipeline`
- `station_daily_pipeline`
- `inversion_daily_pipeline`
- `daily_bundle_pipeline`
- `timeseries_bundle_pipeline`
- `block_inversion_pipeline`
- `omega_block_pipeline`
- `retrieval_workflow_pipeline`

这些名称当前都应视为兼容入口。默认请求应优先使用：

- `module_name=<native module>`
- `workflow_name=<workflow preset>`

当前统一入口还支持直接传入 `workflow_definition`，但运行时要求它已经是 `WorkflowDefinition` 实例；如果请求来自 JSON/接口层，应该先完成反序列化，再交给 `run_job()`。

### 8.3 结构化配置的新增要求

随着 `DUAL` 温度链、`Exp1a/Exp1b/Exp2` 和 `QC` 诊断逐步落地，当前代码已经不再适合“默认所有字段名固定不变”的假设。  
因此，后续结构设计需要补一条明确原则：

1. 原始日 MAT 字段名允许通过 `algorithm_params` 配置别名。
2. `timeseries bundle` / `omega` / `block_inversion` 的 MAT 字段名允许通过 builder 配置别名。
3. 算法层统一遵守 shape 契约：
   - 时序输入使用 `(nt, npix)`
   - 静态输入使用 `(npix,)`
   - 标量、1D 和 `(1, npix)` 允许自动广播

这部分的执行性规范请参考 [field_mapping_contract.md](file:///d:/Workspace/mat2py/docs/field_mapping_contract.md)。

## 九、存储与发布策略

### 9.1 中间层存储

中间层建议逐步摆脱“全量 `.mat`”依赖。

推荐：

- 多维栅格中间结果：`Zarr` 或 `NetCDF`
- 站点时间序列：`Parquet`
- 临时兼容结果：保留 `MAT` 作为过渡

原因很简单：

1. 便于分块。
2. 便于局部读取。
3. 便于跨语言。
4. 便于云端或服务端管理。

### 9.2 发布层存储

面向 WebGIS 的发布格式建议为：

- 栅格图层：`COG`
- 时间序列表：`Parquet`
- 元数据：`JSON`
- 统计表或区域结果：数据库表或 `Parquet`

### 9.3 为什么不能继续把 `.mat` 当主发布格式

因为 `.mat`：

1. 不便于地图服务直接读取。
2. 不利于前端按需访问。
3. 不利于切片和部分下载。
4. 不利于元数据标准化。

所以它可以作为兼容层存在，但不应是最终平台产品层。

## 十、性能重构思路

### 10.1 主要性能瓶颈

从代码看，性能热点主要有三类：

#### 1. 大栅格时序处理

典型代表：

- `A3_VI_daily.m`
- `A4_NDVI_diff_daily.m`

本质是：

1. 三维数组堆叠。
2. 逐像元时间序列处理。
3. 再回写逐日结果。

#### 2. 逐像元非线性优化

典型代表：

- `DDCA.m`
- `Retrieve_DH.m`
- `D1_raw_omeg.m`
- `D2_avg_sm_vod.m`

本质是：

1. 对大量像元重复做优化。
2. 每个像元都有代价函数。
3. 对并行和分块高度敏感。

#### 3. 条带数据空间标准化

典型代表：

- `FY3B.py`
- `FY3dfinalfinal.py`

本质是：

1. 多轨道条带重投影。
2. 多文件拼接。
3. 大量 I/O。

### 10.2 Python 侧的性能工具栈

建议的高性能基础栈为：

- `numpy`
- `scipy`
- `numba`
- `xarray`
- `dask`
- `rasterio`
- `pyproj`
- `h5py`
- `netCDF4`
- `joblib`

### 10.3 性能原则

重写时要遵循以下原则：

1. 尽量矢量化，不写无意义双重 Python 循环。
2. 对大栅格按块处理，而不是一次读入所有年份和所有变量。
3. 对逐像元优化函数做纯函数化，方便 JIT 和并行。
4. 把 I/O 密集任务与计算密集任务拆开。
5. 把重复使用的气候态和静态辅助场做缓存。

## 十一、模块级重构建议

### 11.1 A 模块重构目标

建议拆成：

- `ingest.ndvi`
- `standardize.ndvi`
- `algorithms.ndvi`
- `pipelines.ndvi_products`

可直接面向 WebGIS 产出的图层包括：

- `ndvi_daily`
- `ndvi_monthly`
- `ndvi_climatology`
- `ndvi_anomaly`
- `ndvi_valid_count`

### 11.2 B 模块重构目标

建议拆成：

- `ingest.smap`
- `ingest.fy3`
- `standardize.tb`
- `pipelines.tb_products`

可直接面向 WebGIS 产出的图层包括：

- `tbv_daily`
- `tbh_daily`
- `ts_daily`
- `ia_daily`
- `smap_sm_daily`
- `smap_vod_daily`

说明：

这里描述的是面向 WebGIS 发布层的最终目标接口。
当前 Python 迁移代码在兼容阶段仍会保留 `fy_daily_tif`、`fy_daily_mat` 等中间与交换产物，用于承接 MATLAB 口径验证和后续发布适配。

### 11.3 C 模块重构目标

建议拆成：

- `ingest.station`
- `standardize.station`
- `validation.station_grid`

可直接面向 WebGIS 产出的产品包括：

- 站点点图层
- 站点时序曲线
- 站点与网格比对结果
- 深度剖面对比结果

说明：

这些是最终平台侧的消费形态；
当前 Python 兼容层则以 `station_daily_mat`、`station_am6_mat`、`station_site/grid/net_validation_mat` 等 MAT 产物承接 MATLAB `C2/C4` 验证链。

### 11.4 D 模块重构目标

建议拆成：

- `algorithms.physics`
- `algorithms.inversion`
- `pipelines.inversion_products`
- `publish.product_catalog`

可直接面向 WebGIS 产出的图层包括：

- `sm_daily`
- `vod_daily`
- `omega_daily`
- `qc_daily`
- `omega_doy_avg`

## 十二、建议的产品组织方式

### 12.1 一个任务对应一个产品包

例如一次反演任务完成后，不是只写：

- `20250701.mat`

而是写成一个完整产品包：

1. `sm_daily_20250701.tif`
2. `vod_daily_20250701.tif`
3. `omega_daily_20250701.tif`
4. `qc_daily_20250701.tif`
5. `region_timeseries_20250701_20250731.parquet`
6. `run_manifest.json`

### 12.2 一个产品包内部的层次

建议统一包含：

1. 主图层。
2. 辅助图层。
3. 质量图层。
4. 时间序列产物。
5. 元数据。

## 十三、转换顺序建议

### 第一阶段：先定义规范，不急于全面翻译

先完成：

1. 数据模型。
2. 命名规范。
3. 产品目录结构。
4. 任务配置格式。

### 第二阶段：先转低风险标准化模块

优先级建议：

1. `B1_SMAPL3.m`
2. `A3_VI_daily.m`
3. `FY3B.py / FY3dfinalfinal.py` 的编排层

因为这些模块：

1. 输入输出较清晰。
2. 适合先形成标准日产品。
3. 能为后续 D 模块提供稳定接口。

### 第三阶段：补站点与验证产品

优先级建议：

1. ISMN 标准化。
2. 中国站点标准化。
3. 站点与网格联动产品。

### 第四阶段：重构 D 模块

优先级建议：

1. 先抽象物理核心函数。
2. 再做小范围像元验证。
3. 再做分块区域化运行。
4. 最后再做全球或大区域生产。

### 第五阶段：接入 WebGIS 服务层

包括：

1. 产品清单服务。
2. 图层查询服务。
3. 时间序列查询服务。
4. 下载服务。

## 十四、当前阶段最应该做的事

当前最不应该做的，是直接把 `D1_raw_omeg.m` 全量翻译成一个很长的 Python 文件。  
那样只会把 MATLAB 的结构问题原样搬过去。

当前最应该做的事，是先建立三样东西：

1. **统一数据接口**
2. **统一产品接口**
3. **统一任务接口**

一旦这三层接口稳定，后面的算法迁移才是可持续的。

## 十五、结论

综合代码扫描与公开资料核实，可以明确得出以下判断：

1. 当前项目处理的是典型的多源、多尺度、多时序遥感与站点数据。
2. 这些数据天然适合做时间序列产品，而不只是一次性离线反演。
3. 当前 MATLAB 代码已经包含了产品链雏形，但组织方式仍停留在科研脚本阶段。
4. Python 化的真正目标不是“把 MATLAB 语法换成 Python 语法”，而是“把科研脚本重构成 WebGIS 可服务后端”。
5. 对平台而言，未来的核心单位不应是“某个脚本的输出文件”，而应是“某个任务对应的一组标准化产品层与时间序列产品”。

换句话说，后续工作的判断标准不应是：

**Python 能不能复现一个 MATLAB 结果。**

而应是：

**Python 后端能不能稳定生成、组织、发布并管理多图层、多时间序列、多源融合的遥感产品。**

## 十六、你的职责边界需要重新明确

结合你这次新增的约束，整个系统的职责边界需要进一步收窄。  
你负责的不是整套 WebGIS 后端平台，也不是资源调度中心，而是：

**一套可被前后端平台和作业调度器调用的 Python 计算内核与统一封装层。**

这句话可以拆成四个层次。

### 16.1 你负责的部分

你应该负责：

1. 把现有 MATLAB / Python 脚本重构为统一的 Python 包。
2. 把 A/B/C/D 流程拆成可复用、可组合、可配置的 pipeline。
3. 把不同数据源的读取、缓冲、懒加载、部分下载调用方式标准化。
4. 把不同计算任务统一成一致的任务入口。
5. 把日志、阶段状态、进度、产物注册等能力统一暴露出来。
6. 把输出结果组织成标准化产品，而不是零散文件。

### 16.2 你不负责的部分

你不应该负责：

1. 实现完整的前端接口系统。
2. 实现集群资源调度器本身。
3. 实现账号权限、队列编排、容器编排、节点抢占等平台功能。
4. 实现数据库层的全量平台服务。

这些属于平台或调度系统的职责。  
你这里只需要保证：**别人能够稳定地调用你的计算包。**

### 16.3 从平台视角看，你的模块位于哪里

前后端平台的完整逻辑大致可以抽象为：

1. 前端发起请求。
2. 平台后端把请求转成作业描述。
3. 调度系统接收作业描述并安排资源。
4. 你的 Python 计算包在被分配的资源上运行。
5. 你的计算包通过数据接口取数、通过日志接口回报状态、通过产品接口交付结果。
6. 平台再把结果接回到查询、展示、下载链路。

也就是说，你的模块应该处在：

**“调度系统之后、算法执行之前，以及结果产出过程中”**

这个位置。

### 16.4 为什么这个边界很重要

如果边界不清晰，后续 Python 重构很容易出现两个问题：

1. 代码里混入大量平台侧逻辑，导致计算核心不可复用。
2. 计算包只适合手工运行，无法被调度系统稳定调用。

因此，后续设计原则应该是：

**把平台依赖压缩成少数几个稳定接口，把科学计算和数据处理逻辑尽量做成纯 Python 能力。**

## 十七、建议采用“3 个强制对外接口 + 1 个推荐产品接口”

你提到三个对外接口：

1. 作业调度接口
2. 数据源接口
3. 日志接口

这个判断是对的，但结合当前项目的实际情况，我建议做成：

1. **3 个强制对外接口**
2. **1 个推荐补充接口**

推荐补充的那个接口是：

4. **产品输出接口**

原因很简单：  
如果只有调度、数据源、日志三个接口，而没有统一的结果交付接口，那么最终仍然容易回到“脚本自己随便往某个目录写文件”的老路上。

所以更稳妥的方案是：

### 17.1 三个强制接口

- `作业调度适配接口`
- `数据源适配接口`
- `日志适配接口`

### 17.2 一个推荐补充接口

- `产品输出接口`

这个“产品输出接口”可以先作为内部标准，不一定一开始就开放给平台其他模块，但从代码组织上必须尽早存在。

## 十八、统一接口方案：面向“被调度调用”的 Python 计算包

这一节是整个新方案的核心。  
目标不是做一个平台，而是做一个**接口清晰、性能可控、参数统一、可被调度系统调用的计算框架**。

### 18.1 总体设计思想

建议整体做成：

1. 一个 Python 包。
2. 多个标准 pipeline。
3. 三个强制对外接口。
4. 一个统一任务入口。
5. 一个统一产品输出规范。

也就是说，外部系统只需要知道：

1. 传入什么任务描述。
2. 去哪里取数据。
3. 如何接收日志和状态。
4. 最终去哪里拿产品。

而不需要知道你的算法内部如何组织。

### 18.2 对外接口一：作业调度适配接口

这个接口不是调度器本身，而是**供调度器调用你的计算包的入口层**。

它解决的问题是：

1. 调度器如何启动你的任务。
2. 调度器如何把资源约束传给你。
3. 调度器如何传入作业参数。
4. 调度器如何获取任务状态和最终产物位置。

#### 建议职责

这个接口应该负责：

1. 接收标准化的任务请求对象。
2. 校验参数是否合法。
3. 选择对应的 pipeline。
4. 组装运行上下文。
5. 调用内部执行器。
6. 返回结构化结果。

#### 不应该负责

它不应该负责：

1. 自己分配机器。
2. 自己排队。
3. 自己做集群调度。

#### 建议输入对象

建议统一为 `JobRequest`，字段可包括：

- `job_id`
- `pipeline_name`
- `task_type`
- `time_range`
- `region`
- `datasource_selection`
- `algorithm_params`
- `resource_hint`
- `output_spec`
- `resume_policy`
- `module_name`
- `workflow_name`
- `workflow_definition`

补充说明：

1. 当前 `pipeline_name` 仍保留在契约里，兼容 pipeline 模式下必须填写真实注册名。
2. 当走 `module_name / workflow_name / workflow_definition` 三种 workflow 化入口时，`pipeline_name` 主要承担兼容占位职责，工程里通常传 `workflow`。

#### 建议输出对象

建议统一为 `JobResult`，字段可包括：

- `job_id`
- `run_id`
- `status`
- `started_at`
- `finished_at`
- `manifest_uri`
- `log_uri`
- `metrics`
- `error_summary`

#### 推荐接口形态

从工程实现角度，建议至少支持两种形态：

1. Python 函数入口
2. CLI 入口

例如：

- Python 调用：`run_job(request, scheduler_adapter, datasource_adapter, logger_adapter, product_sink)`
- CLI 调用：`python -m mat2py.cli run-job --config xxx.yaml`

这样既方便调度平台集成，也方便你本地调试。

### 18.3 对外接口二：数据源适配接口

这是你这里最重要的接口之一，因为你们的平台流程中，作业第一步就是“查找数据，等待数据就绪，再按需取数”。

当前代码里大量是：

1. 直接写死目录。
2. 假定文件已在本地。
3. 直接 `load` / `h5read` / `dir`。

而平台化后必须抽象成统一数据源接口。

#### 它要解决的问题

1. 数据在本地还是远程？
2. 数据是否已缓存？
3. 需要全量下载还是部分下载？
4. 是否允许懒加载？
5. 数据是否已经标准化？
6. 数据准备好之前作业如何等待？

#### 建议职责

建议把这个接口设计成四层能力：

1. `discover`：发现数据。
2. `resolve`：把业务查询转为具体数据对象。
3. `acquire`：获取数据，可选全量、部分、懒加载。
4. `materialize`：在真正计算前，把需要的局部数据实体化。

#### 推荐的获取模式

建议统一支持三种模式：

1. `lazy`
2. `partial`
3. `full`

含义分别是：

- `lazy`：只获取元数据和访问句柄，真正读取时再拉取。
- `partial`：只下载指定变量、时间窗、空间窗。
- `full`：拉取完整数据副本。

#### 为什么一定要这样设计

因为你们的数据并不统一：

1. SMAP 更像标准日产品，可较容易按日按变量取数。
2. FY 更像轨道文件集合，往往需要日内组织后再处理。
3. ISMN / 中国站点更像多站点时序，需要按站点、深度、时间过滤。

如果没有统一的数据源接口，后面每条 pipeline 都会重新写一套取数逻辑。

#### 建议输入对象

建议定义 `DataRequest`：

- `dataset_name`
- `variables`
- `time_range`
- `spatial_filter`
- `depth_filter`
- `target_grid`
- `acquire_mode`
- `cache_policy`

#### 建议输出对象

建议定义 `DataBundle`：

- `bundle_id`
- `dataset_name`
- `variables`
- `time_range`
- `storage_mode`
- `local_paths`
- `remote_refs`
- `metadata`
- `is_materialized`

### 18.4 对外接口三：日志适配接口

日志接口不能再只是 `disp`、`print` 或 MATLAB 控制台输出。  
你这里需要的是一个**可被平台消费的结构化日志接口**。

#### 它要解决的问题

1. 平台如何知道任务正在做什么？
2. 平台如何展示进度？
3. 出错时如何快速定位是在取数、预处理还是反演阶段？
4. 后续复现实验时如何回溯运行过程？

#### 建议职责

日志接口建议至少支持以下类型事件：

1. 作业开始
2. 阶段开始
3. 阶段完成
4. 进度更新
5. 警告
6. 错误
7. 产物注册
8. 性能统计

#### 为什么要用结构化日志

因为前后端平台通常不是“看终端输出”，而是：

1. 展示任务状态条。
2. 展示阶段状态。
3. 展示失败原因。
4. 展示性能和产物摘要。

因此建议日志消息至少携带：

- `job_id`
- `run_id`
- `stage`
- `event_type`
- `timestamp`
- `message`
- `progress`
- `extra`

#### 推荐接口方法

建议最少包括：

- `bind_context()`
- `emit_stage_start()`
- `emit_progress()`
- `emit_warning()`
- `emit_error()`
- `emit_artifact()`
- `emit_stage_end()`

### 18.5 推荐补充接口：产品输出接口

这个接口是我建议你额外补上的。

#### 为什么必须有

当前 MATLAB 模式最大的问题之一，就是输出文件随实验目录漂移。  
如果 Python 重构只定义“怎么运行”和“怎么取数”，却不定义“怎么交付产物”，那后面还是会散。

#### 它要解决的问题

1. 一个任务到底产生了哪些产品？
2. 哪些是地图图层？
3. 哪些是时间序列表？
4. 哪些是验证结果？
5. 平台如何知道图层名、时间、空间参考和下载地址？

#### 建议职责

产品输出接口建议负责：

1. 生成标准命名。
2. 统一写出栅格、表格和元数据。
3. 返回 `manifest`。
4. 注册产物 URI。

#### 建议输出对象

建议定义 `ProductManifest`：

- `job_id`
- `run_id`
- `products`
- `main_layers`
- `qc_layers`
- `tables`
- `metadata_uri`
- `created_at`
- `extra`

## 十九、建议的内部组织方式：外部三接口，内部四层核心

如果从代码结构上落地，建议做成下面这个模式：

### 19.1 外部边界层

这一层只处理平台交互边界：

- `SchedulerAdapter`
- `DataSourceAdapter`
- `LoggerAdapter`
- `ProductSink`

这一层不写算法。

### 19.2 任务入口层

这一层负责：

1. 接收 `JobRequest`
2. 解析任务类型
3. 选择 pipeline
4. 创建运行上下文

建议命名为：

- `runner.py`
- `dispatch.py`

### 19.3 pipeline 层

这一层负责把业务流程串起来。

例如：

- `ndvi_products.py`
- `smap_products.py`
- `fy_products.py`
- `station_products.py`
- `inversion_products.py`

它们负责“先干什么、后干什么”，但不直接写底层 I/O 细节。

### 19.4 kernel 层

这一层负责真正高性能计算：

1. NDVI 插值和滤波。
2. FY 轨道拼接后的栅格计算。
3. 逐像元反演。
4. OMEGA 聚合和回代。

这一层最需要高性能优化。

### 19.5 storage / publish 层

这一层负责标准化写出：

1. 栅格产品。
2. 表格产品。
3. 产品清单。
4. 缓存结果。

## 二十、推荐的代码接口原型

为了让这个方案更可执行，下面给一个建议的调用原型。

### 20.1 统一任务入口

```python
def run_job(
    request: JobRequest,
    scheduler_adapter: SchedulerAdapter,
    datasource_adapter: DataSourceAdapter,
    logger_adapter: LoggerAdapter,
    product_sink: ProductSink | None = None,
) -> JobResult:
    ...
```

这里有几点要说明：

1. `scheduler_adapter` 不是调度器本身，而是接收调度上下文的接口对象。
2. `datasource_adapter` 统一屏蔽本地文件、缓存层、远程拉取、懒加载差异。
3. `logger_adapter` 负责把运行信息推给外部系统。
4. `product_sink` 建议存在，即使初期只是写本地目录；当前实现中未显式传入时会回退到本地 manifest sink。

### 20.2 数据源接口原型

```python
class DataSourceAdapter(Protocol):
    def discover(self, request: DataRequest) -> list[Any]:
        ...

    def resolve(self, request: DataRequest) -> DataBundle:
        ...

    def acquire(self, bundle: DataBundle) -> DataBundle:
        ...

    def materialize(self, bundle: DataBundle) -> DataBundle:
        ...
```

### 20.3 日志接口原型

```python
class LoggerAdapter(Protocol):
    def bind_context(self, job_id: str, run_id: str) -> None:
        ...

    def emit_stage_start(self, stage: str, message: str) -> None:
        ...

    def emit_progress(self, stage: str, progress: float, message: str) -> None:
        ...

    def emit_warning(self, stage: str, message: str, extra: dict | None = None) -> None:
        ...

    def emit_error(self, stage: str, message: str, extra: dict | None = None) -> None:
        ...

    def emit_artifact(self, stage: str, artifact_uri: str, artifact_type: str) -> None:
        ...

    def emit_stage_end(self, stage: str, message: str) -> None:
        ...
```

### 20.4 产品输出接口原型

```python
class ProductSink(Protocol):
    def write_raster(self, product: RasterProduct) -> ProductRef:
        ...

    def write_table(self, product: TableProduct) -> ProductRef:
        ...

    def write_manifest(self, manifest: ProductManifest) -> str:
        ...
```

## 二十一、推荐的仓库结构调整

当前已经确认采用 `Python/` 根目录直铺的结构，因此这里把仓库结构调整为与现有代码一致的口径。

```text
Python/
  interfaces/
    scheduler.py
    datasource.py
    logger.py
    product_sink.py
  contracts/
    job.py
    data.py
    product.py
    event.py
  runner/
    dispatch.py
    runtime.py
  ingest/
  algorithms/
  pipelines/
  utils/
  README.md
  pyproject.toml
  requirements.txt
```

其中：

- `interfaces/` 定义外部适配器协议。
- `contracts/` 定义数据对象和请求对象。
- `runner/` 负责统一任务入口。
- `pipelines/` 负责业务流程。
- `algorithms/` 负责计算核心。

## 二十二、你接下来真正应该实现什么

结合你的任务边界，后续最值得优先实现的不是“大而全系统”，而是下面这几类核心能力。

### 22.1 第一优先级：统一任务入口

先做到：

1. 任意一个处理流程都能通过一个统一入口启动。
2. 所有参数都能通过 `JobRequest` 传入。
3. 所有结果都能通过 `JobResult` 返回。

### 22.2 第二优先级：统一数据接口

先做到：

1. 本地数据可读。
2. 预留缓存层能力。
3. 预留懒加载和部分下载模式。
4. 不再让算法代码直接关心绝对路径。

### 22.3 第三优先级：统一日志接口

先做到：

1. 分阶段记录。
2. 结构化事件输出。
3. 支持平台后续接管展示。

### 22.4 第四优先级：统一产品输出

先做到：

1. 输出命名规范一致。
2. 输出位置规范一致。
3. 能生成 `manifest`。

### 22.5 第五优先级：模块化迁移算法

在接口稳定之后，再逐个迁移：

1. SMAP 标准化
2. NDVI 日产品
3. FY 日产品
4. 站点验证产品
5. 反演核心

## 二十三、最终建议

如果把你的任务一句话概括，最准确的表述不是：

“把 MATLAB 代码改成 Python。”

而是：

**“把 MATLAB 科研脚本重构为可被调度系统调用、可被数据层供给、可被日志系统观测、并能稳定输出标准产品的 Python 计算包。”**

因此，当前最合理的方案是：

1. 保留三个强制对外接口：调度、数据源、日志。
2. 增加一个推荐产品接口：产品交付。
3. 把内部代码分成任务入口、pipeline、算法核心、存储发布四层。
4. 所有 A/B/C/D 模块都走统一任务接口，而不是继续脚本式单独运行。

这套方案既不会越界去做别人的调度系统，也能保证你后面转换出来的 Python 代码真正适合接入 WebGIS 平台。

## 二十四、在线核实参考来源

以下公开来源用于核实数据的时间序列属性、多源属性及时间/空间分辨率：

- VNP13C1 官方数据页：<https://www.earthdata.nasa.gov/data/catalog/lpcloud-vnp13c1-001>
- VIIRS 产品表：<https://hodari.ece.arizona.edu/VIIRS_ProductTable.php>
- MOD13C1 官方数据页：<https://www.earthdata.nasa.gov/data/catalog/lpcloud-mod13c1-061>
- MODIS VI 产品说明：<https://modis.gsfc.nasa.gov/data/dataprod/mod13.php>
- SMAP SPL3SMP_E 官方数据页：<https://nsidc.org/data/spl3smp_e/versions/6>
- SMAP 官方任务介绍：<https://science.nasa.gov/science-research/earth-science/a-decade-of-global-water-cycle-monitoring-nasa-soil-moisture-active-passive-mission/>
- FY-3D 卫星信息：<https://space.oscar.wmo.int/satellites/view/fy_3d>
- FY-3 系列英文介绍：<http://www.cma.gov.cn/en2014/20150311/20210702/2021070205/202204/t20220425_4785028.html>
- FY-3 MWRI 仪器说明：<http://satellite.nsmc.org.cn/PortalSite/StaticContent/DeviceIntro_FY3_MWRI.aspx>
- ISMN 数据结构说明：<https://ismn.earth/en/data/ceop-standard/>
- ISMN 网络页示例：<https://ismn.earth/en/networks/?id=COSMOS>
- 中国土壤水分观测网络公开数据描述：<https://www.nature.com/articles/s41597-023-02234-8>
- 对应数据页：<https://figshare.com/articles/dataset/Chinese_Soil_Moisture_Observation_Network_and_Time_Series_Data_Set/21302955>
