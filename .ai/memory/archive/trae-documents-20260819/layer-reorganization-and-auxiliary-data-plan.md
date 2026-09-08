# 图层重组、合并条目与辅助数据接入计划

## 概述

本计划涵盖三大类变更：(1) 分析面板开关迁移至设置外观页；(2) 新增多源合并图层条目（历史降水、ERA5 灾害事件、风云/SMAP ω 反演）及现有条目修正（土壤水分→土壤湿度、下拉框宽度）；(3) 图层分组修正（森林覆盖率移入植被相关、景观 SHDI 移入模型输出）与 SMAP 辅助数据图层接入。

## 当前状态分析

### 已完成（上一轮会话）
- `soil-moisture` 合并条目已存在（4 源可选），但名称仍为"土壤水分"
- `check_catalog_drift.py` 的 `FE_ONLY_ALLOWLIST` 已包含 `soil-moisture`
- `AppSelect.vue` 已支持 `block` 属性

### 未完成
1. **开关迁移**：`InfoPanelToolsTab.vue` 仍持有 `showOnMap = ref(true)` 本地状态和 UI 复选框；`settings-local.ts` 未添加持久化字段；`AppearanceSettings.vue` 未添加开关
2. **合并条目缺失**：`precipitation-static`、`era5-hazard-events`、`fy-omega-inversion`、`smap-omega-inversion` 四个合并条目均不存在
3. **土壤水分→土壤湿度**：`catalog.ts` 第 1030 行 `name: '土壤水分'` 未修改
4. **下拉框宽度**：`LayerSidebarLibrary.vue` 多源下拉框未添加 `block` 属性；CSS 缺少 `.source-selector-label .app-select { flex: 1 }`
5. **ω 反演图层后端缺失**：`layer_descriptors.json` 中四个 ω 反演图层缺少 `sub_category: "模型输出"` 和 `presentation` 块；`method-fy-omega-doy-dynamic` 和 `method-fy-omega-doy-avg` 的 `display_name` 仍以 "FY" 开头（需改为"风云卫星"）
6. **森林覆盖率归类**：当前 `category: 'research-group' / subCategory: '辅助数据'`，有 Zenodo DOI（公开数据），应移入 `vegetation`
7. **景观 SHDI 归类**：当前 `subCategory: '辅助数据'`，SHDI 属景观生态学指标非植被指标，应移入 `模型输出`
8. **辅助数据图层**：`I:\Geograph_DataSet\Soil_Moisture\SMAP_Auxiliary_Data` 下 9 个 .mat 文件均未接入

## 变更明细

### 1. 分析面板开关迁移至设置 → 外观 → 地图显示

#### 1.1 `Code/frontend/src/services/settings-local.ts`
- 在 `SettingsUiLocal` 接口中新增 `showAnalysisResultOnMap?: boolean` 字段
- 新增三个函数（参照 `mapDistributionChrome` 模式）：
  - `isShowAnalysisResultOnMapEnabled(): boolean` — 默认 `true`（`!== false`）
  - `setShowAnalysisResultOnMapEnabled(on: boolean): void` — 写入并通知监听器
  - `subscribeShowAnalysisResultOnMap(listener: () => void): () => void` — 订阅变更
- 使用独立 `Set<() => void>` 监听器集合，与 `mapDistributionChrome` 模式一致

#### 1.2 `Code/frontend/src/components/settings/AppearanceSettings.vue`
- 导入 `isShowAnalysisResultOnMapEnabled`、`setShowAnalysisResultOnMapEnabled`、`subscribeShowAnalysisResultOnMap`
- 在"地图显示" section（现有"地图分布淡底"开关下方）新增一个 `toggle-row`：
  - 标签文本：`成功后在地图显示分析结果图层（默认开）`
  - 初始值来自 `isShowAnalysisResultOnMapEnabled()`
  - `onCheckboxChange` 调用 `setShowAnalysisResultOnMapEnabled(checked)`
