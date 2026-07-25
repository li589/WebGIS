# 缓存迁移与数据集成计划

## Summary

双轨计划：(1) 将所有缓存/临时/产物路径从 D 盘迁移至 I 盘，解决磁盘空间危机（D 盘仅剩 20.2GB）；(2) 完成数据移动、集成远端数据源，为 `omega_sf_fenkuai.m` 算法工作流的全链路跑通做准备。

## Current State Analysis

### 磁盘空间
| 盘符 | 已用 | 可用 | 总计 |
|------|------|------|------|
| D | 933.6 GB | 20.2 GB | 953.9 GB |
| I | 2169.9 GB | 624.2 GB | 2794.1 GB |

### D 盘 `.data` 目录占用（共 ~1.85 GB）
| 子目录 | 大小 | 文件数 |
|--------|------|--------|
| artifacts | 678.8 MB | 2110 |
| cache | 235.0 MB | 968 |
| workflow_state | 336.3 MB | 19 |
| workflow_state_snapshots | 332.3 MB | 35 |
| python_provider | 50.3 MB | 87 |
| logs | 108.0 MB | 30 |
| 其他验证/测试目录 | ~0.1 MB | — |

### 当前缓存/临时路径配置（`config.py` 默认值 → 均在 D 盘）
| 配置项 | 环境变量 | 默认值 | 当前 .env 设置 |
|--------|---------|--------|----------------|
| cache_dir | `BACKEND_CACHE_DIR` | `BACKEND_ROOT/.data/cache` | **未设置（D 盘）** |
| workflow_state_dir | `BACKEND_WORKFLOW_STATE_DIR` | `BACKEND_ROOT/.data/workflow_state` | **未设置（D 盘）** |
| log_dir | `BACKEND_LOG_DIR` | `BACKEND_ROOT/.data/logs` | **未设置（D 盘）** |
| result_artifact_dir | `BACKEND_RESULT_ARTIFACT_DIR` | `BACKEND_ROOT/.data/artifacts` | **未设置（D 盘）** |
| python_provider_workspace | `BACKEND_PYTHON_PROVIDER_WORKSPACE` | `BACKEND_ROOT/.data/python_provider` | **未设置（D 盘）** |
| gee_local_storage_root | `BACKEND_GEE_LOCAL_STORAGE_ROOT` | `BACKEND_ROOT/.data/gee` | **未设置（D 盘）** |
| gee_credentials_db_path | `BACKEND_GEE_CREDENTIALS_DB_PATH` | `BACKEND_ROOT/.data/workflow_state/gee_credentials.sqlite3` | **未设置（D 盘）** |
| data_root | `BACKEND_DATA_ROOT` | `""` | `I:/Geograph_DataSet` ✓ |
| output_root | `BACKEND_OUTPUT_ROOT` | `""` | **未设置** |

### I 盘数据目录状态（12 个顶层目录已建立，但多数为空）
| 目录 | 大小 | 文件数 | 状态 |
|------|------|--------|------|
| Station_Observation | 16.0 GB | 317,288 | 有数据（ISD-Lite 历史数据） |
| Admin_Boundary | 0.3 GB | 212 | 有数据（shapefile） |
| Ecological_Vegetation | 0.3 GB | 10 | 仅 .gitkeep + 少量 zip |
| Inversion_Results | 0.2 GB | 25 | 有 .mat 反演结果 |
| ProjectOutput | 0.1 GB | 603 | 有 SMAP 处理输出 |
| 其他 7 个目录 | <0.1 GB | <12 | **仅 .gitkeep（数据未到位）** |

### 算法迁移现状
- `omega_sf_fenkuai.m`（116KB）：主算法，含 SF 反推、NDVI 双模式、Tau 双模式、分片并行等
- Python 算法包已存在于两处：
  - `Code/algorithms/providers/Python/`（项目内，有 `omega_avg_daily` 等模块）
  - `D:\Workspace\mat2py\Python/`（独立包，有完整的 runner/service/workflow 层）
- `FY3B.py` 和 `FY3dfinalfinal.py`：FY-3B/3D 亮温预处理脚本，同时存在于两处 Matlab 目录中
- Excel 配置文件定义了 3 类路径：输入数据（4 项）、辅助输入数据（9 项）、输出（4 项），全部指向服务器路径

