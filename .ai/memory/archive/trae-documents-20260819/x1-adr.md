# X1 图层注册表外部化 — 架构决策记录 (ADR)

> Specialist: `architecture-decisions` | Phase: Design → Development | Surface: API contracts, data, architecture

## Context

CGDA 图层目录当前存在**三处真源**，新增/修改图层需手工同步多处文件，靠 `check_catalog_drift.py` 人工守卫：

| 真源 | 文件 | 数据内容 | 已外部化程度 |
|------|------|---------|------------|
| 后端 JSON | `catalog_seeds/layer_descriptors.json` + `weather_descriptors.json` | 完整 `LayerDescriptor`（含 `presentation`、`run_readiness`、`engine` 等） | `presentation` 字段已下发，`buildRuntimeLayerLibraryItem()` 已优先消费 ✅ |
| 后端类别 | `catalog_seeds/layer_categories.json` | 类别定义（`id`/`name`/`icon`/`accent_color`/`chip_tone`） | JSON 已含 UI 元数据 ✅，但前端 `LAYER_CATEGORIES` 仍硬编码，运行时未消费后端类别 ❌ |
| 前端 TS | `stores/layers/catalog.ts`（~1500 行） | UI 呈现字段（与 `presentation` 重复）+ `LayerSource[]`（FE 独有）+ 合并分组逻辑（FE 独有）+ `LAYER_CATEGORIES`（与后端重复） | **主要债务来源** ❌ |

### 运行时数据流（当前）

```
GET /layers → LayerDescriptor[] → buildRuntimeLayerLibraryItem()
  ├── presentation 字段：后端 descriptor.presentation（优先）→ catalog.ts 静态表（兜底）  ✅ 已统一
  ├── engine/sourceType/renderType：后端 descriptor（唯一）  ✅ 已统一
  ├── sources：catalog.ts 静态表（唯一）  ❌ 未外部化
  ├── merged groups：catalog.ts MERGED_LAYER_GROUPS（唯一）  ❌ 未外部化
  └── categories：catalog.ts LAYER_CATEGORIES（唯一，后端 JSON 仅离线对齐）  ❌ 未外部化
```

### 代码审查发现的关键缺口

| 编号 | 缺口 | 位置 | 影响 |
|------|------|------|------|
| G1 | `sources` 始终从静态兜底取，不从后端 descriptor 取 | `catalog-builders.ts:255` `sources: fallback?.sources ?? []` | 后端 `sources` 字段即使添加也不会被前端消费 |
| G2 | `ensureRuntimeLayerCatalog()` 只存 `response.items`，不存 `response.categories` | `catalog-runtime.ts:278` | 即使 `LayerCatalogResponse` 增加 `categories`，前端也不会使用 |
| G3 | 合并组遍历依赖静态 `MERGED_LAYER_GROUPS`，不从 runtime descriptor 派生 | `catalog-runtime.ts:93` | 后端 `is_merged_group` 标记即使添加也不会被消费 |
| G4 | 静态兜底过滤依赖 `LAYER_LIBRARY` 中的 `mergedInto` 字段 | `catalog-runtime.ts:135,199` | 后端 `merged_into` 字段不被消费 |
| G5 | `LayerSourceDef.source_id` ↔ `LayerSource.id` 字段名映射未定义 | codegen 脚本 + `catalog-builders.ts` | snake_case → camelCase 转换缺失 |
| G6 | `CATEGORY_INDEX_BY_ID` 从静态 `LAYER_CATEGORIES` 构建 | `catalog-builders.ts:156` | 后端类别顺序变更不会反映到前端排序 |
| G7 | OpenAPI 类型再生成后 `LayerDescriptor` 新字段需同步到 `runtime-api.ts` | `services/runtime-api.ts` | 前端类型与后端 schema 漂移 |

## Decision Drivers

