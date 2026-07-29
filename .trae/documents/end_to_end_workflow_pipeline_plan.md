# 端到端工作流流水线实施计划

## 概述

将 `omega_sf_fenkuai.m`（116KB Matlab SF 块反演算法）完整迁移为 Python 工作流模块，集成远程数据下载/同步节点，构建端到端工作流种子（下载→预处理→反演→3 图层展示），并完善前端触发机制（下载节点参数 UI、一键流水线入口、运行进度与三图层自动生成）。

## 现状分析

### 已有基础设施
- **工作流主链**：`/workflow-runs` 端点 + Celery 执行 + python_provider_bridge + 事件轮询 + jobLayer 机制，均已运行
- **前端编辑器**：LiteGraph 画布 + WorkflowInspector 属性检查器 + WorkflowRunDialog 运行目标选择 + WorkflowStatusPanel 状态面板
- **已注册算法模块**：`omega_avg_daily`（D2 avg-omega）、`block_inversion`（块状 DH/DDCA）、`omega_block`（D1）、`ndvi_daily`、`smap_daily`、`fy_daily` 等
- **已注册数据访问节点**：`remote_fetch`、`http_open_data`、`archive_extract`、`variable_extract`、`format_convert`
- **已有算法库**：`physics.py`（Mironov 介电、Fresnel 反射、VWC/tau）、`inversion.py`（DDCA 像元/网格反演、tb_model）、`omega_avg.py`（DOY 气候态）、`block_inversion.py`（块反演 + 并行）、`ndvi.py`（SG 插值、DOY 气候态）、`_parallel.py`（ProcessPoolExecutor 并行工具）
- **已有工具脚本**：`Tools/sync_server_data.py`（SSH/SFTP 增量同步）、`Tools/download_smap_nsidc.py`（NSIDC SMAP 下载）——均为独立 CLI，未集成进工作流
- **已有预处理模块**：`ingest/fy_preprocess.py`（FY-3B/3D MWRI 亮温预处理，已合并但未注册为节点）
- **已有工作流种子**：`omega_avg_daily_smap_single.json`、`open_data_nsidc_smap_sample.json`（下载→解压→提取→转换端到端示例）

### 关键缺口
1. `omega_sf_fenkuai.m` 的 SF 倒推 + 多模式切换逻辑在 Python 侧无等价实现
2. `sync_server_data.py` / `download_smap_nsidc.py` 未封装为工作流节点
3. `fy_preprocess.py` 未注册为工作流节点
4. 前端下载节点无专用参数表单（需手编 JSON）
5. 无端到端"一键流水线"入口
6. 工作流多输出（3 图层）自动生成机制未实现
7. 23 个 GIS/统计/可视化模块为 Stub（本次不涉及）

## 实施方案

### Part A：omega_sf_fenkuai 算法迁移（核心）

#### A1. `algorithms/omega_sf.py` — 核心算法逻辑

**文件**：`Code/algorithms/providers/Python/algorithms/omega_sf.py`

**职责**：实现 SF 块反演算法的核心逻辑，复用已有 physics/inversion/omega_avg/ndvi 模块。

**关键内容**：

