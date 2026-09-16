# 地理数据分析系统 — 三任务实现计划

仓库：`D:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system`
前端：`Code/frontend/src`（Vue3+TS+MapLibre）；后端：`Code/backend/app`（FastAPI）
前置约束：**用户已有 42 个未提交改动（API Key 认证/密钥安全加固）不可动，需随本次一起提交。**

---

## 任务 1a：UI 文字面向地理科学工作者优化（分层变更清单）

### A 组：必改

#### A1 产品缩写图层名 → 中文名 + 缩写说明（核心）

先在 `Code/frontend/src/utils/workflow-expected-outputs.ts` 新增单一事实来源（运行对话框与占位层复用）：

```ts
export const PRODUCT_TAG_LABELS: Record<string, string> = {
  SM: 'SM（土壤湿度）',
  VOD: 'VOD（植被光学厚度）',
  OMEGA: 'ω（植被光学厚度）',
}
export function productTagLabel(tag: string): string {
  return PRODUCT_TAG_LABELS[tag] ?? tag
}
```

改动点（内部 productTag/归一逻辑 `normalizeProductTag` 一律不动，只改**显示名**）：

| 文件 | 行号 | 改法 |
|---|---|---|
| `stores/layers/index.ts` | 1868-1870 | `groupMember.name === 'OMEGA'` → 与 `productTagLabel('OMEGA')` 比较；`groupMember.name = displayName === 'OMEGA_BLOCK' ? 'OMEGA' : displayName` → 第二分支改为 `productTagLabel('OMEGA')` |
| `stores/layers/index.ts` | 1885, 1892 | `omegaPlaceholder.name || 'OMEGA'` / `omegaPlaceholder.name = 'OMEGA'` → 显示名 |
| `stores/layers/index.ts` | 1805-1809 | `(tag === 'OMEGA' ? 'OMEGA' : item.title...)` → `productTagLabel(tag)`（tag 已归一） |
| `stores/layers/index.ts` | 1980, 1986 | `orphan.name = 'OMEGA'`、`placeholder.name = 'OMEGA'` → 显示名（游离层并入逻辑） |
| `stores/layers/workflow-runner.ts` | 571 | `targets: tags.map((tag) => ({ name: tag, productTag: tag }))` → `name: productTagLabel(tag)`（532 行 tags 数组保持内部值） |
| `components/workflow/WorkflowRunDialog.vue` | 220 | `{{ outputTags.join(' / ') }}` → `{{ outputTags.map(productTagLabel).join(' / ') }}` |
| `components/workflow/WorkflowRunDialog.vue` | 238 | `{{ outputTags[idx] }}`（multi-name-tag）→ `{{ productTagLabel(outputTags[idx]) }}` |

**注意**：`WorkflowRunDialog.vue:243` 与 `workflow-expected-outputs.ts:68-76` 的默认产出图层名 `${prefix}_${tag}` **保持用 tag 原文**（作为文件名/后端标识），仅 UI 标签显示中文；若产品要求图层名也中文，再改为 `${prefix}_${productTagLabel(tag)}`（会改变提交给后端的 name，需评估）。

#### A2 课题组 → 科研数据

| 文件 | 行号 | 改法 |
|---|---|---|
| `ui-copy/brand.ts` | 20 | `ORG_LABEL = ... ?? '课题组'` → `?? '科研'` |
| `stores/layers/catalog.ts` | 50 | `${ORG_LABEL}数据` 自动变为「科研数据」（无需改） |
| `Code/backend/app/catalog_seeds/layer_descriptors.json` | 651, 699 | `display_name`「课题组模型模拟结果」→「科研模型模拟结果」；`run_readiness_summary`「课题组模型产出…」→「科研模型产出…」 |
| `Test/frontend/services/map-defaults.test.ts` | 49 | `expect(ORG_LABEL).toBe('课题组')` → `toBe('科研')`（**必须同步**） |

#### A3 缩写展开（歧义消除）

| 文件 | 行号 | 改法 |
|---|---|---|
| `stores/layers/catalog.ts` | 811, 817 | `name: '干旱指数 AI'` → `'干旱指数 AI（P/PET）'`；`sourceLabel: 'P/PET'` → `'P/PET（降水/蒸散比）'` |
| `stores/layers/catalog.ts` | 431-433 | `name: '土壤生态 DDCA'` → `'土壤生态 DDCA（双通道反演）'`；description 补一句「DDCA：双通道算法（DCA）反演」 |
| `stores/layers/catalog.ts` | 399, 410 | description 中 `'基于 SMCI 指标'` → `'基于 SMCI（土壤湿度指数）指标'` |
| `stores/layers/catalog.ts` | 388 | `'ESA CCI BIOMASS L4 AGB 合并产品'` → `'…AGB（地上生物量）合并产品'`（描述内展开一次） |
| `stores/layers/catalog.ts` | 276 | lab-model 描述 `'14 天 SM 均值'` → `'14 天 SM（土壤湿度）均值'` |