| Driver | Priority | Evidence | Tradeoff |
|--------|----------|---------|----------|
| 新增图层只需改一处 | P0 | 每次新增图层需同时改 `catalog.ts` + `layer_descriptors.json` + `check_catalog_drift.py` allowlist | 一次性重构成本 vs 持续同步成本 |
| 离线开发能力 | P1 | 后端不可用时图层面板应显示兜底数据 | 需要构建时代码生成，增加 build 步骤 |
| 前后端契约一致性 | P0 | `check_catalog_drift.py` 存在本身就说明有漂移风险 | codegen 消灭漂移源头 vs 增加 build 复杂度 |
| 向后兼容 | P1 | 现有 `LayerDescriptor` 消费者（测试、CI、OpenAPI）不能 break | Pydantic 可选字段 + JSON 前向兼容 |
| `catalog.ts` 可维护性 | P2 | 1500 行硬编码数据，查找/修改困难 | 重构后 ~200 行 derived helpers |

## Options Considered

| Option | Benefits | Costs | Risks | Rejected Or Selected Because |
|--------|----------|-------|-------|------------------------------|
| **A. 后端 JSON 单一真源 + 构建时代码生成** | 消灭手工同步；保留离线兜底；codegen 保证一致性 | 新增 build 步骤；后端 JSON 体积增大；前后端 schema 需同步发布 | codegen 脚本 bug 影响所有前端构建 | **Selected** — 唯一彻底消灭多真源的方案 |
| B. 纯 API 驱动，无兜底 | 最简单；无 codegen | 后端不可用时图层面板空白 | 降级开发体验 | Rejected — 离线开发场景不可接受 |
| C. 保留手维护 JSON 兜底 | 无 codegen | 未消灭手工同步，只是将 TS 对象改为 JSON import | 漂移问题不变 | Rejected — 治标不治本 |
| D. 合并分组保留 FE 独有 | 减少后端 JSON 改动 | 仍存在两处真源（后端 descriptor + 前端合并映射） | 部分外部化，债务不彻底 | Rejected — 违背单一真源目标 |

## Decision

**后端 `catalog_seeds/*.json` 为唯一真源 + 构建时代码生成前端兜底 JSON。**

| 维度 | 选择 | 理由 |
|------|------|------|
| 真源 | 后端 `catalog_seeds/*.json` | 运行时已是真源，扩展即可 |
| 兜底策略 | 构建时代码生成（`generate_catalog_seeds.py`） | 消灭手工同步，保留离线能力 |
| LayerSource 迁移 | 全部迁移到后端 `LayerSourceDef` | 真正单一真源 |
| 合并分组 | 后端 `merged_into` 字段 + `is_merged_group` 虚拟组条目 | 数据驱动，前端从 descriptor 派生 |
| 类别定义 | 后端 `layer_categories.json` 随 `LayerCatalogResponse.categories` 下发 | 消除 `LAYER_CATEGORIES` 硬编码 |
| 字段命名 | codegen 负责 snake_case → camelCase | 前端保持现有接口不变 |

## Status

**Approved** — 用户已确认（构建时代码生成 + LayerSource 全部迁移后端）。

## Bounded Context Map

| Context | Responsibility | Model/Language | Owned Data | Upstream Dependencies | Downstream Consumers | Translation Surface |
|---------|---------------|----------------|------------|----------------------|----------------------|-------------------|
| Backend Catalog Seeds | 图层目录数据真源 | Python Pydantic models + JSON | `layer_descriptors.json`, `weather_descriptors.json`, `layer_categories.json` | 无（人类编辑） | `layer_catalog.py` service, codegen script | JSON → Pydantic `LayerDescriptor` |
| Backend Layer Catalog Service | 运行时目录组装与 API 下发 | Python FastAPI | `LayerCatalogResponse` (items + categories) | Catalog Seeds, `weatherengine/constants.py`, DB remote URIs | `GET /layers`, `GET /layers/categories` | Pydantic → JSON response |
| Codegen Script | 构建时生成前端兜底 JSON | Python script | `catalog-seeds.generated.json` | Backend Catalog Seeds JSON | Frontend `catalog.ts` | snake_case → camelCase, `LayerSourceDef` → `LayerSource` |
| Frontend Catalog Store | 运行时图层目录消费 | TypeScript + Vue 3 Pinia | `runtimeLayerCatalog`, `layerLibrary` computed | Backend API (runtime), generated JSON (fallback) | Layer panel, map, analysis tools | `LayerDescriptor` → `RuntimeLayerLibraryItem` |
| Frontend Catalog Builders | descriptor → UI item 转换 | TypeScript pure functions | `buildRuntimeLayerLibraryItem()` | `catalog.ts` (fallback), `runtime-api.ts` (descriptor types) | `catalog-runtime.ts` | `presentation` → UI fields, `sources` → `LayerSource[]` |
| Drift Checker | codegen 产物一致性校验 | Python script | exit code 0/1 | Backend JSON, generated JSON | CI pipeline | 内容 hash 比较 |