```python
@dataclass(frozen=True, slots=True)
class OmegaSfConfig:
    """omega_sf_fenkuai 配置，镜像 Matlab CFG 结构。"""
    # 数据源开关
    tb_source: str = "FY"           # "FY" | "SMAP"
    sm_source: str = "SMAP"         # "SMAP" | "ISMN" | "DDCA"
    fy_platform: str = "3D"         # "3D" | "3B"
    temp_scheme: str = "ORIG_TS"    # "ORIG_TS" | "DUAL"
    run_domain: str = "GLOBAL"      # "ISMN" | "GLOBAL"

    # SF 方案
    sf_mode: str = "INVERTED_DAILY" # "STATIC" | "INVERTED_DAILY"
    sf_invert_mode: str = "POINT1"  # "POINT1" | "NDVIMIN"

    # NDVI 方案
    ndvi_mode: str = "DOY_CLIM"     # "DAILY_FILE" | "DOY_CLIM"
    tau_vwc2_mode: str = "POINT1"   # "NDVIMIN" | "POINT1"

    # FY3B→FY3D 匹配
    match_enable: bool = True
    match_method: str = "bias"      # "none" | "bias" | "cdf"

    # OMEGA 固定模式
    omega_fixed_mode: str = "PFT"   # "PFT" | "PIXEL"

    # SMAP h/Q 模式
    smap_hq_mode: str = "LOWTAU"    # "LOWTAU" | "YEARFILE_HQFIX"

    # 反演参数
    block_days: int = 8
    tau_rel_frac: float = 0.05
    kmin: int = 2
    alpha0: float = 0.1771
    lambda_alpha: float = 1.0
    bounds_h: tuple[float, float] = (0.0, 3.0)
    bounds_alpha: tuple[float, float] = (0.05, 0.35)
    omega0: float = 0.12
    bounds_omega: tuple[float, float] = (0.0, 1.0)
    lambda_tau: float = 20.0
    freq_ghz: float = 10.65  # FY=10.65, SMAP=1.41

    # 并行
    enable_parallel: bool = True
    pixel_chunk_size: int = 200000

    # 日期范围
    start_date: str = "20250101"
    end_date: str = "20251231"

    # QC
    qc_enable: bool = True
    qc_nmin: int = 3
```

**核心函数**（复用已有模块）：

| 函数 | 职责 | 复用 |
|------|------|------|
| `build_omega_sf_config(params)` | 从 algorithm_params 构建配置 | — |
| `invert_sf_daily(smap_data, ndvi_clim, config)` | SF 逐日反推（INVERTED_DAILY 模式） | `physics.vwc_from_ndvi` |
| `compute_sf_static(anc_data, config)` | 静态 SF 加载 | `ingest.mat_bundle` |
| `match_fy3b_to_fy3d(fy3b_tb, fy3d_tb, config)` | FY3B→FY3D 偏差/CDF 匹配 | 新实现 |
| `execute_omega_sf_block(...)` | 单块 DDCA + OMEGA 识别 + h/alpha + SM/VOD | `inversion.ddca_retrieve_grid`、`physics.*` |
| `retrieve_omega_sf_daily(...)` | 逐日反演主循环（外层 chunk + 内层 block） | `_parallel._run_chunks_parallel` |
| `build_omega_pft_maps(block_results)` | 从块结果生成 PFT/PIXEL omega 图 | 新实现 |

**SF 倒推核心逻辑**（Matlab L30-36 对应）：
- `SF_MODE="STATIC"`：直接读 `anc_root/SF.mat` 中的 `SF_smap`
- `SF_MODE="INVERTED_DAILY"`：
  - `SF_INVERT_MODE="POINT1"`：`SF = (NDVI_ref - 0.1) / 0.9`，其中 NDVI_ref 来自 NDVI_clim
  - `SF_INVERT_MODE="NDVIMIN"`：`SF = (NDVI_ref - NDVI_clim_min) / (1 - NDVI_clim_min)`
  - 基于 SMAP vwc + NDVI_clim 逐日反推

**FY3B→FY3D 匹配逻辑**（Matlab L78-85 对应）：
- `MATCH_METHOD="bias"`：计算 FY3B 与 FY3D 亮温偏差，校正 FY3B
- `MATCH_METHOD="cdf"`：CDF 匹配，将 FY3B 分布映射到 FY3D
- 匹配窗口：`match_start_date` ~ `match_end_date`，最小有效样本数 `match_min_valid_n`

**块反演主循环**（Matlab L603-764 对应）：
1. 按 `block_days`（默认 8 天）划分时间块
2. 每块内：预读 TB/SMAP/NDVI/辅助数据 → 构建时间-像元矩阵
3. 对每个像元：DDCA 反演 + OMEGA 识别（`omega0` 初始值 + `bounds_omega` 约束）
4. 提取 h/alpha map
5. 逐日 SM/VOD 反演
6. 输出块级 OMEGA_grid + 逐日 SM/VOD

