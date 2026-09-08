# X1 图层注册表外部化计划

## 概要

将图层目录的三处真源（后端 `layer_descriptors.json`、`weatherengine/constants.py`、前端 `catalog.ts`）统一为后端 JSON 单一真源，前端通过构建时代码生成获取兜底数据，消灭手工同步。

**决策状态**：Approved（用户确认：构建时代码生成 + LayerSource 全部迁移后端）

---

## 当前状态分析

### 三处真源现状

| 真源 | 文件 | 数据内容 | 问题 |
|------|------|---------|------|
| 后端 JSON | `catalog_seeds/layer_descriptors.json` + `weather_descriptors.json` | 完整 LayerDescriptor（含 presentation、run_readiness、engine 等） | 已有 `LayerPresentation` 模型，但缺 `sources`、`merged_into` 字段 |
| 后端 WEATHER_LAYER_SPECS | `weatherengine/constants.py` | 天气图层渲染规格（palette、vmin/vmax、render_hint） | 已在 `_load_seed_descriptors()` 中通过 `_weather_capabilities()` 注入 descriptor，**实质已统一** |
| 前端 catalog.ts | `stores/layers/catalog.ts`（~1500 行） | UI 呈现字段（与后端 presentation 重复）+ LayerSource（FE 独有）+ 合并分组逻辑（FE 独有）+ LAYER_CATEGORIES（部分与后端重复） | **主要债务来源**：新增图层需同时改 catalog.ts + layer_descriptors.json，靠 check_catalog_drift.py 人工守卫 |

### 运行时数据流（已部分外部化）

```
GET /layers → LayerDescriptor[] → buildRuntimeLayerLibraryItem()
  ├── presentation 字段：后端 descriptor.presentation（优先）→ catalog.ts 静态表（兜底）
  ├── engine/sourceType/renderType：后端 descriptor（唯一）
  ├── sources：catalog.ts 静态表（唯一）  ← 未外部化
  └── merged groups：catalog.ts MERGED_LAYER_GROUPS（唯一）  ← 未外部化
```

### 前端 catalog.ts 中 FE 独有数据（后端 JSON 中不存在）

1. **`LayerSource[]`** — 每个图层的源定义（`urlTemplate`、`needsAuth`、`needsBackendTransform`、`coordSys`、`updateFrequency`、`attribution`）
2. **合并分组** — `mergedInto` 字段 + `MERGED_LAYER_GROUPS`（合并组 catalogId → 源 ID 列表）+ `MERGED_LAYER_SOURCES`（反向查找）
3. **`LAYER_CATEGORIES` UI 元数据** — `icon`、`accentColor`、`chipTone`（后端 `layer_categories.json` 仅有 `id` 和 `name`）
4. **`WEATHER_ENGINE_CATALOG_IDS`** — 从 LAYER_LIBRARY 中 source.id 前缀 `weatherengine-` 派生的静态白名单
5. **`isAdminBoundary`** — 行政边界图层标记

---

## 架构决策记录（ADR）

### 决策问题

如何消除图层目录的三处真源，使新增图层只需修改一处？

### 决策

**后端 JSON 为唯一真源 + 构建时代码生成前端兜底 JSON。**

| 维度 | 选择 | 理由 |
|------|------|------|
| 真源 | 后端 `catalog_seeds/*.json` | 运行时已是真源，扩展即可 |
| 兜底策略 | 构建时代码生成 | 消灭手工同步，保留离线能力 |
| LayerSource 迁移 | 全部迁移到后端 | 真正单一真源，后端已掌握 engine/source_type 等相关字段 |
| 合并分组 | 后端 `merged_into` 字段 + 虚拟组条目 | 数据驱动，前端从 descriptor 派生 |

### 被拒绝的替代方案

| 方案 | 拒绝理由 |
|------|---------|
| 纯 API 驱动，无兜底 | 后端不可用时图层面板完全空白，降低开发体验 |
| 保留手维护 JSON 兜底 | 未消灭手工同步，只是将 TS 对象改为 JSON import |
| 合并分组保留 FE 独有 | 仍存在两处真源（后端 descriptor + 前端合并映射） |

### 后果

**正面**：
- 新增图层只需改后端 JSON 一处 + 运行 `npm run gen:catalog`
- `check_catalog_drift.py` 从"跨文件一致性守卫"简化为"代码生成产物校验"
- `catalog.ts` 从 ~1500 行降至 ~200 行

**负面**：
- 新增构建步骤（`gen:catalog`），CI 需在 build 前执行
- 后端 JSON 文件体积增大（每条目增加 sources + merged_into 字段）
- 后端 `LayerDescriptor` schema 扩展需前后端同步发布

### 可逆性