### 上下文关系

```
Backend Catalog Seeds (真源)
  ├── → layer_catalog.py (运行时 API 下发)
  │     └── → Frontend catalog-runtime.ts (运行时消费)
  │           └── → catalog-builders.ts (descriptor → UI item)
  └── → generate_catalog_seeds.py (构建时代码生成)
        └── → catalog-seeds.generated.json (前端兜底)
              └── → catalog.ts (import + derived helpers)
                    └── → catalog-builders.ts (fallback 查找)
```

## Runtime Dependency Adoption

| Dependency | Capability Needed | Failure Mode | Timeout/Retry/Fallback | Adoption Criteria | Revisit Trigger |
|------------|------------------|-------------|----------------------|-------------------|----------------|
| Backend `GET /layers` | 运行时图层目录 | API 不可用 | 静态兜底（generated JSON） | 已有重试逻辑 (`catalog-runtime.ts:266-275`) | 无需变更 |
| `generate_catalog_seeds.py` | 构建时生成兜底 JSON | 脚本执行失败 | `prebuild` 钩子阻止 build | CI 中 `gen:catalog` 先于 `build` | 后端 JSON schema 变更时更新脚本 |
| `catalog-seeds.generated.json` | 前端离线兜底数据 | 文件缺失 | `catalog.ts` import 失败 → build 报错 | `.gitignore` 排除，CI 每次重新生成 | 无需手动维护 |

## Fitness Functions

| # | Property Under Test | Metric | Threshold/Rule | Measurement Source | Cadence | Failure Response | Local Check Path |
|---|-------------------|--------|---------------|-------------------|---------|-----------------|------------------|
| F1 | 单一真源 | `catalog.ts` 中硬编码 `SOURCE_` 常量数量 | 0 | grep `const SOURCE_` in `catalog.ts` | 每次构建 | build 失败 | `grep -c "const SOURCE_" catalog.ts` |
| F2 | codegen 产物一致性 | generated JSON 内容 hash == 后端 JSON 内容 hash | 相等 | `check_catalog_drift.py` | 每次 CI | CI 失败 | `npm run check:catalog` |
| F3 | 前后端 schema 同步 | OpenAPI `LayerDescriptor` 含 `sources`/`merged_into`/`is_merged_group` | 全部存在 | `npm run check:openapi` | 每次 CI | CI 失败 | `npm run check:openapi` |
| F4 | 合并组数据驱动 | `MERGED_LAYER_GROUPS` 从 `isMergedGroup` 派生，非硬编码 | 无硬编码 Map 初始化 | 代码审查 | 一次性 | code review 阻止 | `grep "new Map(\[" catalog.ts` |
| F5 | 向后兼容 | 现有后端测试全通过 | 0 failures | `pytest Test/backend` | 每次 CI | CI 失败 | `Env/Python312/python.exe -m pytest Test/backend -q` |
| F6 | 前端功能不回归 | 前端测试全通过 | 0 failures | `npm run test` | 每次 CI | CI 失败 | `cd Code/frontend && npm run test` |

## Risk Register

| Risk | Likelihood | Impact | Mitigation | Decision Record | Owner |
|------|-----------|--------|-----------|----------------|-------|
| codegen 脚本 bug 导致前端 build 失败 | Medium | High | 脚本含 schema 验证 + dry-run 模式；CI 先跑 `gen:catalog` 再 `check:catalog` | 本 ADR | User + local checks |
| 后端 `LayerDescriptor` 新字段未同步到 OpenAPI → 前端类型缺失 | Medium | Medium | `npm run check:openapi` 作为 CI 质量门 | 本 ADR | CI |
| 合并组虚拟条目缺少必填字段（`extent`/`source_type` 等）导致 Pydantic 验证失败 | High | High | 虚拟条目使用占位值（`extent: default`/`source_type: cog`/`render_type: raster`）；`_load_seed_descriptors()` 已有单条失败跳过逻辑 | 本 ADR | User |
| `LayerSourceDef.source_id` ↔ `LayerSource.id` 映射遗漏导致前端找不到源 | Medium | High | codegen 脚本显式映射 `source_id` → `id`；`check_catalog_drift.py` 验证源 ID 一致性 | 本 ADR | codegen script |
| `ensureRuntimeLayerCatalog()` 未消费 `response.categories` 导致运行时类别仍用静态表 | High | Medium | Phase 3.5 显式更新 `catalog-runtime.ts` 存储 categories | 本 ADR G2 | User |
| 过渡期前后端版本不一致（后端未部署新 schema，前端已用新 codegen） | Low | Low | 新字段均为可选（`default_factory`/`None`）；codegen 产出的 JSON 对旧后端响应兼容 | 本 ADR | — |