### 服务器数据路径映射（来自 Excel + Matlab 代码）
| 数据类型 | 服务器路径 | 本地目标路径（I 盘） |
|---------|-----------|-------------------|
| FY-3D 亮温 | `/public/shared_data/Chenhaojun/FY3D_output/matfinalfinal/` | `Soil_Moisture/FY3D/` |
| FY-3B 亮温 | `/public/shared_data/Chenhaojun/FY3Bmat/` | `Soil_Moisture/FY3B/` |
| SMAP 逐日 | `/public/shared_data/Chenhaojun/DDCAfuxian/DDCAdata/SMAPdata/MAT/` | `Soil_Moisture/SMAP_Origin_Data/` |
| NDVI 逐日 | `/public/shared_data/Chenhaojun/DDCAfuxian/DDCAdata/VNP13C1002/4.Daily/` | `Ecological_Vegetation/NDVI/daily/` |
| NDVI 气候态 | `/public/shared_data/Chenhaojun/DDCAfuxian/DDCAdata/SMAP_ancillary/NDVI_clim/` | `Ecological_Vegetation/NDVI/climatology/` |
| 辅助数据 | `/public/shared_data/Chenhaojun/DDCAfuxian/DDCAdata/SMAP_ancillary/` | `Soil_Moisture/SMAP_Auxiliary_Data/` |
| NDVI 极值 | `/public/shared_data/Chenhaojun/FYdata/VNP13C1002/5.MM/daily/1525/VI_v_qa.mat` | `Ecological_Vegetation/NDVI/VI_v_qa.mat` |
| DDCA SM | `/share/home/user03/Chenhaojun/YH/SM/` | `Soil_Moisture/DDCA/SM/` |
| GLDAS 温度 | `/share/home/user03/Chenhaojun/GLDASmat/` | `Meteorological/Weather/GLDAS/` |
| h 年文件 | `/share/home/user03/Chenhaojun/YH/H/` | `Soil_Moisture/DDCA/H/` |

---

## Phase 1: 缓存/临时路径迁移（D→I 盘）

### 1.1 创建 I 盘目录结构
在 `I:\Geograph_DataSet\` 下创建 `_runtime` 目录作为所有运行时缓存的根：
```
I:\Geograph_DataSet\_runtime\
├── cache\              # 通用缓存（替代 .data/cache）
├── workflow_state\     # 工作流状态（替代 .data/workflow_state）
├── logs\               # 日志（替代 .data/logs）
├── artifacts\          # 产物（替代 .data/artifacts）
├── python_provider\    # Python 算法工作空间（替代 .data/python_provider）
├── gee\                # GEE 本地存储（替代 .data/gee）
└── materialized\       # 静态数据物化缓存
```

### 1.2 更新 `.env` 文件
在 `Code/backend/.env` 中添加以下环境变量：
```env
# ---- 缓存/临时路径（全部指向 I 盘）----
BACKEND_CACHE_DIR=I:/Geograph_DataSet/_runtime/cache
BACKEND_WORKFLOW_STATE_DIR=I:/Geograph_DataSet/_runtime/workflow_state
BACKEND_LOG_DIR=I:/Geograph_DataSet/_runtime/logs
BACKEND_RESULT_ARTIFACT_DIR=I:/Geograph_DataSet/_runtime/artifacts
BACKEND_PYTHON_PROVIDER_WORKSPACE=I:/Geograph_DataSet/_runtime/python_provider
BACKEND_OUTPUT_ROOT=I:/Geograph_DataSet/ProjectOutput
BACKEND_GEE_LOCAL_STORAGE_ROOT=I:/Geograph_DataSet/_runtime/gee
BACKEND_GEE_CREDENTIALS_DB_PATH=I:/Geograph_DataSet/_runtime/workflow_state/gee_credentials.sqlite3
```

### 1.3 迁移现有 `.data` 内容
使用 robocopy 将 D 盘 `.data` 中的有效数据迁移到 I 盘：
- `artifacts` → `I:\Geograph_DataSet\_runtime\artifacts`（678.8 MB）
- `cache` → `I:\Geograph_DataSet\_runtime\cache`（235.0 MB）
- `workflow_state` → `I:\Geograph_DataSet\_runtime\workflow_state`（336.3 MB）
- `python_provider` → `I:\Geograph_DataSet\_runtime\python_provider`（50.3 MB）
- `logs` → 可选迁移（108.0 MB，历史日志可不清空）
- **不迁移**：各种 `_validation*`、`_test*`、`pytest_tmp` 目录（测试临时文件）

### 1.4 更新 `config.py` 默认值
修改 `Code/backend/app/core/config.py` 中的默认路径常量，使未设置环境变量时也指向 I 盘：
```python
# 旧（D 盘）
DEFAULT_WORKFLOW_STATE_DIR = BACKEND_ROOT / ".data" / "workflow_state"
DEFAULT_LOG_DIR = BACKEND_ROOT / ".data" / "logs"
DEFAULT_ARTIFACT_DIR = BACKEND_ROOT / ".data" / "artifacts"
DEFAULT_CACHE_DIR = BACKEND_ROOT / ".data" / "cache"
DEFAULT_PYTHON_PROVIDER_WORKSPACE = BACKEND_ROOT / ".data" / "python_provider"