- `onMounted` 中注册 `subscribeShowAnalysisResultOnMap` 以响应外部变更（可选，保持一致性）

#### 1.3 `Code/frontend/src/components/info-panel/InfoPanelToolsTab.vue`
- 删除 `const showOnMap = ref(true)`（第 36 行）
- 删除模板中的复选框 `<label class="param-row param-row--check">...</label>`（第 358-361 行）
- 在 `onRun()` 中将 `showOnMap: showOnMap.value` 改为 `showOnMap: isShowAnalysisResultOnMapEnabled()`（第 230 行）
- 导入 `isShowAnalysisResultOnMapEnabled` from `settings-local`
- 删除不再使用的 `.param-row--check` CSS 规则

---

### 2. 新增多源合并图层条目

#### 2a. 历史降水（GPCP 月降水 + CMFD 区域降水）

**`catalog.ts`**：
- 在 `gpcp-precip-ts` 条目添加 `mergedInto: 'precipitation-static'`
- 在 `cmfd-precip-cn` 条目添加 `mergedInto: 'precipitation-static'`
- 新增合并条目（放在 climate 分类末尾）：
  ```typescript
  {
    catalogId: 'precipitation-static',
    name: '历史降水',
    category: 'climate',
    metricLabel: '降水',
    metricUnit: 'mm',
    metricPrecision: 1,
    updateLabel: '静态数据',
    sourceLabel: '多源可选',
    accentColor: '#5b8def',
    accentGlow: 'rgba(91, 141, 239, 0.3)',
    chipTone: 'rgba(91, 141, 239, 0.16)',
    sources: [SOURCE_GPCP_TS, SOURCE_CMFD_PRECIP_CN],
  }
  ```

**`check_catalog_drift.py`**：`FE_ONLY_ALLOWLIST` 新增 `"precipitation-static"`

#### 2b. ERA5 灾害事件（ERA5 白天热浪 + ERA5 夜间热浪）

**`catalog.ts`**：
- 在 `era5-dwaa-cn` 条目添加 `mergedInto: 'era5-hazard-events'`
- 在 `era5-wdaa-cn` 条目添加 `mergedInto: 'era5-hazard-events'`
- 新增合并条目（放在 climate 分类末尾）：
  ```typescript
  {
    catalogId: 'era5-hazard-events',
    name: 'ERA5 灾害事件',
    category: 'climate',
    metricLabel: '事件次数',
    metricUnit: 'events',
    metricPrecision: 0,
    updateLabel: '静态数据',
    sourceLabel: '多源可选',
    accentColor: '#e08214',
    accentGlow: 'rgba(224, 130, 20, 0.3)',
    chipTone: 'rgba(224, 130, 20, 0.16)',
    sources: [SOURCE_ERA5_DWAA_CN, SOURCE_ERA5_WDAA_CN],
  }
  ```

**`check_catalog_drift.py`**：`FE_ONLY_ALLOWLIST` 新增 `"era5-hazard-events"`

#### 2c. 土壤水分→土壤湿度 + 下拉框宽度修复

**`catalog.ts`**：
- 第 1030 行 `name: '土壤水分'` 改为 `name: '土壤湿度'`

**`LayerSidebarLibrary.vue`**：
- 第 267 行 `<AppSelect` 添加 `block` 属性

**`LayerSidebar.styles.css`**：
- 在 `.source-selector-label select` 规则后新增：
  ```css
  .source-selector-label .app-select {
    flex: 1;
    min-width: 0;
  }
  ```
  确保多源下拉框占满剩余宽度（与天气图层下拉框一致）

#### 2d. 风云 ω 反演（风云卫星 动态 ω 反演 + 风云卫星 日均 ω 反演）