#### A4 中英混入

| 文件 | 行号 | 改法 |
|---|---|---|
| `ui-copy/analysis.ts` | 39, 43 | `'…已集成至地图 overlay。'` → `'…已集成至地图叠加层。'`；`'栅格 · GeoTIFF overlay'` → `'栅格 · GeoTIFF 叠加层'` |
| `components/LayerSidebar.vue` | 1130 | `'瓦片将回落 dense 源（Open-Meteo）'` → `'瓦片将回落到稠密数据源（Open-Meteo）'` |
| `components/InfoPanel.vue` | 1367 | `'Overlay ID'` → `'叠加层 ID'` |
| `components/InfoPanel.vue` | 1464-1465 | `'调度器'` kicker → `'任务调度'`（面向用户用语） |
| `components/InfoPanel.vue` | 1519, 1522 | `chunk` → `块`；`pixel` → `像素` |
| `components/InfoPanel.vue` | 1771 | `'可见 overlay 的采样对比'` → `'可见叠加层的采样对比'` |

#### A5 错别字

| 文件 | 行号 | 改法 |
|---|---|---|
| `ui-copy/analysis.ts` | 33 | `'直方/分區/时序'` → `'直方/分区/时序'` |
| `Code/backend/app/catalog_seeds/layer_descriptors.json` | 830 | `'斑块斑快破碎化'` → `'斑块破碎化'` |

#### A6 前后端命名/单位统一（**成对改动**）

| 数据项 | 前端 `stores/layers/catalog.ts` | 后端 `catalog_seeds/layer_descriptors.json` |
|---|---|---|
| **smap-sm-ts 年份** | L330 name `（2023-01）`→`（2025-12）`；L331 desc `2023 年 1 月，13 天`→`2025 年 12 月，31 天`；L832 sourceLabel `SMAP L3 (2023-01)`→`SMAP L3 (2025-12)` | L416 display_name 括号格式统一为 `（2025-12）`；L417 desc 已是 12 月（核对） |
| **单位** | 前端已 `m³/m³`（L758/829/1011/1043），不动 | **L440、L500、L733** `unit_label: "cm³/cm³"` → `"m³/m³"` |
| **sm-dec2025 命名** | L467、L1007 name `SM 土壤湿度（2025-12）`→`SMAP 土壤湿度（2025-12）`；L1014 sourceLabel `SmapSoil_VOD_SM v7.3`→`SMAP 土壤湿度反演 v7.3` | L476 display_name `多源融合土壤湿度 (2025.12)`→`SMAP 土壤湿度（2025-12）` |
| **soil-ddca 命名** | L431、L955 name `土壤生态 DDCA…`（保持，见 A3） | L709 display_name `DCA/SCA 校验土壤湿度`→`土壤生态 DDCA（2015-2022 时间序列）` |

#### A7 run_readiness 内部路径 → 地学描述（仅后端）

`layer_descriptors.json` 中 `run_readiness_summary` / `run_readiness_notes` 含内部路径/盘符表述的全部改为地学描述，例如：
- L465-467 `"数据源: Soil_Moisture/SMAP (SMAP_L3；当前盘上为 2023-01 样本集)"` → `"SMAP L3 逐日土壤湿度时序已就绪（2025 年 12 月）"`
- L524-526（SMAP_Soil_VOD_SM）、L761-763（DDCA）、L113-114（Biomass）、L346（DEM）、L585-587（FY MWRI）、L699-700、L819-820、L877-878 同理。

**重要**：`default_data_access_sources` 字段是算法运行时依赖，**绝不修改**；只改面向用户的 run_readiness_* 与 display_name/description。

#### A8 其他必改

| 文件 | 行号 | 改法 |
|---|---|---|
| `ui-copy/basemap.ts` | 27-28, 39 | `'Esri晕'`→`'Esri 晕渲'`；`'OTM'`→`'OpenTopoMap'`（SOURCE_SHORT 与 PROVIDER_SHORT 两处） |
| `ui-copy/workflow.ts` | 13, 25 | `'已入队'`→`'排队中'`；`'重试自'`→`'基于重试'`（retryOf 语义为重试起点） |
| `Test/frontend/ui-copy/data-io.test.ts` | 41-43 | 断言 `'Esri晕'`/`'OTM'` → 同步 `'Esri 晕渲'`/`'OpenTopoMap'`（**必须同步**） |