## Consequences

### Positive

- 新增图层只需改后端 JSON 一处 + 运行 `npm run gen:catalog`
- `check_catalog_drift.py` 从"跨文件一致性守卫"简化为"codegen 产物 hash 校验"
- `catalog.ts` 从 ~1500 行降至 ~200 行（import + derived helpers）
- `LAYER_CATEGORIES` 从硬编码变为后端下发，类别顺序/颜色变更无需前端发版
- 合并组从 `MERGED_LAYER_GROUPS` 硬编码 Map 变为 `is_merged_group` descriptor 派生

### Negative

- 新增构建步骤（`gen:catalog`），CI 需在 build 前执行
- 后端 JSON 文件体积增大（每条目增加 `sources` + 合并组虚拟条目）
- 后端 `LayerDescriptor` schema 扩展需前后端同步发布（OpenAPI 再生成）
- codegen 脚本成为 build 关键路径，脚本 bug 影响所有前端构建

## Reversibility

**双向门（Two-way door）。**

- 回退方法：恢复 `catalog.ts` 手维护版本 + 删除 codegen 脚本 + 移除 `prebuild` 钩子
- 后端 JSON 新增字段不破坏现有消费者（Pydantic 可选字段 + JSON 前向兼容）
- 回退触发条件：codegen 脚本持续维护成本超过手工同步成本；或构建链路不稳定影响开发效率

## Evidence

- `catalog-builders.ts:255` — `sources: fallback?.sources ?? []` 证明 sources 未从后端消费
- `catalog-runtime.ts:278` — `response.items.map(...)` 证明 categories 未被存储
- `catalog-runtime.ts:93` — `MERGED_LAYER_GROUPS` 静态遍历证明合并组未数据驱动
- `catalog.ts:14-64` — `LAYER_CATEGORIES` 硬编码 7 个类别，与 `layer_categories.json` 重复
- `catalog.ts:69-625` — ~40 个 `SOURCE_XXX` 常量，~500 行硬编码源定义
- `layer_categories.json` — 已含 `icon`/`accent_color`/`chip_tone`，证明后端 JSON 已就绪
- `api_contracts.py:66-89` — `LayerPresentation` 已存在且 X1 标注
- `api_contracts.py:92-99` — `LayerCategoryDef` 已含 UI 元数据字段

## Revisit Triggers

1. 后端 JSON 条目数超过 100 时：评估是否需要数据库替代 JSON 文件
2. codegen 脚本复杂度超过 300 行时：评估是否改用 OpenAPI codegen 工具链
3. 前端需要动态（非构建时）更新目录时：评估是否移除兜底 JSON 改为纯 API 驱动

---

## Implementation Plan

### Phase 1: 后端 Schema 扩展 + JSON 数据填充

#### 1.1 新增 `LayerSourceDef` 模型

**文件**: `Code/shared/contracts/api_contracts.py`

```python
class LayerSourceDef(BaseModel):
    """图层数据源定义（X1 外部化：从前端 catalog.ts 迁移到后端 JSON）。"""
    source_id: str
    name: str
    description: str = ""
    url_template: str = ""
    needs_auth: bool = False
    needs_backend_transform: bool = False
    coord_sys: str = "EPSG:4326"
    update_frequency: str = ""
    attribution: str | None = None
```

#### 1.2 扩展 `LayerDescriptor`

新增字段（均为可选，前向兼容）:
- `sources: list[LayerSourceDef] = Field(default_factory=list)`
- `merged_into: str | None = None`
- `is_merged_group: bool = False`
- `members: list[str] = Field(default_factory=list)`
- `is_admin_boundary: bool = False`