**`catalog.ts`**：
- 新增两个数据源常量：
  ```typescript
  const SOURCE_FY_OMEGA_DYNAMIC: LayerSource = {
    id: 'method-fy-omega-doy-dynamic',
    name: '风云卫星 动态 ω 反演',
    description: 'omega_sf_fenkuai 流水线：FY 亮温 + SMAP 辅助 → 8-day 分块 SF 倒推 → SM/VOD/OMEGA。',
    urlTemplate: '',
    needsAuth: false,
    needsBackendTransform: false,
    coordSys: 'EPSG:4326',
    updateFrequency: '按工作流运行',
  }

  const SOURCE_FY_OMEGA_AVG: LayerSource = {
    id: 'method-fy-omega-doy-avg',
    name: '风云卫星 日均 ω 反演',
    description: 'omega_avg_daily FY ORIG_TS 链路：D1→D2 日均 ω。',
    urlTemplate: '',
    needsAuth: false,
    needsBackendTransform: false,
    coordSys: 'EPSG:4326',
    updateFrequency: '按工作流运行',
  }
  ```
- 新增两个独立条目（标记 `mergedInto`）和一个合并条目：
  ```typescript
  {
    catalogId: 'method-fy-omega-doy-dynamic',
    name: '风云卫星 动态 ω 反演',
    category: 'research-group',
    subCategory: '模型输出',
    metricLabel: 'ω',
    metricUnit: '',
    metricPrecision: 3,
    updateLabel: '按工作流运行',
    sourceLabel: 'FY 分块反演（动态）',
    accentColor: '#3288bd',
    accentGlow: 'rgba(50, 136, 189, 0.3)',
    chipTone: 'rgba(50, 136, 189, 0.16)',
    sources: [SOURCE_FY_OMEGA_DYNAMIC],
    dataOwner: 'Lab',
    mergedInto: 'fy-omega-inversion',
  },
  {
    catalogId: 'method-fy-omega-doy-avg',
    name: '风云卫星 日均 ω 反演',
    category: 'research-group',
    subCategory: '模型输出',
    metricLabel: 'ω',
    metricUnit: '',
    metricPrecision: 3,
    updateLabel: '按工作流运行',
    sourceLabel: 'FY 日均反演',
    accentColor: '#66c2a5',
    accentGlow: 'rgba(102, 194, 165, 0.3)',
    chipTone: 'rgba(102, 194, 165, 0.16)',
    sources: [SOURCE_FY_OMEGA_AVG],
    dataOwner: 'Lab',
    mergedInto: 'fy-omega-inversion',
  },
  {
    catalogId: 'fy-omega-inversion',
    name: '风云 ω 反演',
    category: 'research-group',
    subCategory: '模型输出',
    metricLabel: 'ω',
    metricUnit: '',
    metricPrecision: 3,
    updateLabel: '按工作流运行',
    sourceLabel: '多源可选',
    accentColor: '#3288bd',
    accentGlow: 'rgba(50, 136, 189, 0.3)',
    chipTone: 'rgba(50, 136, 189, 0.16)',
    sources: [SOURCE_FY_OMEGA_DYNAMIC, SOURCE_FY_OMEGA_AVG],
  }
  ```

**`layer_descriptors.json`**：
- `method-fy-omega-doy-dynamic`：`display_name` 从 `"FY 动态 ω 反演"` 改为 `"风云卫星 动态 ω 反演"`；新增 `sub_category: "模型输出"`；新增 `presentation` 块
- `method-fy-omega-doy-avg`：`display_name` 从 `"FY 日均 ω 反演"` 改为 `"风云卫星 日均 ω 反演"`；新增 `sub_category: "模型输出"`；新增 `presentation` 块

**`check_catalog_drift.py`**：`FE_ONLY_ALLOWLIST` 新增 `"fy-omega-inversion"`

#### 2e. SMAP ω 反演（SMAP 动态 ω 反演 + SMAP 日均 ω 反演）