### B 组：建议改（设置页软化措辞，只动文字不动逻辑）

| 文件 | 行号 | 改法 |
|---|---|---|
| `components/settings/GeneralSettings.vue` | 96 | `'任务软时间限制，超时后抛 SoftTimeLimitExceeded'` → `'任务软时间限制，超时后任务将被终止'` |
| `components/settings/ApiKeySettings.vue` | 28-29 | `'已保存（session + localStorage 持久化）'`→`'已保存（浏览器会话 + 跨刷新）'`；`'仅本标签页 sessionStorage'`→`'仅当前浏览器标签页'` |
| `components/settings/ApiKeySettings.vue` | 470-471, 492 | `<code>sessionStorage</code>`→`<code>会话存储</code>`、`<code>localStorage</code>`→`<code>本地存储</code>`；`'跨会话记住到 localStorage'`→`'跨刷新记住'` |
| `components/settings/WeatherProviderSettings.vue` | 236, 249, 258 | `'天气源 Provider'`→`'天气源'`；`'系统按 Provider 优先级'`→`'系统按数据源优先级'`；`'暂无天气源 Provider'`→`'暂无天气源'` |
| `components/settings/RemoteStorageSettings.vue` | 241 | `'自动接受主机密钥（extra.host_key_policy=auto_add，仅内网）'` → `'自动接受主机密钥（仅内网）'` |

⚠️ ApiKeySettings 属于用户 42 个未提交改动之一（settings-local sessionStorage-first），**只允许改展示文案，严禁触碰存储逻辑**。

### C 组：慎改不动
- `components/workflow/node-forms/*.vue` 算法参数中英对照：**不动**（参数名须与后端 `algorithm_params` 键一致，改键会断参）。
- `GeneralSettings` 中 `Provider 根目录`、`Python Provider` 等运维字段：不动。
- 工作流引擎并发/软超时等运维配置标签：不动。

---

## 任务 1b：每条工作流可配置说明描述

后端链路已就绪（`workflow_definition_service.py` `_build_meta` L128-160 含 description，create L310-328 / update L362-365 透传）；前端 store `workflow-definitions.ts` `createNew`/`updateCurrent` 已支持 `description`。缺口：无编辑 UI + 运行对话框不展示。

### 1b-1 WorkflowEditorPanel.vue — header「属性」编辑对话框

script 改动：
```ts
// 属性编辑对话框（name/description）
const showPropsDialog = ref(false)
const editName = ref('')
const editDescription = ref('')

function openPropsDialog() {
  if (!currentDefinition.value) return
  editName.value = currentDefinition.value.name
  editDescription.value = currentDefinition.value.description ?? ''
  showPropsDialog.value = true
}

async function saveProps() {
  if (!currentDefinition.value || !editName.value.trim() || isReadonly.value) return
  await store.updateCurrent({
    name: editName.value.trim(),
    description: editDescription.value.trim() || undefined,
  })
  showPropsDialog.value = false
}
```
- `saveProps` 只传 name/description（后端 update 只更新提供的字段，nodes/links 保留），完成后 `headerWorkflowLabel`（L163-167）自动刷新。

template 改动：
- header-left（L585-587 `header-workflow-name` 之后）加按钮：
  `<button class="header-btn" type="button" :disabled="!hasDefinition || isReadonly" title="编辑名称与描述" @click="openPropsDialog">⚙ 属性</button>`
- 对话框参照新建对话框（L854-909）结构，新增 `.props-dialog`：标题「工作流属性」，`名称 *` input（v-model=editName）+ `描述` textarea（v-model=editDescription，rows=3，`.form-textarea` 样式已存在 L1254-1272），底部「保存/取消」。

### 1b-2 WorkflowRunDialog.vue — 展示描述

- props（L39-45）加：`workflowDescription?: string`
- template header（L172-175）subtitle 下加：
  `<p v-if="workflowDescription" class="dialog-description">{{ workflowDescription }}</p>`
- style 加 `.dialog-description { margin:.3rem 0 0; font-size:.56rem; color:#8aa0b6; line-height:1.5; }`

### 1b-3 调用处传参