# 新（I 盘）
_RUNTIME_ROOT = Path(r"I:\Geograph_DataSet\_runtime")
DEFAULT_WORKFLOW_STATE_DIR = _RUNTIME_ROOT / "workflow_state"
DEFAULT_LOG_DIR = _RUNTIME_ROOT / "logs"
DEFAULT_ARTIFACT_DIR = _RUNTIME_ROOT / "artifacts"
DEFAULT_CACHE_DIR = _RUNTIME_ROOT / "cache"
DEFAULT_PYTHON_PROVIDER_WORKSPACE = _RUNTIME_ROOT / "python_provider"
```

### 1.5 更新 `.env.example`
在 `Code/backend/.env.example` 中添加缓存路径配置说明，保持与 `.env` 一致。

### 1.6 更新 `dataset_config.py` 输出根目录
确认 `BACKEND_OUTPUT_ROOT` 默认值从 `I:\GeoOutput` 改为 `I:\Geograph_DataSet\ProjectOutput`（与 .env 一致）。

---

## Phase 2: 数据路径映射与目录补全

### 2.1 创建缺失的 I 盘数据目录
根据服务器路径映射表，在 I 盘创建对应目录结构：
```powershell
# 在 I:\Geograph_DataSet 下创建缺失目录
$dirs = @(
    'Soil_Moisture\FY3D',
    'Soil_Moisture\FY3B',
    'Soil_Moisture\SMAP_Origin_Data',
    'Soil_Moisture\DDCA\SM',
    'Soil_Moisture\DDCA\H',
    'Soil_Moisture\SMAP_Auxiliary_Data',
    'Ecological_Vegetation\NDVI\daily',
    'Ecological_Vegetation\NDVI\climatology',
    'Meteorological\Weather\GLDAS'
)
```

### 2.2 检查辅助数据位置
任务文档提到辅助数据在 `I:\Geograph_DataSet\Soil_Ecological_Data\Smap_auxiliary_data`（旧路径），但重组脚本已将其移动到 `I:\Geograph_DataSet\Soil_Moisture\SMAP_Auxiliary_Data`。需要：
- 确认 `SMAP_Auxiliary_Data` 目录内容（当前仅 .gitkeep）
- 检查旧路径 `Soil_Ecological_Data\Smap_auxiliary_data` 是否仍存在
- 如果旧路径有数据，移动到新路径

### 2.3 更新 `dataset_config.py` 路径映射
更新 `Code/algorithms/providers/Python/dataset_config.py` 中的 `DATASET_REGISTRY`，确保所有 `relative_path` 与 I 盘 12 类目录结构一致：
- `"SMAP_L3"` → `Soil_Moisture/SMAP`（已正确）
- `"FY_MWRI_HDF"` → `Soil_Moisture/FY_MWRI`（已正确）
- `"ancillary_mat"` → `Soil_Moisture/SMAP_Auxiliary_Data`（需更新，当前指向 `Soil_Moisture/Ancillary`）
- 新增 FY3D/FY3B 逐日数据集定义

### 2.4 更新 `BACKEND_REMOTE_LAYER_DATA_URIS`
更新 `.env` 中的 `BACKEND_REMOTE_LAYER_DATA_URIS`，将 D 盘测试路径替换为 I 盘正式路径，并添加新的数据源映射。

---

## Phase 3: FY3B.py / FY3dfinalfinal.py 处理

### 3.1 依赖分析结论
- `FY3B.py` 和 `FY3dfinalfinal.py` 是 FY-3B/3D 卫星 HDF 亮温数据的预处理脚本
- 使用 GDAL 进行 geolocation、拼接、重投影，输出 NetCDF/HDF5
- 它们不是工作流直接依赖（没有在 backend 代码中被 import）
- 但它们处理的逻辑（HDF→GeoTIFF→MAT 转换）是算法流水线的前置步骤
- Python 算法包中已有 `ingest/fy.py` 和 `algorithms/fy.py`，但功能不完全覆盖

### 3.2 处理方案
1. **不删除**这两个文件（包含有效的 GDAL 预处理逻辑）
2. **合并到** `Code/algorithms/providers/Python/ingest/fy_preprocess.py`（新文件）
3. 从两个脚本中提取公共逻辑：
   - `geoloc_hdf()` → 通用 HDF geolocation 函数
   - `merge_allto_tif()` → 日内拼接函数
   - `merge_day()` → 多通道合并函数
4. 参数化：将硬编码路径（`FY_folder`、`output_root`）改为通过函数参数传入
5. 更新 `ingest/fy.py` 引用新的预处理模块
6. 从 Matlab 目录中移除这两个 .py 文件（保留 .m 文件不动）

---

## Phase 4: 算法迁移准备（omega_sf_fenkuai.m → Python）

### 4.1 Matlab 算法结构分析
`omega_sf_fenkuai.m` 包含以下核心模块：
1. **配置系统**：CFG 结构体，含 50+ 参数（日期范围、数据路径、SF 模式、NDVI 模式、Tau 模式等）
2. **数据加载**：SMAP/FY 亮温、NDVI（daily/climatology）、辅助数据（IGBP/Albedo/B/BD/CF/H/SF）
3. **SF 反推**：两种模式（STATIC / INVERTED_DAILY），两种公式（POINT1 / NDVIMIN）
4. **Tau 计算**：VWC2 双模式（NDVIMIN / POINT1）
5. **温度方案**：单温度（ORIG_TS）/ 双温度（DUAL，GLDAS 匹配）
6. **亮温匹配**：FY-3B/3D bias/cdf 匹配
7. **反演核心**：omega → SM/VOD 反演，支持分片并行
8. **输出**：总结果 MAT、block_mat、NDVI DOY 缓存

### 4.2 Python 现有模块映射
| Matlab 模块 | Python 已有模块 | 缺口 |
|------------|----------------|------|
| 配置系统 | `contracts/modes.py`（RetrievalMode, DualTgMode） | 缺少完整 CFG 结构 |
| SMAP 加载 | `ingest/smap.py` | 基本可用 |
| FY 加载 | `ingest/fy.py` | 需合并 FY3B.py 逻辑 |
| NDVI 加载 | `ingest/ndvi.py` + `algorithms/ndvi.py` | 缺 DOY 气候态逻辑 |
| Tau/物理 | `algorithms/physics.py` + `algorithms/omega.py` | 缺 SF 反推逻辑 |
| 反演 | `algorithms/inversion.py` + `algorithms/block_inversion.py` | 基本可用 |
| 辅助数据 | `dataset_config.py`（ancillary_mat） | 路径需更新 |
| 分片并行 | `algorithms/_parallel.py` | 已有 |
| 输出 | `publish/` + `pipelines/omega_block_products.py` | 基本可用 |

### 4.3 迁移策略
采用**增量迁移**而非一次性重写：
1. 先确保数据源可访问（Phase 2 + Phase 5）
2. 补全 SF 反推逻辑（`algorithms/omega.py` 中新增 `compute_sf_inverted_daily()`）
3. 补全 NDVI DOY 气候态加载（`ingest/ndvi.py` 中新增 `load_ndvi_climatology()`）
4. 补全 GLDAS 温度匹配（`ingest/` 中新增 `gldas.py`）
5. 创建 `modules/omega_sf.py`（新模块），编排完整算法流水线
6. 注册到 `modules/registry.py`

### 4.4 本计划范围
本计划仅覆盖**迁移准备**（数据源到位 + 模块缺口识别 + FY 预处理合并）。完整算法迁移需在数据源可用后单独规划。

---

## Phase 5: 远端数据源集成

### 5.1 SSH 服务器访问
根据任务文档，服务器访问有三条路径：
1. **直连**（校园网）：`ssh likr6008@172.16.98.184 -p 22`（需 SSH key）
2. **Cloudflare 隧道**：`ssh -p 2222 likr6008@127.0.0.1 -i ~/.ssh/seahpc_key`（需先启动 `cloudflared access tcp`）
3. **跳板机桥接**：`ssh win11-lab` → `ssh -i <key> likr6008@172.16.98.184 -p 22`

### 5.2 数据同步脚本
创建 `Tools/sync_server_data.py`：
- 通过 SSH 连接服务器
- 扫描服务器数据目录（`/public/shared_data/Chenhaojun/`）
- 按日期范围下载 .mat 文件到 I 盘对应目录
- 支持增量同步（跳过已存在文件）
- 支持 `--dry-run` 预览模式

### 5.3 FileBrowser 远端数据
两个 FileBrowser 隧道：
- `https://nasfile.personaltunnel.dpdns.org/` → NAS（Z 盘）
- `https://win11file.personaltunnel.dpdns.org/` → Win11（E 盘）
- 账号：user / remotefangwen123
- 已有 `Tools/remote_data_scanner.py` 可复用