**`catalog.ts`**：
- 新增两个数据源常量：
  ```typescript
  const SOURCE_SMAP_OMEGA_DYNAMIC: LayerSource = {
    id: 'method-smap-omega-doy-dynamic',
    name: 'SMAP 动态 ω 反演',
    description: 'omega_sf_fenkuai 流水线：SMAP 亮温 + 辅助数据 → 8-day 分块 SF 倒推 → SM/VOD/OMEGA。',
    urlTemplate: '',
    needsAuth: false,
    needsBackendTransform: false,
    coordSys: 'EPSG:4326',
    updateFrequency: '按工作流运行',
  }

  const SOURCE_SMAP_OMEGA_AVG: LayerSource = {
    id: 'method-smap-omega-doy-avg',
    name: 'SMAP 日均 ω 反演',
    description: 'omega_avg_daily / omega_block 经典 D1→D2 链路产出。',
    urlTemplate: '',
    needsAuth: false,
    needsBackendTransform: false,
    coordSys: 'EPSG:4326',
    updateFrequency: '按工作流运行',
  }
  ```
- 新增两个独立条目（标记 `mergedInto`）和一个合并条目：
  ```typescript
  {
    catalogId: 'method-smap-omega-doy-dynamic',
    name: 'SMAP 动态 ω 反演',
    category: 'research-group',
    subCategory: '模型输出',
    metricLabel: 'ω',
    metricUnit: '',
    metricPrecision: 3,
    updateLabel: '按工作流运行',
    sourceLabel: 'SMAP 分块反演（动态）',
    accentColor: '#d53e4f',
    accentGlow: 'rgba(213, 62, 79, 0.3)',
    chipTone: 'rgba(213, 62, 79, 0.16)',
    sources: [SOURCE_SMAP_OMEGA_DYNAMIC],
    dataOwner: 'Lab',
    mergedInto: 'smap-omega-inversion',
  },
  {
    catalogId: 'method-smap-omega-doy-avg',
    name: 'SMAP 日均 ω 反演',
    category: 'research-group',
    subCategory: '模型输出',
    metricLabel: 'ω',
    metricUnit: '',
    metricPrecision: 3,
    updateLabel: '按工作流运行',
    sourceLabel: 'SMAP 日均反演',
    accentColor: '#abdda4',
    accentGlow: 'rgba(171, 221, 164, 0.3)',
    chipTone: 'rgba(171, 221, 164, 0.16)',
    sources: [SOURCE_SMAP_OMEGA_AVG],
    dataOwner: 'Lab',
    mergedInto: 'smap-omega-inversion',
  },
  {
    catalogId: 'smap-omega-inversion',
    name: 'SMAP ω 反演',
    category: 'research-group',
    subCategory: '模型输出',
    metricLabel: 'ω',
    metricUnit: '',
    metricPrecision: 3,
    updateLabel: '按工作流运行',
    sourceLabel: '多源可选',
    accentColor: '#d53e4f',
    accentGlow: 'rgba(213, 62, 79, 0.3)',
    chipTone: 'rgba(213, 62, 79, 0.16)',
    sources: [SOURCE_SMAP_OMEGA_DYNAMIC, SOURCE_SMAP_OMEGA_AVG],
  }
  ```

**`layer_descriptors.json`**：
- `method-smap-omega-doy-dynamic`：新增 `sub_category: "模型输出"`；新增 `presentation` 块
- `method-smap-omega-doy-avg`：新增 `sub_category: "模型输出"`；新增 `presentation` 块

**`check_catalog_drift.py`**：`FE_ONLY_ALLOWLIST` 新增 `"smap-omega-inversion"`

---

### 3. 图层分组修正

#### 3a. 森林覆盖率移入"植被相关"

**判断依据**：`forest-ratio` 有 Zenodo DOI（`https://doi.org/10.5281/zenodo.4708837`），属公开数据源；森林覆盖率是植被相关指标。

**`catalog.ts`**：
- `forest-ratio` 条目：`category` 从 `'research-group'` 改为 `'vegetation'`；删除 `subCategory: '辅助数据'`

**`layer_descriptors.json`**：
- `forest-ratio`：`category` 从 `"research-group"` 改为 `"vegetation"`；删除 `sub_category` 字段

#### 3b. 景观多样性 SHDI 移入"模型输出"