`WorkflowEditorPanel.vue` L843-851（唯一调用方，已确认）：
```html
<WorkflowRunDialog
  :visible="showRunDialog"
  :workflow-id="currentDefinition?.workflow_id ?? ''"
  :workflow-name="currentDefinition?.name ?? ''"
  :workflow-description="currentDefinition?.description ?? ''"
  :linked-layer-id="currentLinkedLayerId"
  :engine="currentEngine"
  ...
/>
```

---

## 任务 2：点选/测量模式优化

### 2.1 Bug 修复：模式切换清除选中点

链路已验证：`ModeToolbar.vue:153-157` → `stores/ui.ts:262-264` → `map-canvas-runtime-watcher.ts:45-56` → `map-canvas-module-bundle.ts:219-222`（onInteractionModeChange 只 apply 交互/测量，**不清选点**）。

**改动 1**：`components/map/map-canvas-module-bundle.ts` L219-222
```ts
onInteractionModeChange: () => {
  mapInteractionModule.applyInteractionMode()
  measureModule.applyMeasureMode()
  const mode = options.getInteractionMode()
  if (mode !== 'select') {
    options.setSelectedHotspotId(null)
    options.emitHotspotSelect(null)   // 传导到 DashboardView.handleHotspotSelect → selectedHotspot=null
  }
},
```
（`setSelectedHotspotId`/`emitHotspotSelect` 已在 options 接口 L77-80 暴露）

**改动 2**：`views/DashboardView.vue` 增加 interactionMode watch（补在其现有 watch 群附近，uiStore 已 import，见 L1263）：
```ts
watch(
  () => uiStore.interactionMode,
  (mode) => {
    if (mode === 'select') return
    if (selectedMapPoint.value || selectedHotspot.value) {
      clearMapPointInspect()          // L751-757：清 selectedMapPoint/pointWeather/overlay 点值
      selectedHotspot.value = null
    }
  },
)
```

**InfoPanel 联动**：`selectedMapPoint` 置 null 后 `InfoPanel.vue` 的 `:selected-map-point` prop（DashboardView L1248）自动为 null，点查图表/Overlay 对比区随之隐藏，无需改 InfoPanel。

### 2.2 测量点优化（适度）

`components/map/measure-module.ts`：
1. **常量（L23-43 区）新增**：
   ```ts
   const POINT_RADIUS_FIRST = 8            // 首点强调半径
   const POINT_COLOR_FIRST = '#ffb84d'     // 首点琥珀色，区分路径蓝
   ```
2. **circle layer paint（L138-148）改为表达式**（MapLibre case / get）：
   ```ts
   paint: {
     'circle-radius': [
       'case',
       ['==', ['get', 'isFirst'], true], POINT_RADIUS_FIRST,
       POINT_RADIUS,
     ],
     'circle-color': [
       'case',
       ['==', ['get', 'isFirst'], true], POINT_COLOR_FIRST,
       LINE_COLOR,
     ],
     'circle-stroke-width': POINT_STROKE_WIDTH,
     'circle-stroke-color': '#ffffff',
   },
   ```
3. **syncGeoJSON 的 pointFeatures（L163-167）带首点标记**：
   ```ts
   const pointFeatures: GeoJSON.Feature<GeoJSON.Point>[] = points.map((p, i) => ({
     type: 'Feature',
     geometry: { type: 'Point', coordinates: [p.lng, p.lat] },
     properties: { isFirst: i === 0 },
   }))
   ```
4. **终点悬停态（可选、低成本）**：新增 `SOURCE_HOVER_POINT`/`LAYER_HOVER_POINT`（circle，r=4，色 `LINE_COLOR`，无描边）；`syncGeoJSON` 中 `isDrawing && hoverPoint` 时 setData 单点，否则空。约 +20 行。若保守，可仅依赖既有 preview 虚线（L194-216）表达悬停。

---

## 任务 3：测试 + 编译 + 提交

### 验证命令
- 前端类型检查：`cd Code/frontend && npx vue-tsc --noEmit`
- 前端测试：`cd Code/frontend && npm test`（现有 516+）
- 前端 lint/format：`npm run lint`；`npm run format:check`
- openapi drift：`npm run check:openapi`（后端 `scripts/check_openapi_drift.py`）
- catalog drift（如有）：`npm run check:catalog`
- 后端测试：`cd Test/backend && python -m pytest -q`（现有 608+；`test_archive_safe.py` 需真实 unrar，环境缺失时 `-k "not archive_safe"`）
- 后端 lint：`ruff check Code/backend/app`