**双向门**。回退方法：恢复 `catalog.ts` 手维护版本 + 删除 codegen 脚本。后端 JSON 新增字段不破坏现有消费者（Pydantic 可选字段 + JSON 前向兼容）。

---

## 实施步骤

### Phase 1：扩展后端 Schema（共享契约 + JSON 数据）

#### 1.1 新增 `LayerSourceDef` 模型

**文件**：`Code/shared/contracts/api_contracts.py`

```python
class LayerSourceDef(BaseModel):
    """图层数据源定义（X1 外部化：从前端 catalog.ts 迁移到后端 JSON）。"""
    source_id: str
    """源标识，与 layer_id 对齐（合并组的成员 layer_id）。"""
    name: str
    """源显示名。"""
    description: str = ""
    url_template: str = ""
    needs_auth: bool = False
    needs_backend_transform: bool = False
    coord_sys: str = "EPSG:4326"
    update_frequency: str = ""
    attribution: str | None = None
```

#### 1.2 扩展 `LayerDescriptor`

**文件**：`Code/shared/contracts/api_contracts.py`

```python
class LayerDescriptor(BaseModel):
    # ... 现有字段不变 ...
    
    sources: list[LayerSourceDef] = Field(default_factory=list)
    """图层数据源列表（X1）。单源图层含 1 项；合并组含多个成员源。"""
    
    merged_into: str | None = None
    """若此图层已合并到某个多源组，此处记录目标 catalog_id。"""
    
    is_merged_group: bool = False
    """标记此条目为合并组虚拟条目（含 members 列表，自身不对应实际数据）。"""
    
    members: list[str] = Field(default_factory=list)
    """合并组成员的 layer_id 列表（仅 is_merged_group=true 时有效）。"""
    
    is_admin_boundary: bool = False
    """是否为行政区边界图层。"""
```

#### 1.3 扩展 `LayerCategoryDef`

**文件**：`Code/shared/contracts/api_contracts.py`

```python
class LayerCategoryDef(BaseModel):
    id: str
    name: str
    icon: str = ""
    accent_color: str = ""
    chip_tone: str = ""
```

#### 1.4 扩展 `LayerCatalogResponse`

**文件**：`Code/shared/contracts/api_contracts.py`

```python
class LayerCatalogResponse(BaseModel):
    items: list[LayerDescriptor]
    categories: list[LayerCategoryDef] = Field(default_factory=list)
    """X1: 类别定义随 catalog 一起下发，前端无需维护静态 LAYER_CATEGORIES。"""
```

#### 1.5 填充后端 JSON 数据

**文件**：`Code/backend/app/catalog_seeds/layer_descriptors.json`

- 为每个现有图层条目添加 `sources` 数组（从 `catalog.ts` 中的 `LayerSource` 定义迁移）
- 为已合并的图层添加 `merged_into` 字段（如 `gpcp-precip-ts` → `merged_into: "precipitation-static"`）
- 新增合并组虚拟条目（`is_merged_group: true` + `members` 列表）
- 为行政边界图层添加 `is_admin_boundary: true`

**文件**：`Code/backend/app/catalog_seeds/layer_categories.json`

- 为每个类别添加 `icon`、`accent_color`、`chip_tone` 字段（从 `catalog.ts` 中的 `LAYER_CATEGORIES` 迁移）

#### 1.6 更新后端 catalog 服务

**文件**：`Code/backend/app/services/layer_catalog.py`

- `get_layer_catalog()` 在响应中包含 `categories`
- `_load_seed_descriptors()` 保持现有 mtime 缓存逻辑（Pydantic 自动解析新字段）

---

### Phase 2：构建时代码生成

#### 2.1 创建 codegen 脚本

**文件**：`Tools/generate_catalog_seeds.py`

```python
"""从后端 catalog_seeds JSON 生成前端兜底 JSON。

读取：
  Code/backend/app/catalog_seeds/layer_descriptors.json
  Code/backend/app/catalog_seeds/weather_descriptors.json
  Code/backend/app/catalog_seeds/layer_categories.json

生成：
  Code/frontend/src/stores/layers/catalog-seeds.generated.json
"""
```

脚本逻辑：
1. 读取后端 JSON 文件
2. 转换为前端 `LayerCatalogItem[]` + `LayerCategory[]` 格式
3. 写入 `catalog-seeds.generated.json`（含 `categories`、`items` 两个顶层 key）
4. 输出文件头部标注 `// AUTO-GENERATED by Tools/generate_catalog_seeds.py — DO NOT EDIT`

#### 2.2 添加 npm 脚本

**文件**：`Code/frontend/package.json`