**并行策略**：复用 `_parallel._run_chunks_parallel`（ProcessPoolExecutor + spawn context + 超时保护），chunk 大小 = `pixel_chunk_size`。

#### A2. `modules/omega_sf_fenkuai.py` — 工作流模块注册

**文件**：`Code/algorithms/providers/Python/modules/omega_sf_fenkuai.py`

**职责**：将核心算法注册为工作流节点，定义输入端口、数据源键映射、3 个输出产品。

```python
@register_module_decorator(name="omega_sf_fenkuai", aliases=["omega_sf_fenkuai_pipeline"])
class OmegaSfFenkuaiModule(BaseModule):
    name = "omega_sf_fenkuai"
    description = "SF block inversion with OMEGA identification (migrated from Matlab omega_sf_fenkuai.m)"
    mode_required_inputs = {
        "omega_sf_fenkuai": (
            "smap_folder",       # SMAP 逐日 .mat
            "anc_root",          # 辅助库目录
            "ndvi_folder",       # NDVI 逐日 .mat（DAILY_FILE 模式）
            "ndvi_clim_folder",  # NDVI DOY 气候态 .mat（DOY_CLIM 模式）
        ),
    }
    input_ports = [
        PortSpec(name="datasource_selection", kind="config", data_class="dict", required=False),
        PortSpec(name="algorithm_params", kind="config", data_class="dict", required=False),
        PortSpec(name="output_spec_extra", kind="config", data_class="dict", required=False),
    ]
    output_ports = [
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
```

**数据源键映射**（复用 bundles.py + 扩展）：
```python
_OMEGA_SF_DATASOURCE_KEY_MAP = {
    "smap_folder": ("smap_folder", "smap_mat_dir", "smap_data"),
    "fy3d_folder": ("fy3d_folder", "fy3d_mat_dir"),
    "fy3b_folder": ("fy3b_folder", "fy3b_mat_dir"),
    "ndvi_folder": ("ndvi_folder", "ndvi_mat_dir"),
    "ndvi_clim_folder": ("ndvi_clim_folder", "ndvi_clim_dir"),
    "anc_root": ("anc_root", "ancillary_mat"),
    "gldas_mat_folder": ("gldas_mat_folder", "gldas_dir"),
    "ddca_sm_folder": ("ddca_sm_folder", "ddca_sm_dir"),
}
```

**execute() 逻辑**：
1. 解析 datasource_selection（复用 `_resolve_bundle_datasource_selection` + 专有键）
2. 构建 `OmegaSfConfig`
3. 校验必需键（根据 `tb_source`/`sf_mode`/`ndvi_mode` 动态判断）
4. 调用 `retrieve_omega_sf_daily(...)` 执行反演
5. 构建 `ProductManifest`，包含 3 个 `ProductRef`：
   - `SM`（土壤水分）
   - `VOD`（植被光学厚度）
   - `OMEGA`（OMEGA 参数）
6. `main_layers = ["SM", "VOD", "OMEGA"]`

#### A3. `contracts/request_templates.py` — 手动请求模板

**文件**：`Code/algorithms/providers/Python/contracts/request_templates.py`

**原因**：根据 lessons learned，`template_deriver.py` 将 `mode_required_inputs` 键错误放入 `required_algorithm_keys`，导致校验报错。需添加手动模板。

```python
"omega_sf_fenkuai": RequestTemplateSpec(
    module_name="omega_sf_fenkuai",
    required_datasource_keys=("smap_folder", "anc_root"),
    required_algorithm_keys=(),  # 所有 mode_required_inputs 键均为 datasource 路径
    optional_datasource_keys=("fy3d_folder", "fy3b_folder", "ndvi_folder",
                              "ndvi_clim_folder", "gldas_mat_folder", "ddca_sm_folder"),
),
```

---

### Part B：数据下载节点集成