### 提交策略（3 个 commit，安全改动隔离）
1. `chore(security): api key/secrets hardening` — **42 个未提交改动原样提交**（不夹带本次改动）
2. `feat(ui): geoscience-friendly copy + workflow description editing` — 任务 1a + 1b
3. `fix(map): clear selection on mode switch; emphasize measure start point` — 任务 2

### pre-commit 注意事项（.pre-commit-config.yaml 已验证）
- `ruff --fix`、`ruff-format`、`end-of-file-fixer`（Python/JSON）**会自动改写文件** → commit 后若文件被改，需**重新 `git add`** 再提交
- `frontend-eslint`（`npm run lint`）与 `frontend-prettier`（`format:check`）在 pre-commit 运行，失败会阻止提交 → 提交前本地先跑
- commit-msg 钩子要求 Conventional Commits 格式（已按上述前缀）

---

## 风险点

1. **catalog.ts ↔ layer_descriptors.json 成对遗漏**：smap-sm-ts 年份/单位、sm-dec2025 命名、soil-ddca 命名必须两侧同步，漏改会导致前端图层库名称与后端算法解析名称/单位不一致（drift 检查可兜底部分）。
2. **测试断言引用旧文案**（改文案必须同步更新）：
   - `Test/frontend/services/map-defaults.test.ts:49`（ORG_LABEL）
   - `Test/frontend/ui-copy/data-io.test.ts:41-43`（Esri晕/OTM）
   - `Test/frontend/utils/workflow-progress-format.test.ts:20`（progress 中 `OMEGA` 显示，若 progress 也接入显示映射则需更新；否则保留）
   - `Test/frontend/utils/workflow-expected-outputs.test.ts`（tags 用内部值，不受影响，勿误改）
3. **OMEGA 占位名改中文后内部匹配**：`normalizeProductTag(layer.runGroupProductTag || layer.name)`（index.ts L1792/1880/1976）依赖 `runGroupProductTag='OMEGA'` 兜底 → 改名时**必须保留 runGroupProductTag**，且 L1868/1966 的 name 字符串比较需同步替换为中文显示名。
4. **后端 `default_data_access_sources` 是算法运行时依赖**，只改展示字段（display_name/description/run_readiness_*），误改断数据源解析。
5. **ApiKeySettings 在用户 42 个未提交改动中**：B 组软化只改文案，严禁触碰 sessionStorage-first 存储逻辑。
6. **pre-commit 钩子自动改文件**：ruff/end-of-file-fixer 改后须重新 git add，否则出现 staged/unstaged 不一致。
7. **WorkflowRunDialog 新增 prop**：调用方仅 WorkflowEditorPanel 一处（已验证），新增 `workflowDescription` 为可选 prop 不破坏其他使用。
8. **MapLibre paint 表达式** `['get','isFirst']` 需在浏览器验证；hover 点与首点颜色/半径对比需肉眼确认可辨识。

---

## 已验证要点（探索/复查确认，执行时无需再验证）

- **任务 2 改动 1 依赖接口已存在**：`map-canvas-module-bundle.ts` options 接口已有 `setSelectedHotspotId`（L78）、`emitHotspotSelect`（L80）、`getInteractionMode`（L91）；`onInteractionModeChange`（L219-222）只 apply 交互/测量，确认不清选点。
- **DashboardView 已 import uiStore**（watch 可直接加）。
- **WorkflowRunDialog 唯一调用方** = WorkflowEditorPanel（`Code/frontend/src/components/workflow/WorkflowEditorPanel.vue` 约 L843-851），新增可选 prop 安全。
- **workflow description 后端链路**（create/update 透传 + JSON 持久化）已就绪，仅缺编辑 UI 与运行展示。
- **用户 42 个未提交改动**（API Key 安全加固）已确认：deps.py 认证收窄、encryption 64-hex/空 IV 策略、GEE 默认关、settings-local sessionStorage-first、4 个新测试。**原样提交，不夹带本次改动。**

## 执行顺序

1. **任务 1a A 组**（必改文案，含 catalog 前后端成对项 + 3 处测试断言同步）→ 前端 tsc/vitest 快速验证
2. **任务 1a B 组**（设置页软化文案，只动文字）
3. **任务 1b**（属性编辑对话框 + 运行展示）→ tsc 验证
4. **任务 2**（模式切换清选点 + 测量首点强调）→ tsc + 无头渲染验证
5. **全量回归**：vue-tsc / vitest / pytest（-k "not archive_safe"）/ eslint / prettier / check:openapi
6. **3 个 commit 提交推送**：①安全加固原样 → ②UI 文案+描述功能 → ③地图交互修复（注意 pre-commit 自动改文件后重新 git add）