```json
{
  "scripts": {
    "gen:catalog": "python ../../Tools/generate_catalog_seeds.py",
    "prebuild": "npm run gen:catalog",
    "check:catalog": "python ../../Tools/check_catalog_drift.py"
  }
}
```

#### 2.3 更新 check_catalog_drift.py

**文件**：`Tools/check_catalog_drift.py`

简化为代码生成产物校验：
- 检查 `catalog-seeds.generated.json` 是否存在且与后端 JSON 一致（mtime 比较或内容 hash）
- 移除 FE_ONLY_ALLOWLIST（不再需要——合并组条目已在后端 JSON 中）
- 移除 presentation 字段交叉检查（由 codegen 保证一致性）
- 保留 category 一致性检查

---

### Phase 3：重构前端 catalog.ts

#### 3.1 替换 LAYER_LIBRARY 和 LAYER_CATEGORIES

**文件**：`Code/frontend/src/stores/layers/catalog.ts`

```typescript
import catalogData from './catalog-seeds.generated.json'

interface GeneratedCatalog {
  categories: LayerCategory[]
  items: LayerCatalogItem[]
}

const data = catalogData as GeneratedCatalog

export const LAYER_CATEGORIES: LayerCategory[] = data.categories
export const LAYER_LIBRARY: LayerCatalogItem[] = data.items
```

#### 3.2 派生 helpers 从 generated JSON 计算

```typescript
// 从 LAYER_LIBRARY 中 is_merged_group 条目派生
export const MERGED_LAYER_GROUPS = new Map(
  LAYER_LIBRARY
    .filter(item => item.isMergedGroup)
    .map(item => [item.catalogId, item.members])
)

// 从 mergedInto 字段派生反向查找
export const MERGED_LAYER_SOURCES = new Map(
  LAYER_LIBRARY
    .filter(item => item.mergedInto)
    .map(item => [item.catalogId, item.mergedInto!])
)

// 从 source 前缀派生天气引擎白名单
export const WEATHER_ENGINE_CATALOG_IDS = new Set(
  LAYER_LIBRARY
    .filter(item => item.sources.some(s => s.id.startsWith('weatherengine')))
    .map(item => item.catalogId)
)
```

#### 3.3 更新 types.ts

**文件**：`Code/frontend/src/stores/layers/types.ts`

`LayerCatalogItem` 接口新增：
```typescript
export interface LayerCatalogItem {
  // ... 现有字段 ...
  isMergedGroup?: boolean
  members?: string[]
  isAdminBoundary?: boolean  // 已存在，确认类型
}
```

#### 3.4 更新 catalog-builders.ts

**文件**：`Code/frontend/src/stores/layers/catalog-builders.ts`

`buildRuntimeLayerLibraryItem()` 的 `fallback` 查找逻辑不变——仍从 `LAYER_LIBRARY`（现为 generated JSON）获取兜底数据。后端 descriptor 中的 `sources` 和 `merged_into` 字段优先使用。

关键变更：
```typescript
// 优先使用后端 descriptor.sources，兜底用静态表
sources: descriptor.sources?.length 
  ? descriptor.sources.map(s => ({ ... })) 
  : fallback?.sources ?? [],

// 优先使用后端 descriptor.merged_into
mergedInto: descriptor.merged_into ?? fallback?.mergedInto,
```

#### 3.5 更新 catalog-runtime.ts

**文件**：`Code/frontend/src/stores/layers/catalog-runtime.ts`

合并组构建逻辑改用后端 `is_merged_group` 标记：
```typescript
// 从 runtimeLayerCatalog 中查找合并组虚拟条目
const mergedGroupDescriptors = Object.values(runtimeLayerCatalog.value)
  .filter(d => d.is_merged_group)

for (const groupDescriptor of mergedGroupDescriptors) {
  const memberIds = groupDescriptor.members ?? []
  // ... 构建 enriched 条目（同现有逻辑）...
}
```

---

### Phase 4：清理与验证

#### 4.1 移除前端硬编码数据源定义

**文件**：`Code/frontend/src/stores/layers/catalog.ts`

删除所有 `const SOURCE_XXX: LayerSource = { ... }` 常量定义（约 30 个，~500 行）。这些数据已迁移到后端 JSON 并通过 codegen 生成为 `catalog-seeds.generated.json` 的一部分。

#### 4.2 更新 .gitignore

**文件**：`.gitignore`

```
# X1: 自动生成的 catalog 兜底 JSON
Code/frontend/src/stores/layers/catalog-seeds.generated.json
```

#### 4.3 更新 CI

**文件**：`.github/workflows/ci.yml`

在 build 步骤前添加：
```yaml
- name: Generate catalog seeds
  run: cd Code/frontend && npm run gen:catalog

- name: Verify catalog drift
  run: cd Code/frontend && npm run check:catalog
```