### 5.4 NSIDC SMAP 下载
- 数据源：`https://nsidc.org/data/spl3smp_e/versions/6`
- Earthdata 账号：Rejoyce / Diandian143
- 需创建 `Tools/download_smap_nsidc.py` 脚本
- 使用 `earthaccess` 或 `requests` 库下载
- 下载目标：`I:\Geograph_DataSet\Soil_Moisture\SMAP\`

### 5.5 路径配置统一
将所有远端数据源路径配置到 `BACKEND_REMOTE_LAYER_DATA_URIS`，使工作流可自动解析：
```json
{
  "omega_sf": {
    "fy3d_folder": ["I:/Geograph_DataSet/Soil_Moisture/FY3D"],
    "fy3b_folder": ["I:/Geograph_DataSet/Soil_Moisture/FY3B"],
    "smap_folder": ["I:/Geograph_DataSet/Soil_Moisture/SMAP_Origin_Data"],
    "ndvi_folder": ["I:/Geograph_DataSet/Ecological_Vegetation/NDVI/daily"],
    "ndvi_clim_folder": ["I:/Geograph_DataSet/Ecological_Vegetation/NDVI/climatology"],
    "anc_root": ["I:/Geograph_DataSet/Soil_Moisture/SMAP_Auxiliary_Data"],
    "gldas_mat_folder": ["I:/Geograph_DataSet/Meteorological/Weather/GLDAS"],
    "ddca_sm_folder": ["I:/Geograph_DataSet/Soil_Moisture/DDCA/SM"],
    "h_year_folder": ["I:/Geograph_DataSet/Soil_Moisture/DDCA/H"]
  }
}
```

---

## Assumptions & Decisions

### 假设
1. I 盘（外接 HDD）在系统运行期间保持连接
2. Cloudflare 隧道在需要时可手动启动（非 24/7 常驻）
3. 服务器 SSH key 在 2026-08-23 前有效
4. `omega_sf_fenkuai.m` 的完整迁移可分阶段进行，本计划仅覆盖前置准备

### 决策
1. **缓存根目录**：选择 `I:\Geograph_DataSet\_runtime\` 而非 `I:\GeoOutput\`，与数据目录同盘但逻辑隔离
2. **不删除 D 盘 `.data`**：迁移后保留原目录作为备份，仅停止写入；后续确认无问题后可手动清理
3. **FY3B.py/FY3dfinalfinal.py**：合并为 `ingest/fy_preprocess.py`，不直接删除原文件
4. **算法迁移**：采用增量迁移策略，先补数据源再补代码，不一次性重写
5. **配置方式**：优先通过 `.env` 环境变量配置路径，`config.py` 默认值作为 fallback

---

## Verification Steps

### Phase 1 验证
1. 确认 `.env` 中所有路径变量指向 I 盘
2. 运行 `python launch.py start fastapi`，确认服务正常启动
3. 检查 `I:\Geograph_DataSet\_runtime\` 下各目录已创建且有写入权限
4. 执行一个简单工作流，确认产物写入 I 盘而非 D 盘
5. 运行 `pytest tests/test_config_security.py -q` 确认配置正确

### Phase 2 验证
1. 确认所有 I 盘数据目录已创建
2. 运行 `python -c "from dataset_config import list_available_datasets; print(list_available_datasets())"` 确认路径映射
3. 检查 `BACKEND_REMOTE_LAYER_DATA_URIS` JSON 可被正确解析

### Phase 3 验证
1. 确认 `ingest/fy_preprocess.py` 可正常 import
2. 运行 `pytest tests/ -k fy -q` 确认 FY 相关测试通过
3. 确认 Matlab 目录中已无 .py 文件

### Phase 5 验证
1. 测试 SSH 连接：`ssh -p 2222 likr6008@127.0.0.1 -i ~/.ssh/seahpc_key`
2. 测试 FileBrowser API：`curl -H "User-Agent: Mozilla" https://nasfile.personaltunnel.dpdns.org/api/login`
3. 运行数据同步脚本 `--dry-run` 模式确认路径映射正确