#### B1. SSH/SFTP 同步节点

**文件**：`Code/algorithms/providers/Python/modules/data_access_nodes.py`（新增类）

```python
@register_module_decorator(name="ssh_sync", aliases=["remote_ssh_sync"])
class SshSyncModule(BaseModule):
    """通过 SSH/SFTP 从远程服务器增量同步数据到本地。"""
    name = "ssh_sync"
    description = "Incremental SSH/SFTP sync from remote server (wraps Tools/sync_server_data.py logic)"
```

**execute() 逻辑**：
1. 从 inputs/params 解析：`server`（win11/nas/hpc）、`remote_path`、`local_path`、`date_range`、`file_filter`
2. 解析 SSH 连接配置（从环境变量 `CGDA_SSH_*` 或 params）：
   - hpc: `127.0.0.1:2222`，key=`~/.ssh/seahpc_key`，user=`likr6008`
   - win11: `win11-lab`（cloudflare tunnel），user=`qiujianqiu`
   - nas: FileBrowser API（`nasfile.personaltunnel.dpdns.org`）
3. 调用同步逻辑（从 `Tools/sync_server_data.py` 提取核心函数，不依赖 subprocess）
4. 输出 `ProductManifest`，`uri` = 本地落盘路径

**关键**：将 `Tools/sync_server_data.py` 中的 `sync_dataset()`、`_sftp_list_dir()`、`_sftp_download_file()` 等函数提取为可 import 的模块 `ingest/remote_sync.py`，供节点调用。

#### B2. NSIDC SMAP 下载节点

**文件**：`Code/algorithms/providers/Python/modules/data_access_nodes.py`（新增类）

```python
@register_module_decorator(name="nsidc_smap_download", aliases=["nsidc_download"])
class NsidcSmapDownloadModule(BaseModule):
    """从 NASA NSIDC 下载 SMAP L3 SPL3SMP_E 数据。"""
    name = "nsidc_smap_download"
```

**execute() 逻辑**：
1. 从 inputs/params 解析：`start_date`、`end_date`、`local_path`、`version`（默认 6）
2. 使用 `earthaccess` 认证（凭据从环境变量 `EARTHDATA_USER` / `EARTHDATA_PASSWORD`）
3. 调用 CMR 查询 + HTTP 下载（从 `Tools/download_smap_nsidc.py` 提取核心函数）
4. 输出 `ProductManifest`，`uri` = 本地落盘目录

**关键**：将 `Tools/download_smap_nsidc.py` 中的 `download_smap_range()`、`_cmr_search()`、`_download_granule()` 提取为 `ingest/nsidc_download.py`。

#### B3. FY 预处理节点注册

**文件**：`Code/algorithms/providers/Python/modules/fy_preprocess_node.py`（新建）

```python
@register_module_decorator(name="fy_preprocess", aliases=["fy_hdf_preprocess"])
class FyPreprocessModule(BaseModule):
    """FY-3B/3D MWRI HDF 亮温预处理（geoloc → 拼接 → 多通道合并 → 重投影）。"""
    name = "fy_preprocess"
```

**execute() 逻辑**：
1. 从 inputs/params 解析：`input_dir`、`output_dir`、`satellite`（FY3B/FY3D）、`start_date`、`end_date`、`band_ids`、`orbit_mode`
2. 构建 `FySatelliteConfig.for_fy3d()` 或 `for_fy3b()`
3. 调用 `FyPreprocessor(config).process_date_range(...)`
4. 输出 `ProductManifest`，`uri` = 输出目录

---

### Part C：端到端工作流种子

#### C1. `omega_sf_fenkuai_fy_single.json`

**文件**：`Code/backend/workflow_seeds/system/omega_sf_fenkuai_fy_single.json`

