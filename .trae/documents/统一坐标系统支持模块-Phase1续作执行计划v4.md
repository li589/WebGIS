# 统一坐标系统支持模块 — Phase 1 续作执行计划 v4

> **背景**：[v3 执行计划](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/.trae/documents/统一坐标系统支持模块-Phase1续作执行计划v3.md) 已被用户批准，但因上下文中断未执行任何改动。本 v4 计划是 v3 的**接续执行版**——v3 的代码片段、用户决策、Phase 1 探索结果全部仍然有效，v4 仅做：① 本轮 Phase 1 状态再验证；② 标注 2 处与 v3 描述的细微差异；③ 给出紧凑的执行路线图。
>
> **不重新决策**：v3 锁定的所有决策（CRS 扩展到 13 项、改 raster_preview_service.py 生产代码、保留 deprecated 垫片、OverlaySpec.crs 默认 WGS84、前端预览+后端收口、显式 lng_offset/lat_offset 字段、不做双点校准）一律沿用。

## 一、本轮 Phase 1 状态再验证（2026-07-19）

### 1.1 已验证：v3 计划批准后**零改动**

| 文件 | v3 期望状态 | 本轮验证 | 结论 |
|---|---|---|---|
| [Code/backend/app/services/raster_preview_service.py:80](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/raster_preview_service.py#L80) | `numpy.ma.getmaskarray(masked_array)` | 仍为 `numpy.where(masked_array.mask, 0, 255)` | ❌ Task 6.3-fix 待执行 |
| [Code/backend/app/services/raster_preview_service.py:194](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/raster_preview_service.py#L194) | 同上 | 仍为 `numpy.where(masked_array.mask, 0, 255)` | ❌ Task 6.3-fix 待执行 |
| [Code/backend/app/services/crs/crs_registry.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/crs_registry.py) | 13 项 CRS | 仍为 9 项（docstring 仍写"Phase 1 含 9 个"） | ❌ Task 6.4.1 待执行 |
| [Code/backend/app/services/crs/_gcj_bd.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/_gcj_bd.py) | 6 函数（含 `gcj02_to_bd09`） | 仍为 5 函数 | ❌ Task 6.4.2 待执行 |
| [Code/backend/app/services/crs/_crs_detector.py:266-279](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/_crs_detector.py#L266-L279) | GK/Lambert 启发式增强 | 仍为简单 UTM 50N 默认 | ❌ Task 6.4.3 待执行 |
| [Code/backend/tests/test_import_raster_crs.py:98-107](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/test_import_raster_crs.py#L98-L107) | `test_returns_13_items` + `count == 13` | 仍为 `test_returns_9_items` + `count == 9` | ❌ Task 6.4.7 待执行 |
| `Code/frontend/src/services/crs/` 目录 | 7 文件 | 目录不存在 | ❌ Task 7 待执行 |
| 其余前端集成点（data-import.ts/useDataImportFlow.ts/CsvImportDialog.vue/imported-raster.ts/layers/index.ts/overlay-image-module.ts） | v3 描述状态 | 与 v3 描述一致 | ❌ Task 8/9/10 待执行 |

### 1.2 与 v3 描述的 2 处差异（需在执行时注意）

**差异 1：`_crs_transformer.py` 已有完整加密系路由，Task 6.4.4 可降级为可选**

v3 计划 Task 6.4.4 提到「加密系路由表增加 `gcj02_to_bd09` 直连路径」。本轮验证 [_crs_transformer.py:247-250](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/_crs_transformer.py#L247-L250) 发现现有代码已通过 `gcj02_to_wgs84` + `wgs84_to_bd09` 两步中转实现 GCJ02→BD09（结果正确，仅多一次 WGS84 中转）。

**决策**：
- `gcj02_to_bd09` 仍需添加到 `_gcj_bd.py`（与前端对称，是 Task 6.4.2 的硬要求）
- `_crs_transformer.py` 的直连路由优化**改为可选**：执行时若发现现有两步中转测试通过，**不强制**新增直连分支（避免引入未经测试的代码路径）。如新增，需配套 1 个测试。

**差异 2：`CsvImportDialog.vue` 的 `_proj4Convert` 签名与 v3 片段不同**

v3 Task 9.3 代码片段写的是 `_proj4Convert(lng, lat, fromCrs)` 三参版本，实际 [CsvImportDialog.vue:95-98](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/toolbar/CsvImportDialog.vue#L95-L98) 是 `_proj4Convert(x, y)` 两参版本（fromCrs 从 `crs.value` ref 取）。

**决策**：Task 9.3 执行时按实际签名替换为 `_convertPoint(x, y)`（内部用 `crs.value`），不要照抄 v3 的三参签名。同时注意 `previewCoordsAsync` watch 中的调用点（约第 102-110 行）也要同步改名。

### 1.3 其他确认事项

- `CsvImportDialog.vue` 的 `CRS_OPTIONS` 已硬编码包含 EPSG:4527/4528/4529（3 个 GK zone）—— Task 9.3 改为动态拉取后，13 项 CRS 中这 3 项原本就在，新增的是 GCJ02/BD09/4258/6933/3035 共 5 项。
- `proj4@^2.20.9` + `@types/proj4@^2.5.6` 已装（v3 已确认）。
- v3 Task 6.4.5/6.4.6 的测试文件追加（`test_crs_detector.py` +6 测试 / `test_crs_transformer.py` +2 测试）仍按 v3 执行。

## 二、执行路线图（8 个 Task，引用 v3 对应章节）

> 每个任务只给「执行要点 + v3 引用」，**代码片段以 v3 为准**。v4 不重复贴代码。

### Task 6.3-fix — 修复 raster_preview_service.py 标量 mask bug（5 分钟）

**执行要点**：
1. Edit [raster_preview_service.py:80](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/raster_preview_service.py#L80)：`masked_array.mask` → `numpy.ma.getmaskarray(masked_array)`
2. Edit [raster_preview_service.py:194](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/raster_preview_service.py#L194)：同上
3. Edit [test_import_raster_crs.py:32-37](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/test_import_raster_crs.py#L32-L37) fixture docstring：删除"rasterio edge case"错误说法，改为"标量 mask bug（已修复）"
4. 验证：`cd Code\backend; python -m pytest tests/test_import_raster_crs.py -v` → 期望 12/12 通过

**v3 引用**：[v3 §Task 6.3-fix](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/.trae/documents/统一坐标系统支持模块-Phase1续作执行计划v3.md)（第 58-96 行）

---

### Task 6.4 — 后端 CRS 扩展 9 → 13 项（30 分钟）

**6.4.1** Edit [crs_registry.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/crs_registry.py)：在 `_CRS_DEFS` 末尾追加 4 项 CRSDef（EPSG:4527/4528/4529 + EPSG:3035），同时更新模块 docstring 从"9 个"改"13 个"。

**6.4.2** Edit [_gcj_bd.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/_gcj_bd.py)：追加 `gcj02_to_bd09(lng, lat) -> CoordinatePoint`（v3 第 150-157 行代码）。

**6.4.3** Edit [_crs_detector.py:266-279](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/_crs_detector.py#L266-L279)：把简单 UTM 50N 默认分支替换为 v3 第 162-216 行的三分支（GK zone 39/40/41 → Lambert Europe → 默认 UTM 50N）。

**6.4.4**（可选）Edit [_crs_transformer.py:247-250](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/_crs_transformer.py#L247-L250)：把 GCJ02→BD09 从两步中转改为直连 `gcj02_to_bd09`。**若 6.4.6 测试通过则跳过此项**（参见 §1.2 差异 1）。

**6.4.5** Edit [test_crs_detector.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/test_crs_detector.py)：追加 6 个测试（v3 第 220-226 行清单）。

**6.4.6** Edit [test_crs_transformer.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/test_crs_transformer.py)：追加 2 个测试（GK 4527→WGS84 / Lambert 3035→WGS84）。

**6.4.7** Edit [test_import_raster_crs.py:98-107](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/test_import_raster_crs.py#L98-L107)：`test_returns_9_items` → `test_returns_13_items`，`count == 9` → `count == 13`，expected 集合追加 `{"EPSG:4527", "EPSG:4528", "EPSG:4529", "EPSG:3035"}`。

**验证**：
```powershell
cd Code\backend
python -m pytest tests/test_crs_transformer.py tests/test_crs_detector.py tests/test_import_raster_crs.py -v
# 期望: 23 + 63 + 12 = 98 测试全通过
```

**v3 引用**：[v3 §Task 6.4](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/.trae/documents/统一坐标系统支持模块-Phase1续作执行计划v3.md)（第 100-239 行）

---

### Task 7 — 前端 `services/crs/` 模块 + vitest（60 分钟）

**新建目录**：`Code/frontend/src/services/crs/`

**7.1** 新建 `crs-types.ts`：TypeScript 类型定义（CRSCategory/CRSDef/CRSOption/CoordinatePoint/TransformOptions/CRSDetectionResult）。

**7.2** 新建 `crs-registry.ts`：13 个 CRS 镜像后端，模块加载时 `proj4.defs()` 注册所有 EPSG proj4 串，导出 `CRS_REGISTRY`/`getCrs`/`listCrs`/`toApiPayload`，含 `GCJ-02`/`BD-09` 旧码归一化。

**7.3** 新建 `gcj-bd.ts`：从 [_gcj_bd.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/_gcj_bd.py) 直译，**保留 `_WGS84_A = 6378245.0`（Krasovsky 1940，故意保留）**。导出 6 函数：`gcj02ToWgs84`/`wgs84ToGcj02`/`bd09ToGcj02`/`gcj02ToBd09`/`bd09ToWgs84`/`wgs84ToBd09`。签名 `(lng, lat) => [number, number]`。

**7.4** 新建 `crs-transformer.ts`：`transformPoint`/`transformBounds`/`transformPointsBatch`，加密系走 gcj-bd.ts，EPSG 系走 proj4，偏移在 CRS 转换**后**应用（与后端一致）。

**7.5** 新建 `crs-detector.ts`：客户端 `detectFromBounds` 启发式（含 GK/Lambert 分支，与后端 6.4.3 增强版一致）。

**7.6** 新建 `index.ts`：`export * from './crs-types'` 等 5 行统一导出。

**7.7** 新建 `crs-transformer.test.ts`：~17 个 vitest 测试（registry 3 + transformer 10 + detector 4）。

**验证**：
```powershell
cd Code\frontend
npx vitest run src/services/crs/
# 期望: ~17 测试全通过
```

**v3 引用**：[v3 §Task 7](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/.trae/documents/统一坐标系统支持模块-Phase1续作执行计划v3.md)（第 243-737 行，含完整 TS 代码）

---

### Task 8 — `RasterImportConfirmDialog.vue` 弹窗组件（30 分钟）

**新建**：`Code/frontend/src/components/toolbar/RasterImportConfirmDialog.vue`

**执行要点**：
- Props: `visible`/`fileName`/`detectionResult`（含 source_crs/suggested_crs/needs_confirm/detection_notes/bounds）
- Emits: `confirm`({sourceCrs, lngOffset, latOffset}) / `cancel` / `skip`
- UI 三区块：① 检测信息只读 ② 用户校验（CRS 下拉从 `listCrs()` 拉 13 项 + lng/lat offset 输入 + 实时预览 WGS84 bounds）③ 操作按钮
- 样式复用 [CsvImportDialog.vue](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/toolbar/CsvImportDialog.vue) 的暗色 BEM 命名（`csv-dialog-overlay`/`csv-dialog-panel`/`panel-header`/`section-label`/`col-row`/`col-field`/`col-select`/`action-row`/`cancel-btn`/`confirm-btn`）
- `onMounted` 从 `services/crs` import `listCrs` + `transformBounds` 做实时预览

**v3 引用**：[v3 §Task 8](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/.trae/documents/统一坐标系统支持模块-Phase1续作执行计划v3.md)（第 741-792 行）

---

### Task 9 — 前端 4 个集成点修改（45 分钟）

**9.1** Edit [data-import.ts](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/services/data-import.ts)：
- 扩展 `RasterImportResult` 接口加 `source_crs?`/`suggested_crs?`/`needs_confirm?`/`detection_notes?`
- 新增 3 函数：`fetchCrsOptions` / `confirmRasterImport` / `transformPointBatch`

**9.2** Edit [useDataImportFlow.ts:79-101](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/composables/useDataImportFlow.ts#L79-L101)：
- `importRasterFile` 上传后根据 `needs_confirm` 分流：false → 直接 addImportedRasterLayer；true → 存 `pendingRasterConfirm` ref 触发弹窗
- 新增 `pendingRasterConfirm` ref + `confirmRasterCrs`/`skipRasterConfirm`/`cancelRasterConfirm` 三方法
- 返回值新增上述 4 项

**9.3** Edit [CsvImportDialog.vue:29-38, 87-110](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/toolbar/CsvImportDialog.vue#L29-L38)：
- 第 29-38 行 `CRS_OPTIONS` 常量 → 改为 `ref([])` + `onMounted` 调 `fetchCrsOptions()` 拉取 13 项
- 第 87-98 行 `_proj4Convert(x, y)`（**两参版本，参见 §1.2 差异 2**） → 替换为 `_convertPoint(x, y)` 调 `transformPoint(x, y, crs.value, 'EPSG:4326')`，移除动态 `import('proj4')` 与 `_proj4Lib` 缓存
- 第 102-110 行 watch 中调用点同步改名
- 模板中 `CRS_OPTIONS` 改为 `CRS_OPTIONS.value`（Vue 模板自动 unwrap，但 setup 内 JS 需 `.value`）

**9.4** Edit [imported-raster.ts:4-10](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/stores/layers/imported-raster.ts#L4-L10) + [layers/index.ts:852-878](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/stores/layers/index.ts#L852-L878)：
- `ImportedRasterPayload` 加 `sourceCrs?`/`lngOffset?`/`latOffset?`
- `addImportedRasterLayer` 增第 4 个可选参数 `options?: { sourceCrs?; lngOffset?; latOffset? }`，写入 `ActiveLayer` metadata

**v3 引用**：[v3 §Task 9](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/.trae/documents/统一坐标系统支持模块-Phase1续作执行计划v3.md)（第 795-1001 行）

---

### Task 10 — `overlay-image-module.ts` 防御性 bounds 校验（15 分钟）

**Edit** [overlay-image-module.ts:138-244](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/map/overlay-image-module.ts#L138-L244)：
- 新增 `_validateWgs84Bounds(bounds)` 函数：检查 NaN/Infinity、±180/±90 越界、west≥east/south≥north、跨 ±180° 经线
- `_addOverlay` 拿到 `boundsData.bounds` 后、`addSource` 前调校验：失败 → 不加载 + console.warn；valid+warning → 加载 + console.warn
- 检查 `meta.crs` 非 WGS84 时额外 warn

**v3 引用**：[v3 §Task 10](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/.trae/documents/统一坐标系统支持模块-Phase1续作执行计划v3.md)（第 1005-1048 行）

---

### Task 11.1 — TRAE-code-review skill 审查（20 分钟）

**调用** `Skill` tool with `name="TRAE-code-review"`

**审查范围**：所有 Task 6.3-fix ~ Task 10 改动文件（backend 7 文件 + frontend 9 文件/目录）

**审查重点**（用户要求"着重于旧代码使用和逻辑混乱问题"）：
1. **旧代码使用**：是否还有调用已废弃的 `coordinate_transform_service` 旧 API（应已迁移到 `services/crs/`）？是否还有 `_proj4Lib`/`import('proj4')` 残留？
2. **逻辑混乱**：CRS 转换路由是否清晰（加密系 vs EPSG 系分流）？偏移应用时机是否一致（转换后）？
3. **前后端一致性**：13 个 CRS 是否完全对齐？proj4 串是否与后端 `proj4_def` 完全一致？`gcj02_to_bd09` 算法是否前后端字节级一致？
4. **错误处理**：网络失败/CRS 不识别/bounds 越界是否优雅降级？
5. **类型安全**：TypeScript 类型是否完整（无 any 滥用）？

**v3 引用**：[v3 §Task 11.1](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/.trae/documents/统一坐标系统支持模块-Phase1续作执行计划v3.md)（第 1054-1079 行）

---

### Task 11.2 — 项目重启 + E2E 冒烟（15 分钟）

**重启**：
```powershell
# 后端
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Process python -ArgumentList "-u","-m","uvicorn","app.main:app","--host","0.0.0.0","--port","8000" -WindowStyle Hidden
# 前端
Get-Process node -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Process npm -ArgumentList "run","dev" -WindowStyle Hidden
```

**E2E 冒烟清单**（手动验证）：
- [ ] `GET /import/crs-options` 返回 13 项
- [ ] 上传 WGS84 TIF → needs_confirm=false → 直接显示
- [ ] 上传 UTM 50N TIF → needs_confirm=true → 弹窗 → 确认 → 显示正确
- [ ] 上传 Gauss-Krüger zone 39 TIF → suggested_crs='EPSG:4527' → 确认 → 显示正确
- [ ] 上传 Lambert Europe TIF → suggested_crs='EPSG:3035' → 确认 → 显示正确
- [ ] CSV 导入：选 GCJ02 → 点位转换到 WGS84 位置（与底图对齐）
- [ ] CSV 导入：选 BD09 → 点位转换到 WGS84 位置
- [ ] 图层 show/hide 性能正常
- [ ] 已有图层（SMAP/CLCD/Biomass 等）显示无回归
- [ ] 测量工具（measure 模式）正常工作

**v3 引用**：[v3 §Task 11.2](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/.trae/documents/统一坐标系统支持模块-Phase1续作执行计划v3.md)（第 1081-1109 行）

---

## 三、假设与风险

### 假设（沿用 v3）
- pyproj 3.7.2 已装，支持 EPSG:4527/4528/4529/3035（标准 EPSG，pyproj 内置）
- proj4.js 2.20.9 支持上述 4 个 CRS 的 proj4 串（手动 `proj4.defs()` 注册）
- 用户测试数据位于 `I:\Geograph_DataSet\`
- 前端 dev server 与后端 8000 代理已配好（`resolveApiUrl` 处理）

### 风险与缓解
1. **风险**：Task 6.4.4 若新增直连路由，可能引入未测试的代码路径
   - **缓解**：默认跳过（§1.2 差异 1），仅当 6.4.6 测试发现两步中转精度不足时才补
2. **风险**：Task 9.3 改 `CRS_OPTIONS` 为 ref 后，模板内若直接用 `CRS_OPTIONS` 不 unwrap 可能报错
   - **缓解**：Vue 3 模板自动 unwrap 顶层 ref，但 v-for 内访问需 `CRS_OPTIONS.value`（setup 内）/ 模板内 `CRS_OPTIONS` 即可。执行时检查模板用法
3. **风险**：Task 9.3 改名为 `_convertPoint` 后，若有其他文件 import `_proj4Convert` 会断
   - **缓解**：`_proj4Convert` 是 CsvImportDialog.vue 内部函数（前缀 `_`，未 export），无外部依赖
4. **风险**：proj4.js 对 EPSG:4527 的 false easting（39500000）数值精度
   - **缓解**：Task 7.7 vitest 含北京点转换测试，验证精度到 0.1°
5. **风险**：Task 11.2 重启时若 backend 进程未杀干净，端口 8000 占用
   - **缓解**：`Get-Process python | Stop-Process -Force` 后等 2 秒再启动；必要时用 `netstat -ano | findstr :8000` 查残留

## 四、验证步骤汇总

```powershell
# Backend 单测
cd Code\backend
python -m pytest tests/test_crs_transformer.py tests/test_crs_detector.py tests/test_import_raster_crs.py -v
# 期望: 23 + 63 + 12 = 98 测试全通过

# Frontend 单测
cd Code\frontend
npx vitest run src/services/crs/
# 期望: ~17 测试全通过

# Type check
cd Code\frontend
npx vue-tsc --noEmit
# 期望: 0 errors

# E2E 冒烟（手动，按 Task 11.2 清单）
```

## 五、执行顺序与预估

| 序号 | Task | 预估 | 依赖 |
|---|---|---|---|
| 1 | Task 6.3-fix | 5 min | 无 |
| 2 | Task 6.4（6.4.1~6.4.7，6.4.4 可选） | 30 min | 无 |
| 3 | Task 7（7.1~7.7） | 60 min | 无（前端镜像后端，可并行但建议串行以避免 proj4 串手抄错） |
| 4 | Task 8（RasterImportConfirmDialog.vue） | 30 min | Task 7 |
| 5 | Task 9（9.1~9.4） | 45 min | Task 7 + 8 |
| 6 | Task 10（overlay-image-module.ts） | 15 min | Task 9.4 |
| 7 | Task 11.1（TRAE-code-review） | 20 min | Task 6.3-fix ~ 10 全部完成 |
| 8 | Task 11.2（重启 + E2E） | 15 min | Task 11.1 通过 |

**总计预估：~3.5 小时**

执行时用 TodoWrite 跟踪 8 个 Task，每个 Task 完成立即 mark completed，再启下一个。