**判断依据**：SHDI（Shannon 多样性指数）是景观生态学指标，基于土地覆盖派生，不直接属于"植被"范畴；`dataOwner: 'Liuzheng'` 无公开 DOI，属课题组数据。按用户指示"如果不属于就放在模型输出中"。

**`catalog.ts`**：
- `landscape-metrics-9km` 条目：`subCategory` 从 `'辅助数据'` 改为 `'模型输出'`

**`layer_descriptors.json`**：
- `landscape-metrics-9km`：`sub_category` 从 `"辅助数据"` 改为 `"模型输出"`

#### 3c. SMAP 辅助数据图层接入

**数据源**：`I:\Geograph_DataSet\Soil_Moisture\SMAP_Auxiliary_Data` 下 9 个 .mat 文件

**需接入的文件清单**（跳过 `info.mat`、`smap_lat_lon.mat`、`ToEaseGrid2.0Net.m`、`LandCover.txt`、`NDVI_clim` 目录）：

| 文件 | layer_id | display_name | 推测变量名 | palette | vmin | vmax | unit |
|------|----------|-------------|-----------|---------|------|------|------|
| Albedo.mat | `smap-aux-albedo` | 反照率 | Albedo | YlOrRd | 0 | 0.5 | - |
| BD.mat | `smap-aux-bd` | 土壤容重 | BD | YlOrBr | 0.8 | 1.8 | g/cm³ |
| SF.mat | `smap-aux-sf` | 砂粒分数 | SF | YlGn | 0 | 1 | fraction |
| B.mat | `smap-aux-b` | B 参数 | B | RdBu | 0 | 10 | - |
| CF.mat | `smap-aux-cf` | 粘粒分数 | CF | PuBu | 0 | 1 | fraction |
| H.mat | `smap-aux-h` | 粗糙度参数 H | H | Oranges | 0 | 0.5 | - |
| IGBP_9km_12.mat | `smap-aux-igbp` | IGBP 土地覆盖 (9km) | IGBP | igbp-landcover-ramp | 1 | 17 | class |
| Koppen_present_083.mat | `smap-aux-koppen` | 柯本气候分类 | Koppen | Set3 | 1 | 30 | class |
| VI_v_qa.mat | `smap-aux-vi-qa` | 植被指数 QA | VI | RdYlGn | 0 | 1 | - |

> **注意**：变量名为推测值，实施时需用 `scipy.io.loadmat` 逐一验证每个 .mat 文件的实际变量名。若变量名不符，以实际为准。

**`overlay_registry.py`**：
- 为每个 .mat 文件新增 `_data_join("Soil_Moisture", "SMAP_Auxiliary_Data", "<filename>.mat")` 路径常量
- 为每个新增 `register_overlay()` 调用，参照 `forest-ratio` 模式：
  - `category="static"`
  - `source_reader="mat"`
  - `source_path` 指向对应 .mat 路径
  - `source_variable` 为表中推测变量名（待验证）
  - `overlay_dir` 为 `_OVERLAY_PNG_ROOT / "smap_aux_<name>"`
  - `png_filename` 为 `smap_aux_<name>_overlay.png`
  - `bounds_filename` 为 `smap_aux_<name>_overlay_bounds.json`

**`layer_descriptors.json`**：
- 为每个辅助数据图层新增 descriptor 条目：
  - `category: "research-group"`
  - `sub_category: "辅助数据"`
  - `engine: "overlay_registry"`
  - `source_type: "algorithm_output"`
  - `render_type: "raster"`
  - `supports_time: false`
  - `time_granularity: "static"`
  - `default_data_access_sources` 指向 `Soil_Moisture/SMAP_Auxiliary_Data`
  - `run_readiness_summary`: `"<名称>辅助数据已就绪（SMAP Auxiliary）；以本地叠加层展示"`
  - `presentation` 块包含 accent_color / metric_label / metric_unit / metric_precision / update_label / source_label

**`catalog.ts`**：
- 为每个辅助数据图层新增 `LayerSource` 常量和 `LayerCatalogItem` 条目：
  - `category: 'research-group'`
  - `subCategory: '辅助数据'`
  - `updateLabel: '静态数据'`
  - `sourceLabel` 对应数据描述