**节点链路**：
```
[data_source: SMAP]     → [data_source: FY3D]     → [data_source: NDVI]
        ↓                       ↓                       ↓
[ssh_sync: SMAP]        [ssh_sync: FY3D]        [ssh_sync: NDVI]
        ↓                       ↓                       ↓
[data_source: anc_root] → [ssh_sync: ancillary] → [data_source: ndvi_clim]
                                                        ↓
                                                [ssh_sync: ndvi_clim]
        ↘                       ↓                       ↙
                    [algorithm/omega_sf_fenkuai]
                     ↓          ↓          ↓
              [output_map_layer: SM]  [output_map_layer: VOD]  [output_map_layer: OMEGA]
```

**algorithm_params**（镜像 Matlab CFG 默认值）：
```json
{
  "tb_source": "FY",
  "fy_platform": "3D",
  "sm_source": "SMAP",
  "sf_mode": "INVERTED_DAILY",
  "sf_invert_mode": "POINT1",
  "ndvi_mode": "DOY_CLIM",
  "tau_vwc2_mode": "POINT1",
  "temp_scheme": "ORIG_TS",
  "omega_fixed_mode": "PFT",
  "match_enable": true,
  "match_method": "bias",
  "block_days": 8,
  "start_date": "20250101",
  "end_date": "20251231",
  "enable_parallel": true,
  "pixel_chunk_size": 200000
}
```

**3 个 output_map_layer 节点**：分别对应 SM / VOD / OMEGA，自动渲染为 MapLibre 图层。

#### C2. `omega_sf_fenkuai_smap_single.json`

**文件**：`Code/backend/workflow_seeds/system/omega_sf_fenkuai_smap_single.json`

与 C1 类似，但 `tb_source="SMAP"`，无需 FY3D/FY3B 节点，增加 `nsidc_smap_download` 节点替代 `ssh_sync: SMAP`。

---

### Part D：前端完善

#### D1. 下载节点参数 UI

**文件**：
- `Code/frontend/src/components/workflow/WorkflowInspector.vue`（增强）
- `Code/frontend/src/components/workflow/node-forms/`（新建目录）
  - `SshSyncForm.vue`
  - `NsidcDownloadForm.vue`
  - `FyPreprocessForm.vue`

**实现**：
1. `WorkflowInspector.vue` 检测当前选中节点的 `module_name`，若为 `ssh_sync` / `nsidc_smap_download` / `fy_preprocess`，渲染专用表单组件替代通用 JSON 编辑器
2. `SshSyncForm.vue`：
   - 服务器选择下拉（HPC / Win11 / NAS），自动填充连接配置
   - 远程路径输入（带 FileBrowser 浏览按钮，调用 `/api/remote/list`）
   - 本地路径输入（默认 `I:\Geograph_DataSet\...`）
   - 日期范围选择器（el-date-picker）
   - 文件过滤多选（.mat / .hdf5 / .nc / .tif）
3. `NsidcDownloadForm.vue`：
   - 日期范围选择器
   - 版本选择（默认 V6）
   - 本地路径输入
   - Earthdata 凭据状态指示（从 `/api/config/earthdata` 获取）
4. `FyPreprocessForm.vue`：
   - 卫星选择（FY-3B / FY-3D）
   - 输入目录、输出目录
   - 日期范围、波段选择、轨道模式

#### D2. 一键流水线入口

**文件**：
- `Code/frontend/src/components/workflow/PipelineLauncher.vue`（新建）
- `Code/frontend/src/components/workflow/WorkflowEditorPanel.vue`（增加入口按钮）

**实现**：
1. 在 `WorkflowEditorPanel.vue` 顶部工具栏增加"流水线模板"按钮，点击弹出 `PipelineLauncher.vue`
2. `PipelineLauncher.vue` 展示预置端到端种子列表（从 `/api/workflow-definitions?tag=pipeline` 获取）：
   - "FY-3D SF 块反演全流程"（omega_sf_fenkuai_fy_single）
   - "SMAP SF 块反演全流程"（omega_sf_fenkuai_smap_single）