---

## 假设与决策

| 编号 | 假设/决策 | 理由 |
|------|----------|------|
| A1 | `weatherengine/constants.py` 的 `WEATHER_LAYER_SPECS` 不需要迁移 | 已通过 `_weather_capabilities()` 注入 descriptor，实质已统一 |
| A2 | 合并组作为虚拟条目放入 `layer_descriptors.json` | 保持单一 JSON 文件，避免新增文件 |
| A3 | 生成 JSON 加入 `.gitignore` | 避免手工编辑，CI 中每次重新生成 |
| A4 | `LayerSourceDef` 使用 `source_id` 而非 `id` | 避免与 `LayerDescriptor.layer_id` 混淆 |
| A5 | 前端 `catalog.ts` 保留 derived helpers（MERGED_LAYER_GROUPS 等） | 纯计算逻辑，无数据重复 |
| A6 | 后端 `LayerDescriptor` 新增字段均为可选（`| None = None` / `default_factory`） | 前向兼容，不破坏现有消费者 |

---

## 验证步骤

### Phase 1 验证（Schema 扩展）

```bash
# 后端模型验证
Env/Python312/python.exe -c "from shared.contracts.api_contracts import LayerDescriptor; print('OK')"

# 后端 API 验证
Env/Python312/python.exe launch.py start fastapi
curl http://127.0.0.1:8000/layers | python -m json.tool | head -50
# 确认响应包含 sources、merged_into、categories 字段
```

### Phase 2 验证（代码生成）

```bash
# 生成兜底 JSON
cd Code/frontend && npm run gen:catalog

# 验证生成产物
ls -la src/stores/layers/catalog-seeds.generated.json
python ../../Tools/check_catalog_drift.py
```

### Phase 3 验证（前端重构）

```bash
# 前端测试
cd Code/frontend && npm run test

# Lint
cd Code/frontend && npm run lint

# Build（含 prebuild gen:catalog）
cd Code/frontend && npm run build
```

### Phase 4 验证（完整回归）

```bash
# 契约校验
cd Code/frontend && npm run check:catalog && npm run check:openapi

# 后端测试
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= \
  Env/Python312/python.exe -m pytest Test/backend -q -p no:cacheprovider --basetemp="Test/.pytest-be"

# 前端完整测试
cd Code/frontend && npm run test && npm run lint && npm run build

# 提交前
pre-commit run --all-files
```

---

## 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `Code/shared/contracts/api_contracts.py` | 修改 | 新增 `LayerSourceDef`；扩展 `LayerDescriptor`（sources, merged_into, is_merged_group, members, is_admin_boundary）；扩展 `LayerCategoryDef`（icon, accent_color, chip_tone）；扩展 `LayerCatalogResponse`（categories） |
| `Code/backend/app/catalog_seeds/layer_descriptors.json` | 修改 | 每条目添加 `sources`；已合并图层添加 `merged_into`；新增合并组虚拟条目；行政边界添加 `is_admin_boundary` |
| `Code/backend/app/catalog_seeds/layer_categories.json` | 修改 | 每类别添加 `icon`、`accent_color`、`chip_tone` |
| `Code/backend/app/services/layer_catalog.py` | 修改 | `get_layer_catalog()` 响应包含 `categories` |
| `Code/frontend/openapi.json` | 修改 | OpenAPI schema 同步更新 |
| `Tools/generate_catalog_seeds.py` | 新增 | 构建时代码生成脚本 |
| `Tools/check_catalog_drift.py` | 修改 | 简化为 codegen 产物校验 |
| `Code/frontend/package.json` | 修改 | 添加 `gen:catalog` 脚本 + `prebuild` 钩子 |
| `Code/frontend/src/stores/layers/catalog.ts` | 重构 | 删除 ~500 行 SOURCE_ 常量 + ~800 行硬编码 LAYER_LIBRARY；替换为 generated JSON import + derived helpers |
| `Code/frontend/src/stores/layers/types.ts` | 修改 | `LayerCatalogItem` 新增 `isMergedGroup`、`members` 字段 |
| `Code/frontend/src/stores/layers/catalog-builders.ts` | 修改 | `buildRuntimeLayerLibraryItem()` 优先使用后端 `sources` 和 `merged_into` |
| `Code/frontend/src/stores/layers/catalog-runtime.ts` | 修改 | 合并组构建逻辑改用后端 `is_merged_group` 标记 |
| `.gitignore` | 修改 | 添加 `catalog-seeds.generated.json` |
| `.github/workflows/ci.yml` | 修改 | build 前添加 `gen:catalog` + drift check |
| `.ai/progress/` | 新增 | X1 完成记录 |