#### 1.3 扩展 `LayerCatalogResponse`

```python
class LayerCatalogResponse(BaseModel):
    items: list[LayerDescriptor]
    categories: list[LayerCategoryDef] = Field(default_factory=list)
```

#### 1.4 填充后端 JSON

**`layer_descriptors.json`**:
- 每个现有条目添加 `sources` 数组（从 `catalog.ts` SOURCE_ 常量迁移）
- 已合并图层添加 `merged_into` 字段
- 新增 5 个合并组虚拟条目（`soil-moisture`/`precipitation-static`/`era5-hazard-events`/`fy-omega-inversion`/`smap-omega-inversion`），含 `is_merged_group: true` + `members` 列表 + `presentation` + 占位 `extent`/`source_type`/`render_type`

**`layer_categories.json`**: 已就绪 ✅（`icon`/`accent_color`/`chip_tone` 已存在）

#### 1.5 更新 `layer_catalog.py`

- `get_layer_catalog()` 在 `LayerCatalogResponse` 中包含 `categories`
- `_load_seed_descriptors()` 保持现有 mtime 缓存逻辑

#### 1.6 OpenAPI 再生成

- 运行后端启动 → `openapi.json` 自动更新
- 前端 `npm run check:openapi` 验证类型同步

### Phase 2: 构建时代码生成

#### 2.1 创建 `Tools/generate_catalog_seeds.py`

读取后端 JSON → 转换为前端格式 → 写入 `catalog-seeds.generated.json`

关键转换:
- `LayerSourceDef.source_id` → `LayerSource.id`（snake_case → camelCase）
- `LayerDescriptor` → `LayerCatalogItem`（字段名映射 + `presentation` 展开）
- `LayerCategoryDef` → `LayerCategory`（snake_case → camelCase）
- 合并组虚拟条目 → `LayerCatalogItem` with `isMergedGroup: true` + `members: string[]`

#### 2.2 npm 脚本 + prebuild 钩子

```json
"gen:catalog": "python ../../Tools/generate_catalog_seeds.py",
"prebuild": "npm run gen:catalog"
```

#### 2.3 简化 `check_catalog_drift.py`

- 移除 `FE_ONLY_ALLOWLIST`（合并组已在后端 JSON）
- 移除 presentation 交叉检查（codegen 保证）
- 改为 generated JSON ↔ backend JSON 内容 hash 比较

### Phase 3: 前端重构

#### 3.1 重构 `catalog.ts`

- 删除所有 `SOURCE_XXX` 常量（~500 行）
- 删除硬编码 `LAYER_LIBRARY` 数组（~800 行）
- 删除硬编码 `LAYER_CATEGORIES`（~50 行）
- 替换为 `import catalogData from './catalog-seeds.generated.json'`
- 保留 derived helpers（`MERGED_LAYER_GROUPS` 从 `isMergedGroup` 派生）

#### 3.2 更新 `types.ts`

`LayerCatalogItem` 新增:
- `isMergedGroup?: boolean`
- `members?: string[]`

#### 3.3 更新 `catalog-builders.ts`

**关键修复 G1**: `buildRuntimeLayerLibraryItem()` line 255:
```typescript
// Before: sources: fallback?.sources ?? [],
// After:
sources: descriptor.sources?.length
  ? descriptor.sources.map(s => ({
      id: s.source_id,
      name: s.name,
      description: s.description,
      urlTemplate: s.url_template,
      needsAuth: s.needs_auth,
      needsBackendTransform: s.needs_backend_transform,
      coordSys: s.coord_sys as LayerSource['coordSys'],
      updateFrequency: s.update_frequency,
      attribution: s.attribution,
    }))
  : fallback?.sources ?? [],
```

**关键修复 G4**: `mergedInto` 从后端 descriptor 获取:
```typescript
mergedInto: descriptor.merged_into ?? fallback?.mergedInto,
```

#### 3.4 更新 `catalog-runtime.ts`