3. 每个模板卡片展示节点链路缩略图 + 参数表单（数据范围选择、数据源切换）
4. 用户选择数据范围（start_date / end_date）和数据源（本地 / SSH 同步 / NSIDC 下载）后，点击"启动"
5. 调用 `compileWorkflowGraph` 编译种子为 workflow_definition → `POST /workflow-runs` 提交
6. 自动关闭面板，打开 `WorkflowStatusPanel`

#### D3. 运行进度与结果增强

**文件**：
- `Code/frontend/src/components/workflow/WorkflowStatusPanel.vue`（增强）
- `Code/frontend/src/stores/layers/index.ts`（增强 `applyWorkflowEventsToJobLayer`）

**实现**：
1. **下载阶段反馈**：事件类型 `download_progress` / `download_complete`，在状态面板中显示下载进度条（已下载/总文件数、已下载字节）
2. **多输出自动叠加**：当 `/workflow-runs/{run_id}/view` 返回的 `result_refs` 含多个 `map_layer` 类型时：
   - 自动为每个 `map_layer` 创建独立 jobLayer
   - 按顺序叠加到地图（SM 底层 → VOD 中层 → OMEGA 顶层）
   - 在图层面板中分组显示（"omega_sf_fenkuai 输出"分组下含 3 个图层）
3. **结果对比展示**：在 `WorkflowStatusPanel` 增加"结果对比"标签页，支持选择 2 个输出图层做滑动对比

#### D4. 三图层自动生成机制

**文件**：
- `Code/frontend/src/components/workflow/WorkflowRunDialog.vue`（增强）
- `Code/backend/app/services/workflow/result_builder.py`（增强，若需要）

**实现**：
1. `WorkflowRunDialog.vue` 检测工作流定义中 `output_map_layer` 节点数量：
   - 单输出：保持现有逻辑（选择默认图层或新建图层）
   - 多输出（如 omega_sf_fenkuai 的 3 个）：显示"自动生成 3 个图层"选项
2. 用户选择"自动生成"后，提交时 `requested_outputs` 包含 3 个 layer_id 占位符
3. 后端 `result_builder` 为每个 `output_map_layer` 节点生成独立 `WorkflowResultReference`（type=`map_layer`）
4. 前端收到 3 个 `result_refs` 后，依次创建 3 个 jobLayer 并叠加

---

### Part E：后端配置与路由补充

#### E1. SSH 连接配置

**文件**：`Code/backend/app/core/config.py` + `Code/backend/.env`

新增配置项：
```python
# SSH 远程同步配置
CGDA_SSH_HPC_HOST: str = "127.0.0.1"
CGDA_SSH_HPC_PORT: int = 2222
CGDA_SSH_HPC_USER: str = "likr6008"
CGDA_SSH_HPC_KEY_PATH: str = "~/.ssh/seahpc_key"

CGDA_SSH_WIN11_ALIAS: str = "win11-lab"
CGDA_SSH_WIN11_USER: str = "qiujianqiu"

# Earthdata 凭据
EARTHDATA_USER: str = ""
EARTHDATA_PASSWORD: str = ""

# FileBrowser 配置
CGDA_FILEBROWSER_NAS_URL: str = "https://nasfile.personaltunnel.dpdns.org"
CGDA_FILEBROWSER_WIN11_URL: str = "https://win11file.personaltunnel.dpdns.org"
CGDA_FILEBROWSER_USER: str = "user"
CGDA_FILEBROWSER_PASSWORD: str = ""
```

#### E2. 远程文件浏览 API

**文件**：`Code/backend/app/api/routers/__init__.py`（注册）+ `Code/backend/app/api/routers/remote_browser_router.py`（新建）

提供 `GET /api/remote/list?server=hpc&path=/public/shared_data/...` 端点，封装 FileBrowser REST API，供前端 `SshSyncForm.vue` 浏览远程目录。

---

### Part F：可重用模块提取

#### F1. `ingest/remote_sync.py`

**文件**：`Code/algorithms/providers/Python/ingest/remote_sync.py`（新建）