**预览 PNG 生成**：
- 运行 `python Tools/audit_overlay_assets.py` 为新注册的 overlay 生成预览 PNG 和 bounds JSON
- 此步骤需后端服务运行（overlay_registry 在启动时注册）

---

### 4. `check_catalog_drift.py` 最终更新

`FE_ONLY_ALLOWLIST` 最终内容：
```python
FE_ONLY_ALLOWLIST = frozenset(
    {
        "admin-boundary",
        "admin-boundary-cn",
        "soil-moisture",
        "precipitation-static",
        "era5-hazard-events",
        "fy-omega-inversion",
        "smap-omega-inversion",
    }
)
```

---

## 假设与决策

1. **"土壤水分"→"土壤湿度"**：用户明确要求，"土壤湿度"是更标准的科学术语。仅修改合并条目名称，源条目（SMAP L3 土壤水分等）名称不变。
2. **森林覆盖率归类**：有 Zenodo DOI → 公开数据 → 移入 `vegetation`。后端 `data_owner` 字段保持 `"Lab"` 不变（仅前端 `dataOwner` 已为 `'Liuzheng'`）。
3. **景观 SHDI 归类**：SHDI 是景观生态学指标，不直接属于植被 → 移入 `research-group / 模型输出`。
4. **辅助数据变量名**：表中为推测值，实施时须验证。若 .mat 文件内变量名不同，以实际为准。
5. **ω 反演图层行为**：这些是 `python_provider` 工作流图层，添加后若已有运行结果则显示 SM/VOD/ω 图层组，无结果则仅添加条目不渲染——此为系统既有行为，合并条目仅做源选择聚合，不改变运行时逻辑。
6. **IGBP 9km 与现有 landcover-cn 不冲突**：前者是 SMAP 辅助数据 9km EASE-Grid，后者是 MODIS 0.25° 中国区域裁剪；分属不同分类（辅助数据 vs 土地利用），不构成重复。
7. **brooks-lint 代码审查**：实施完成后使用 `trae-remote-official:brooks-lint:brooks-review` 对全部变更进行 PR 级代码审查。

## 验证步骤

### 前端
1. `cd Code/frontend && npm run check:catalog` — 验证前后端目录无漂移
2. `cd Code/frontend && npm run test` — 全量前端测试
3. `cd Code/frontend && npm run lint && npm run build` — lint + 构建

### 后端
1. `Env/Python312/python.exe -m pytest Test/backend/test_data_source_paths.py Test/backend/test_data_root_policy.py -q` — 数据根/图层就绪
2. 启动后端 `python launch.py start fastapi`，请求 `GET /layers` 确认新图层可见且 `sub_category` 正确

### 辅助数据
1. 运行 `python Tools/audit_overlay_assets.py` 生成预览 PNG
2. 启动后端后 `GET /layers/smap-aux-albedo` 验证图层元数据返回正常

### 代码审查
1. 使用 `brooks-lint:brooks-review` skill 对所有变更进行 PR 级代码审查

## 实施顺序

1. `settings-local.ts` — 添加持久化字段
2. `AppearanceSettings.vue` — 添加开关
3. `InfoPanelToolsTab.vue` — 移除本地状态，引用设置
4. `catalog.ts` — 所有新增/修改条目（合并条目 + 重命名 + 归类调整 + 辅助数据）
5. `layer_descriptors.json` — 后端元数据同步（display_name + sub_category + presentation + 新辅助图层）
6. `overlay_registry.py` — 注册 9 个辅助数据 overlay
7. `LayerSidebarLibrary.vue` + `LayerSidebar.styles.css` — 下拉框宽度修复
8. `check_catalog_drift.py` — 更新 allowlist
9. `audit_overlay_assets.py` — 生成预览 PNG
10. 验证（前端测试 + 后端测试 + 目录检查）
11. brooks-lint 代码审查