**关键修复 G2**: `ensureRuntimeLayerCatalog()` 存储 categories:
```typescript
.then((response) => {
  runtimeLayerCatalog.value = Object.fromEntries(
    response.items.map((item) => [item.layer_id, item]),
  )
  if (response.categories?.length) {
    runtimeLayerCategories.value = response.categories
  }
  deps.onCatalogLoaded?.()
})
```

**关键修复 G3**: 合并组从 runtime descriptor 派生:
```typescript
// Before: for (const [mergedCatalogId, sourceIds] of MERGED_LAYER_GROUPS) {
// After: 从 runtimeLayerCatalog 中查找 is_merged_group 条目
const mergedGroupDescriptors = Object.values(runtimeLayerCatalog.value)
  .filter(d => d.is_merged_group)
```

### Phase 4: 清理与验证

- `.gitignore` 添加 `catalog-seeds.generated.json`
- CI 添加 `gen:catalog` + `check:catalog` 步骤
- 完整回归：`check:catalog` + `check:openapi` + `pytest` + `npm run test` + `npm run lint` + `npm run build` + `pre-commit run --all-files`

### 文件变更清单

| 文件 | 变更类型 | Phase |
|------|---------|-------|
| `Code/shared/contracts/api_contracts.py` | 修改：新增 `LayerSourceDef`；扩展 `LayerDescriptor`/`LayerCatalogResponse` | 1.1-1.3 |
| `Code/backend/app/catalog_seeds/layer_descriptors.json` | 修改：添加 `sources`/`merged_into`/`is_merged_group`/`members` | 1.4 |
| `Code/backend/app/services/layer_catalog.py` | 修改：`get_layer_catalog()` 含 `categories` | 1.5 |
| `Code/frontend/openapi.json` | 再生成 | 1.6 |
| `Code/frontend/src/services/runtime-api.ts` | 再生成（OpenAPI types） | 1.6 |
| `Tools/generate_catalog_seeds.py` | 新增 | 2.1 |
| `Code/frontend/package.json` | 修改：添加 `gen:catalog`/`prebuild` | 2.2 |
| `Tools/check_catalog_drift.py` | 修改：简化为 hash 校验 | 2.3 |
| `Code/frontend/src/stores/layers/catalog.ts` | 重构：~1500 行 → ~200 行 | 3.1 |
| `Code/frontend/src/stores/layers/types.ts` | 修改：新增 `isMergedGroup`/`members` | 3.2 |
| `Code/frontend/src/stores/layers/catalog-builders.ts` | 修改：sources 从后端取 + mergedInto 从后端取 | 3.3 |
| `Code/frontend/src/stores/layers/catalog-runtime.ts` | 修改：存储 categories + 合并组从 descriptor 派生 | 3.4 |
| `.gitignore` | 修改：添加 generated JSON | 4 |
| `.github/workflows/ci.yml` | 修改：build 前添加 gen:catalog | 4 |

### 验证步骤

```bash
# Phase 1 验证
Env/Python312/python.exe -c "from shared.contracts.api_contracts import LayerSourceDef, LayerDescriptor; print('OK')"
Env/Python312/python.exe launch.py start fastapi
curl http://127.0.0.1:8000/layers | python -m json.tool | head -80
# 确认响应包含 sources、merged_into、categories 字段

# Phase 2 验证
cd Code/frontend && npm run gen:catalog
python ../../Tools/check_catalog_drift.py

# Phase 3 验证
cd Code/frontend && npm run test && npm run lint && npm run build

# Phase 4 完整回归
cd Code/frontend && npm run check:catalog && npm run check:openapi
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= \
  Env/Python312/python.exe -m pytest Test/backend -q -p no:cacheprovider --basetemp="Test/.pytest-be"
cd Code/frontend && npm run test && npm run lint && npm run build
pre-commit run --all-files
```

### Follow-up Checks (max 2)

1. **OpenAPI 契约同步**：Phase 1.6 后验证 `runtime-api.ts` 中 `LayerDescriptor` 类型包含 `sources`/`merged_into`/`is_merged_group`/`members` 字段 — 使用 `api-design-and-compatibility` specialist 评估字段命名与类型兼容性
2. **合并组虚拟条目验证**：Phase 1.4 后启动后端，确认 `GET /layers` 返回的虚拟条目通过 Pydantic 验证且前端能正确渲染合并组下拉 — 关注 `extent`/`source_type` 占位值是否导致 `run_readiness` 误判