从 `Tools/sync_server_data.py` 提取核心函数：
- `sync_dataset(server_config, remote_path, local_path, date_range, file_filter) -> SyncResult`
- `_sftp_list_dir(sftp, path) -> list[RemoteFile]`
- `_sftp_download_file(sftp, remote_path, local_path) -> bool`
- `_filebrowser_list_dir(url, token, path) -> list[RemoteFile]`
- `_filebrowser_download(url, token, path, local_path) -> bool`

#### F2. `ingest/nsidc_download.py`

**文件**：`Code/algorithms/providers/Python/ingest/nsidc_download.py`（新建）

从 `Tools/download_smap_nsidc.py` 提取核心函数：
- `download_smap_range(start_date, end_date, local_dir, version=6) -> DownloadResult`
- `_cmr_search(start_date, end_date, version) -> list[Granule]`
- `_download_granule(url, local_path, auth) -> bool`
- `_earthaccess_login(user, password) -> EarthaccessSession`

---

## 假设与决策

### 假设
1. SSH 密钥 `~/.ssh/seahpc_key` 已配置且有效（2026-08-23 过期）
2. Earthdata 账号 `Rejoyce` / `Diandian143` 可用
3. FileBrowser 隧道 `nasfile.personaltunnel.dpdns.org` 和 `win11file.personaltunnel.dpdns.org` 可达
4. GDAL 可执行文件位于 `C:\OSGeo4W\bin`（fy_preprocess 依赖）
5. 远程服务器数据路径遵循 Excel 配置中的 `/public/shared_data/Chenhaojun/...` 结构
6. 本地数据已整理到 12 类目录结构（`I:\Geograph_DataSet\`）

### 决策
1. **算法迁移策略**：完整迁移 omega_sf_fenkuai.m，支持全部模式（SF_MODE / NDVI_MODE / TAU_VWC2_MODE / TEMP_SCHEME / MATCH_METHOD / OMEGA_FIXED_MODE），复用已有 physics/inversion/omega_avg 模块
2. **下载集成策略**：将 Tools 脚本核心逻辑提取为 `ingest/` 模块，再封装为 data_access_nodes，不通过 subprocess 调用 CLI
3. **前端表单策略**：为下载/预处理节点创建专用 Vue 表单组件，通过 WorkflowInspector 动态渲染，不修改通用 JSON 编辑器
4. **多输出策略**：前端检测 `output_map_layer` 节点数量，多输出时自动生成对应数量 jobLayer；后端 result_builder 逐节点生成 result_ref
5. **工作流种子策略**：创建 FY 和 SMAP 两个端到端种子，节点链路含可选下载节点（用户可选择本地已有数据或远程下载）
6. **配置安全**：SSH 密钥路径和 Earthdata 凭据通过环境变量注入，不硬编码到代码中；FileBrowser 密码存入 `.env`（development 模式可旁路鉴权）

## 验证步骤

### 后端验证
1. **算法模块单测**：
   ```bash
   cd Code/algorithms/providers/Python
   pytest tests/test_omega_sf_config.py tests/test_omega_sf_inversion.py -q
   ```
   验证 `OmegaSfConfig` 构建、SF 倒推逻辑（STATIC/INVERTED_DAILY 两种模式）、FY3B→FY3D 匹配（bias/cdf）

2. **模块注册验证**：
   ```bash
   cd Code/algorithms/providers/Python
   python -c "from modules.registry import MODULE_REGISTRY; assert 'omega_sf_fenkuai' in MODULE_REGISTRY; assert 'ssh_sync' in MODULE_REGISTRY; assert 'nsidc_smap_download' in MODULE_REGISTRY; assert 'fy_preprocess' in MODULE_REGISTRY"
   ```

3. **请求模板验证**：
   ```bash
   cd Code/algorithms/providers/Python
   python -c "from contracts.request_templates import MODULE_REQUEST_TEMPLATES; t = MODULE_REQUEST_TEMPLATES['omega_sf_fenkuai']; assert 'smap_folder' in t.required_datasource_keys"
   ```

4. **工作流编译验证**：
   ```bash
   cd Code/backend
   pytest tests/test_workflow_graph_compiler.py -q
   ```

5. **工作流路由验证**：
   ```bash
   cd Code/backend
   pytest tests/test_workflow_routes.py tests/test_interaction_hub.py tests/test_business_regression.py -q
   ```

6. **端到端 API 验证**：
   ```bash
   python launch.py start fastapi
   # 提交 omega_sf_fenkuai 工作流
   curl -X POST http://127.0.0.1:8000/workflow-runs -H "Content-Type: application/json" -d @workflow_seeds/system/omega_sf_fenkuai_fy_single.json
   # 查询状态
   curl http://127.0.0.1:8000/workflow-runs/{run_id}/view
   ```

### 前端验证
7. **组件单测**：
   ```bash
   cd Code/frontend
   npm run test -- ssh-sync-form nsidc-download-form pipeline-launcher workflow-status-panel workflow-run-dialog
   ```

8. **Lint + Build**：
   ```bash
   cd Code/frontend
   npm run lint && npm run build
   ```

9. **契约检查**：
   ```bash
   cd Code/frontend
   npm run check:openapi
   ```

### 集成验证
10. **端到端流水线**：
    - 启动全栈：`python launch.py start`
    - 前端打开工作流编辑器 → 点击"流水线模板" → 选择"FY-3D SF 块反演全流程"
    - 设置数据范围（如 2025-01-01 ~ 2025-01-31 测试段）
    - 点击"启动" → 观察 WorkflowStatusPanel 下载进度 → 反演进度
    - 验证地图上自动叠加 3 个图层（SM / VOD / OMEGA）

## 当前进度（2026-07-25 更新）

| 部件 | 状态 | 说明 |
|------|------|------|
| 数据整理（12 类目录） | ✅ 完成 | I:\Geograph_DataSet 下 12 类 + _runtime + workflow_definitions |
| Part F1: `ingest/remote_sync.py` | ✅ 完成 | ServerConfig + sync_dataset + SFTP/FileBrowser 双路径 |
| Part F2: `ingest/nsidc_download.py` | ⬜ 待实施 | 从 Tools/download_smap_nsidc.py 提取 |
| Part A1: `algorithms/omega_sf.py` | ⬜ 待实施 | SF 倒推 + FY3B→FY3D 匹配 + 块反演主循环 + PFT/pixel omega |
| Part A2: `modules/omega_sf_fenkuai.py` | ⬜ 待实施 | 工作流模块注册，3 输出（SM/VOD/OMEGA） |
| Part A3: request_templates | ⬜ 待实施 | 手动模板，避免 mode_required_inputs 误判 |
| Part B: 下载节点注册 | ⬜ 待实施 | ssh_sync + nsidc_smap_download + fy_preprocess |
| Part E: 后端配置与路由 | ⬜ 待实施 | config.py + .env + remote_browser_router |
| Part C: 工作流种子 | ⬜ 待实施 | omega_sf_fenkuai_fy_single + smap_single |
| Part D: 前端完善 | ⬜ 待实施 | 下载节点 UI + 一键入口 + 进度增强 + 三图层自动生成 |
| 验证 | ⬜ 待实施 | 后端测试 + 前端测试 + 端到端集成 |

## 实施顺序

1. **Part F2**：提取 `ingest/nsidc_download.py` — 补全可重用模块
2. **Part A**：算法迁移（omega_sf.py + module 注册 + request template）— 核心算法
3. **Part B**：数据下载节点集成（ssh_sync / nsidc_smap_download / fy_preprocess 注册）— 数据获取
4. **Part E**：后端配置与路由补充 — 支撑前端
5. **Part C**：工作流种子创建 — 连接下载→反演→输出
6. **Part D**：前端完善（下载节点 UI → 一键入口 → 进度增强 → 三图层自动生成）— 用户交互
7. **验证**：按上述验证步骤逐项执行
