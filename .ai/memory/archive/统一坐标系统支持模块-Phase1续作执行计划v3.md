# 统一坐标系统支持模块 — Phase 1 续作执行计划 v3

> **背景**：[v2 执行计划](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/.trae/documents/统一坐标系统支持模块-Phase1续作执行计划v2.md) 已完成 Task 3-fix / 4 / 5 / 6.1 / 6.2，Task 6.3 有 8/12 测试通过。v2 计划对 Task 6.3-fix 的诊断错误（误判为 rasterio 极小栅格 edge case），实际根因是 numpy masked array 标量 bug。本计划接续完成 Task 6.3-fix + Task 6.4（CRS 扩展）+ Task 7~11。
>
> **用户原始需求**：覆盖 WGS84/ETRS89/EASE-Grid 2.0/CGCS2000/GCJ-02/BD-09 + 高斯-克吕格/UTM/Lambert/Web Mercator 的统一 CRS 模块，支持显式偏移字段，前端预览 + 后端收口，上传时检测 + 用户确认。
>
> **本计划基于用户两轮决策**：
> 1. **CRS 范围**：「完整覆盖所有列举 CRS」— 在现有 9 项基础上扩展高斯-克吕格（CGCS2000 3 度带北京/上海/东北 3 个 zone）+ 兰伯特等角圆锥（ETRS89 / LCC Europe）
> 2. **Bug 修复方式**：「改 raster_preview_service.py（推荐）」— 根治生产环境所有无 nodata 栅格的预览失败问题
>
> **不重新决策已锁定项**（垫片保留、OverlaySpec.crs 默认 WGS84、前端预览+后端收口、不做双点校准、显式 lng_offset/lat_offset 字段等）。

## 一、当前状态确认

### 1.1 已完成（不动）

| 文件 | 状态 |
|---|---|
| [Code/backend/app/services/crs/](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/) 整个包 | ✅ 6 文件：`crs_types.py`/`crs_registry.py`/`_gcj_bd.py`/`__init__.py`/`_crs_transformer.py`/`_crs_detector.py` |
| [Code/backend/app/services/coordinate_transform_service.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/coordinate_transform_service.py) | ✅ Task 4 deprecated 垫片，5 加密函数 + `transform_point` + `CoordinatePoint`/`CoordinateSystem` 全保留 |
| [Code/backend/app/services/overlay_registry.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/overlay_registry.py) | ✅ Task 5 `OverlaySpec.crs` 字段 + `meta_dict` 返回 `crs` |
| [Code/backend/app/services/raster_preview_service.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/raster_preview_service.py) | ✅ Task 6.1 `render_cog_preview_reprojected` 方法；❌ 第 80/194 行标量 mask bug（Task 6.3-fix 修复） |
| [Code/backend/app/api/routers/import_router.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/api/routers/import_router.py) | ✅ Task 6.2 4 新端点 + 3 Pydantic 模型 + `/import/raster` 返回 CRS 检测字段 |
| [Code/backend/tests/conftest.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/conftest.py) | ✅ Task 3-fix `PYTEST_DEBUG_TEMPROOT` 重定向 |
| [Code/backend/requirements.txt](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/requirements.txt) | ✅ Task 4 `pyproj>=3.6,<4` pin |
| [Code/backend/tests/test_crs_transformer.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/test_crs_transformer.py) | ✅ 21 测试全通过 |
| [Code/backend/tests/test_crs_detector.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/test_crs_detector.py) | ✅ 57 测试全通过（Task 6.4 扩展后需补 ~6 测试） |
| [Code/backend/tests/test_import_raster_crs.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/test_import_raster_crs.py) | ⚠️ 8 通过 / 4 失败（Task 6.3-fix 修复）；fixture 已改 32×32（但 docstring 错误说法需更新） |

### 1.2 Task 6.3 失败根因（本轮已验证）

**实际根因**（与 v2 计划诊断不同）：
- [raster_preview_service.py:80](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/raster_preview_service.py#L80): `alpha = numpy.where(masked_array.mask, 0, 255).astype("uint8")`
- [raster_preview_service.py:194](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/raster_preview_service.py#L194): 同上
- 当 `masked_array.mask` 是标量 `False`（无 nodata 数据常见），`numpy.where(False, 0, 255)` 返回 shape `()` 标量，`dataset.write(alpha, 4)` 报 `ValueError: Source shape (1,) is inconsistent with given indexes 1`
- 已验证：`band.mask type= bool value= False` / `alpha.shape= ()`

**影响范围**：所有无 nodata 值的生产栅格（不仅是测试），Task 6.3-fix 必须改生产代码。

### 1.3 前端集成点扫描结果（本轮 Phase 1 已扫描）

| 集成点 | 当前状态 | Task |
|---|---|---|
| `Code/frontend/src/services/crs/` | ❌ 不存在（全新创建） | Task 7 |
| [Code/frontend/src/services/data-import.ts:18-21](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/services/data-import.ts#L18-L21) | `RasterImportResult` 只有 `layer_id`/`bounds`，无 CRS 字段 | Task 9.1 |
| [Code/frontend/src/services/data-import.ts:162-227](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/services/data-import.ts#L162-L227) | `uploadRasterFile` 用 XHR + `resolveApiUrl('/import/raster')` | Task 9.1 |
| [Code/frontend/src/composables/useDataImportFlow.ts:79-101](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/composables/useDataImportFlow.ts#L79-L101) | `importRasterFile` 上传后直接 `addImportedRasterLayer`，无确认步骤 | Task 9.2 |
| [Code/frontend/src/components/toolbar/CsvImportDialog.vue:29-38](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/toolbar/CsvImportDialog.vue#L29-L38) | `CRS_OPTIONS` 硬编码 8 项（含 EPSG:4527/4528/4529 Gauss-Krüger，但缺 GCJ02/BD09/4258/6933/3035） | Task 9.3 |
| [Code/frontend/src/components/toolbar/CsvImportDialog.vue:95-98](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/toolbar/CsvImportDialog.vue#L95-L98) | `_proj4Convert` 用动态 import proj4，仅做 EPSG→EPSG:4326 | Task 9.3 |
| [Code/frontend/src/stores/layers/imported-raster.ts:4-10](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/stores/layers/imported-raster.ts#L4-L10) | `ImportedRasterPayload` 只有 `overlayLayerId`/`bounds`/`fileName`，无 CRS/offset 字段 | Task 9.4 |
| [Code/frontend/src/stores/layers/index.ts:852-878](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/stores/layers/index.ts#L852-L878) | `addImportedRasterLayer(name, overlayLayerId, bounds?)` — 3 参数，无 CRS 字段 | Task 9.4 |
| [Code/frontend/src/components/map/overlay-image-module.ts:138-244](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/map/overlay-image-module.ts#L138-L244) | `_addOverlay` 无 bounds 校验，直接 `addSource` | Task 10 |
| [Code/frontend/package.json:20-30](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/package.json#L20-L30) | ✅ `proj4@^2.20.9` + `@types/proj4@^2.5.6` 已装 | — |
| [Code/frontend/src/services/data-import.test.ts](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/services/data-import.test.ts) | vitest 模式：`describe/it/expect`，`*.test.ts` 命名 | Task 7 |

## 二、Proposed Changes

### Task 6.3-fix：修复 raster_preview_service.py 标量 mask bug

**改写**：[Code/backend/app/services/raster_preview_service.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/raster_preview_service.py)

**改动 1**：第 80 行（`render_cog_preview`）
```python
# 改前
alpha = numpy.where(masked_array.mask, 0, 255).astype("uint8")
# 改后
alpha = numpy.where(numpy.ma.getmaskarray(masked_array), 0, 255).astype("uint8")
```

**改动 2**：第 194 行（`render_cog_preview_reprojected`）
```python
# 改前
alpha = numpy.where(masked_array.mask, 0, 255).astype("uint8")
# 改后
alpha = numpy.where(numpy.ma.getmaskarray(masked_array), 0, 255).astype("uint8")
```

**根因说明**：`masked_array.mask` 在无 nodata 时为标量 `False`，`numpy.where(False, 0, 255)` 返回 shape `()` 标量，导致 `dataset.write(alpha, 4)` 报 `Source shape (1,) is inconsistent`。`numpy.ma.getmaskarray()` 始终返回与数据同形状的布尔数组，根治此问题。**影响所有无 nodata 的生产栅格**，不仅是测试。

**改动 3**：[Code/backend/tests/test_import_raster_crs.py:32-37](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/test_import_raster_crs.py#L32-L37) 更新 fixture docstring（删除错误的 rasterio edge case 说法）：
```python
@pytest.fixture
def wgs84_geotiff(tmp_path: Path) -> Path:
    """合成 WGS84 GeoTIFF（32×32 像素，覆盖中国区域 116-117E, 39-40N）。

    32×32 是常见的小栅格尺寸，更接近真实数据。原 2×2 fixture 暴露了
    ``raster_preview_service.py`` 的标量 mask bug（已修复）。
    """
```

**验证**：
```powershell
cd Code\backend
python -m pytest tests/test_import_raster_crs.py -v
# 期望: 12/12 通过
```

---

### Task 6.4：扩展后端 CRS 注册表（新增 4 项，9 → 13 项）

**目的**：覆盖用户列举的高斯-克吕格 + 兰伯特等角圆锥投影，落地"完整覆盖"决策。

**改写文件 1**：[Code/backend/app/services/crs/crs_registry.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/crs_registry.py)

在 `_CRS_DEFS` 列表末尾追加 4 项（UTM 50N 之后）：
```python
    # ── 高斯-克吕格（CGCS2000 3 度带）──────────────────────────────
    CRSDef(
        code="EPSG:4527",
        label="CGCS2000 / 3度带 高斯-克吕格 zone 39（北京，CM 117E）",
        category=CRSCategory.PROJECTED,
        epsg=4527,
        proj4_def="+proj=tmerc +lat_0=0 +lon_0=117 +k=1 +x_0=39500000 +y_0=0 +ellps=GRS80 +units=m +no_defs",
        area="China",
    ),
    CRSDef(
        code="EPSG:4528",
        label="CGCS2000 / 3度带 高斯-克吕格 zone 40（上海，CM 120E）",
        category=CRSCategory.PROJECTED,
        epsg=4528,
        proj4_def="+proj=tmerc +lat_0=0 +lon_0=120 +k=1 +x_0=40500000 +y_0=0 +ellps=GRS80 +units=m +no_defs",
        area="China",
    ),
    CRSDef(
        code="EPSG:4529",
        label="CGCS2000 / 3度带 高斯-克吕格 zone 41（东北，CM 123E）",
        category=CRSCategory.PROJECTED,
        epsg=4529,
        proj4_def="+proj=tmerc +lat_0=0 +lon_0=123 +k=1 +x_0=41500000 +y_0=0 +ellps=GRS80 +units=m +no_defs",
        area="China",
    ),
    # ── 兰伯特等角圆锥投影（欧洲）──────────────────────────────────
    CRSDef(
        code="EPSG:3035",
        label="ETRS89-extended / LCC Europe（欧洲兰伯特等角圆锥）",
        category=CRSCategory.PROJECTED,
        epsg=3035,
        proj4_def="+proj=lcc +lat_1=35 +lat_2=65 +lat_0=52 +lon_0=10 +x_0=4000000 +y_0=2800000 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs",
        area="Europe",
    ),
```

同时更新模块 docstring 第 1-8 行：把"Phase 1 含 9 个常用 CRS"改为"含 13 个常用 CRS（Phase 1 扩展版）"，并把 Phase 2 待扩展项调整为"全 UTM 系列 / 全 GK zone / EASE-Grid 变体"。

**改写文件 2**：[Code/backend/app/services/crs/_gcj_bd.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/_gcj_bd.py)

追加缺失的 `gcj02_to_bd09` 函数（与前端对称，是 `bd09_to_gcj02` 的逆运算）：
```python
def gcj02_to_bd09(lng: float, lat: float) -> CoordinatePoint:
    """GCJ-02 → BD-09（百度坐标系正向偏移）。"""
    x = lng
    y = lat
    z = sqrt(x * x + y * y) + 0.00002 * sin(y * pi * 3000.0 / 180.0)
    theta = atan2(y, x) + 0.000003 * cos(x * pi * 3000.0 / 180.0)
    return CoordinatePoint(lng=z * cos(theta), lat=z * sin(theta))
```

**更新文件 3**：[Code/backend/app/services/crs/_crs_detector.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/_crs_detector.py) — `detect_from_bounds` 增强启发式（仅影响无 CRS 元数据的兜底路径）：

把第 266-279 行的"投影坐标系：大数值"分支细化为：
```python
        # 投影坐标系：大数值
        if abs(west) > 180 or abs(east) > 180:
            # 高斯-克吕格 3 度带 false easting 模式：X 在 39500000-41500000 范围
            # （zone 39/40/41，覆盖北京/上海/东北）
            if 39000000 < west < 42000000 or 39000000 < east < 42000000:
                # 按中央子午线推断 zone
                mid_x = (west + east) / 2
                zone = int(mid_x // 1000000)
                if zone == 39:
                    suggested = "EPSG:4527"
                elif zone == 40:
                    suggested = "EPSG:4528"
                elif zone == 41:
                    suggested = "EPSG:4529"
                else:
                    suggested = "EPSG:4527"
                return CRSDetectionResult(
                    source_crs=suggested,
                    confidence=0.5,
                    method="bounds_heuristic",
                    suggested_crs=suggested,
                    needs_user_confirm=True,
                    notes=(
                        f"bounds ({west:.0f},{south:.0f},{east:.0f},{north:.0f}) "
                        f"匹配高斯-克吕格 3 度带 false easting 模式（zone {zone}），"
                        f"建议 {suggested}，需用户确认"
                    ),
                )
            # Lambert Europe (EPSG:3035) 范围：X 1500000-7500000, Y 1000000-6000000
            if 1000000 < west < 8000000 and 1000000 < east < 8000000:
                return CRSDetectionResult(
                    source_crs="EPSG:3035",
                    confidence=0.3,
                    method="bounds_heuristic",
                    suggested_crs="EPSG:3035",
                    needs_user_confirm=True,
                    notes=(
                        f"bounds ({west:.0f},{south:.0f},{east:.0f},{north:.0f}) "
                        f"在 Lambert Europe 范围内，建议 EPSG:3035，需用户确认"
                    ),
                )
            # 默认 UTM 50N（中国区域最常见的投影系）
            return CRSDetectionResult(
                source_crs="EPSG:32650",
                confidence=0.3,
                method="bounds_heuristic",
                suggested_crs="EPSG:32650",
                needs_user_confirm=True,
                notes=(
                    f"bounds ({west:.2f},{south:.2f},{east:.2f},{north:.2f}) "
                    f"数值超出 ±180，推断为投影坐标系（默认建议 UTM 50N，需用户确认）"
                ),
            )
```

**更新文件 4**：[Code/backend/app/services/crs/_crs_transformer.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/_crs_transformer.py) — 加密系路由表增加 `gcj02_to_bd09` 直连路径（如果现有代码用通用路径经 WGS84 中转，需改为直连提升精度）。先读后改，仅在确认当前路由表缺 `gcj02_to_bd09` 时追加。

**改写文件 5**：[Code/backend/tests/test_crs_detector.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/test_crs_detector.py) — 追加 6 个测试覆盖新 CRS：
- `test_detect_from_bounds_gauss_kruger_zone39` — bounds `(39500000, 4400000, 39510000, 4410000)` → 建议_EPSG:4527
- `test_detect_from_bounds_gauss_kruger_zone40` — bounds `(40500000, 3500000, 40510000, 3510000)` → 建议_EPSG:4528
- `test_detect_from_bounds_gauss_kruger_zone41` — bounds `(41500000, 4500000, 41510000, 4510000)` → 建议_EPSG:4529
- `test_detect_from_bounds_lambert_europe` — bounds `(4000000, 2500000, 4500000, 3000000)` → 建议_EPSG:3035
- `test_detect_from_raster_gauss_kruger_4527` — 合成 EPSG:4527 TIF → detect_from_raster 识别为 EPSG:4527
- `test_detect_from_raster_lambert_3035` — 合成 EPSG:3035 TIF → detect_from_raster 识别为 EPSG:3035

**改写文件 6**：[Code/backend/tests/test_crs_transformer.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/test_crs_transformer.py) — 追加 2 个测试覆盖新 CRS 转换：
- `test_transform_gauss_kruger_4527_to_wgs84` — 北京点 (39500000+500000, 4440000) → WGS84 ~ (116.39, 39.91)
- `test_transform_lambert_3035_to_wgs84` — 欧洲点 (4321000, 3210000) → WGS84 ~ (10.5, 51.0)

**更新文件 7**：[Code/backend/tests/test_import_raster_crs.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/test_import_raster_crs.py) — `test_returns_9_items` 改为 `test_returns_13_items`，期望 codes 集合追加 `{"EPSG:4527", "EPSG:4528", "EPSG:4529", "EPSG:3035"}`。

**验证**：
```powershell
cd Code\backend
python -m pytest tests/test_crs_transformer.py tests/test_crs_detector.py tests/test_import_raster_crs.py -v
# 期望: 全部通过（21+2 + 57+6 + 12 = 98 测试）
```

---

### Task 7：前端 `services/crs/` 模块 + vitest

**新建目录**：`Code/frontend/src/services/crs/`

**文件清单**（6 个源文件 + 1 个测试文件）：

#### 7.1 `crs-types.ts`
TypeScript 类型定义（镜像后端 `crs_types.py`）：
```ts
export type CRSCategory = 'geographic' | 'encrypted' | 'projected'

export interface CRSDef {
  code: string         // 'EPSG:4326' | 'GCJ02' | ...
  label: string
  category: CRSCategory
  epsg: number | null
  proj4Def: string | null
  area: string
  deprecated: boolean
}

export interface CRSOption {
  code: string
  label: string
  category: CRSCategory
  area: string
  deprecated: boolean
}

export interface CoordinatePoint {
  lng: number
  lat: number
}

export interface TransformOptions {
  lngOffset?: number
  latOffset?: number
}

export interface CRSDetectionResult {
  sourceCrs: string
  confidence: number       // 0~1
  method: 'rasterio_crs' | 'geojson_crs' | 'bounds_heuristic' | 'default'
  suggestedCrs: string
  needsUserConfirm: boolean
  notes: string
}
```

#### 7.2 `crs-registry.ts`
镜像后端 13 个 CRS，提供 `CRS_REGISTRY`/`getCrs(code)`/`listCrs(category?)`/`toApiPayload()`：
- 与后端 `_CRS_DEFS` 列表完全对齐（13 项）
- `getCrs` 兼容旧码 `'GCJ-02'`/`'BD-09'` → `'GCJ02'`/`'BD09'` 归一化（同后端 `_normalize_legacy_code`）
- proj4.defs() 注册所有 13 个 CRS 的 proj4 串（在模块加载时一次性注册）

```ts
import proj4 from 'proj4'
import type { CRSDef, CRSOption, CRSCategory } from './crs-types'

const _CRS_DEFS: CRSDef[] = [
  // ── 地理坐标系 ──
  { code: 'EPSG:4326', label: 'WGS84 经纬度', category: 'geographic', epsg: 4326,
    proj4Def: '+proj=longlat +datum=WGS84 +no_defs', area: 'Global', deprecated: false },
  { code: 'EPSG:4490', label: 'CGCS2000 国家大地坐标系', category: 'geographic', epsg: 4490,
    proj4Def: '+proj=longlat +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +no_defs', area: 'China', deprecated: false },
  { code: 'EPSG:4258', label: 'ETRS89 欧洲地理坐标系', category: 'geographic', epsg: 4258,
    proj4Def: '+proj=longlat +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +no_defs', area: 'Europe', deprecated: false },
  // ── 加密坐标系 ──
  { code: 'GCJ02', label: 'GCJ-02 火星坐标系（国测局加密）', category: 'encrypted', epsg: null,
    proj4Def: null, area: 'China', deprecated: false },
  { code: 'BD09', label: 'BD-09 百度坐标系', category: 'encrypted', epsg: null,
    proj4Def: null, area: 'China', deprecated: false },
  // ── 投影坐标系 ──
  { code: 'EPSG:3857', label: 'Web Mercator（伪墨卡托）', category: 'projected', epsg: 3857,
    proj4Def: '+proj=merc +a=6378137 +b=6378137 +lat_ts=0 +lon_0=0 +x_0=0 +y_0=0 +k=1 +units=m +nadgrids=@null +wktext +no_defs',
    area: 'Global', deprecated: false },
  { code: 'EPSG:6933', label: 'EASE-Grid 2.0 全球等积圆柱投影', category: 'projected', epsg: 6933,
    proj4Def: '+proj=cea +lon_0=0 +lat_ts=30 +x_0=0 +y_0=0 +ellps=WGS84 +datum=WGS84 +units=m +no_defs',
    area: 'Global', deprecated: false },
  { code: 'EPSG:32649', label: 'UTM Zone 49N', category: 'projected', epsg: 32649,
    proj4Def: '+proj=utm +zone=49 +datum=WGS84 +units=m +no_defs', area: 'China', deprecated: false },
  { code: 'EPSG:32650', label: 'UTM Zone 50N', category: 'projected', epsg: 32650,
    proj4Def: '+proj=utm +zone=50 +datum=WGS84 +units=m +no_defs', area: 'China', deprecated: false },
  // ── 高斯-克吕格（CGCS2000 3 度带）── Task 6.4 新增 ──
  { code: 'EPSG:4527', label: 'CGCS2000 / 3度带 高斯-克吕格 zone 39（北京，CM 117E）',
    category: 'projected', epsg: 4527,
    proj4Def: '+proj=tmerc +lat_0=0 +lon_0=117 +k=1 +x_0=39500000 +y_0=0 +ellps=GRS80 +units=m +no_defs',
    area: 'China', deprecated: false },
  { code: 'EPSG:4528', label: 'CGCS2000 / 3度带 高斯-克吕格 zone 40（上海，CM 120E）',
    category: 'projected', epsg: 4528,
    proj4Def: '+proj=tmerc +lat_0=0 +lon_0=120 +k=1 +x_0=40500000 +y_0=0 +ellps=GRS80 +units=m +no_defs',
    area: 'China', deprecated: false },
  { code: 'EPSG:4529', label: 'CGCS2000 / 3度带 高斯-克吕格 zone 41（东北，CM 123E）',
    category: 'projected', epsg: 4529,
    proj4Def: '+proj=tmerc +lat_0=0 +lon_0=123 +k=1 +x_0=41500000 +y_0=0 +ellps=GRS80 +units=m +no_defs',
    area: 'China', deprecated: false },
  // ── 兰伯特等角圆锥投影 ── Task 6.4 新增 ──
  { code: 'EPSG:3035', label: 'ETRS89-extended / LCC Europe（欧洲兰伯特等角圆锥）',
    category: 'projected', epsg: 3035,
    proj4Def: '+proj=lcc +lat_1=35 +lat_2=65 +lat_0=52 +lon_0=10 +x_0=4000000 +y_0=2800000 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs',
    area: 'Europe', deprecated: false },
]

// 模块加载时一次性注册 proj4 defs
for (const def of _CRS_DEFS) {
  if (def.proj4Def && def.epsg !== null) {
    proj4.defs(`EPSG:${def.epsg}`, def.proj4Def)
  }
}

export const CRS_REGISTRY: Record<string, CRSDef> = Object.fromEntries(
  _CRS_DEFS.map((c) => [c.code, c]),
)

const _LEGACY_MAP: Record<string, string> = { 'GCJ-02': 'GCJ02', 'BD-09': 'BD09' }

function normalizeCode(code: string): string {
  return _LEGACY_MAP[code] ?? code
}

export function getCrs(code: string): CRSDef | undefined {
  if (!code) return undefined
  return CRS_REGISTRY[normalizeCode(code)]
}

export function listCrs(category?: CRSCategory): CRSDef[] {
  return category ? _CRS_DEFS.filter((c) => c.category === category) : _CRS_DEFS
}

export function toApiPayload(): CRSOption[] {
  return _CRS_DEFS.map((c) => ({
    code: c.code, label: c.label, category: c.category, area: c.area, deprecated: c.deprecated,
  }))
}
```

#### 7.3 `gcj-bd.ts`
从后端 [_gcj_bd.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/_gcj_bd.py) 直译为 TypeScript，保留 `_WGS84_A = 6378245.0`（Krasovsky 1940，**有意保留**）。

导出 6 个函数：`gcj02ToWgs84`/`wgs84ToGcj02`/`bd09ToGcj02`/`gcj02ToBd09`/`bd09ToWgs84`/`wgs84ToBd09`。

签名：`(lng: number, lat: number) => [number, number]`（返回 tuple，与后端 `CoordinatePoint` 字段顺序一致）

```ts
// Krasovsky 1940 长半轴 — GCJ-02 算法使用的椭球参数（故意的，非 WGS84 a=6378137）
const _WGS84_A = 6378245.0
const _WGS84_EE = 0.00669342162296594323

function _outOfChina(lng: number, lat: number): boolean {
  return !(72.004 <= lng && lng <= 137.8347 && 0.8293 <= lat && lat <= 55.8271)
}

function _transformLat(lng: number, lat: number): number {
  let ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * Math.sqrt(Math.abs(lng))
  ret += (20.0 * Math.sin(6.0 * lng * Math.PI) + 20.0 * Math.sin(2.0 * lng * Math.PI)) * 2.0 / 3.0
  ret += (20.0 * Math.sin(lat * Math.PI) + 40.0 * Math.sin(lat / 3.0 * Math.PI)) * 2.0 / 3.0
  ret += (160.0 * Math.sin(lat / 12.0 * Math.PI) + 320 * Math.sin(lat * Math.PI / 30.0)) * 2.0 / 3.0
  return ret
}

function _transformLng(lng: number, lat: number): number {
  let ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * Math.sqrt(Math.abs(lng))
  ret += (20.0 * Math.sin(6.0 * lng * Math.PI) + 20.0 * Math.sin(2.0 * lng * Math.PI)) * 2.0 / 3.0
  ret += (20.0 * Math.sin(lng * Math.PI) + 40.0 * Math.sin(lng / 3.0 * Math.PI)) * 2.0 / 3.0
  ret += (150.0 * Math.sin(lng / 12.0 * Math.PI) + 300.0 * Math.sin(lng / 30.0 * Math.PI)) * 2.0 / 3.0
  return ret
}

export function gcj02ToWgs84(lng: number, lat: number): [number, number] {
  if (_outOfChina(lng, lat)) return [lng, lat]
  let dlat = _transformLat(lng - 105.0, lat - 35.0)
  let dlng = _transformLng(lng - 105.0, lat - 35.0)
  const radlat = lat / 180.0 * Math.PI
  const magic = 1 - _WGS84_EE * Math.sin(radlat) ** 2
  const sqrtMagic = Math.sqrt(magic)
  dlat = (dlat * 180.0) / ((_WGS84_A * (1 - _WGS84_EE)) / (magic * sqrtMagic) * Math.PI)
  dlng = (dlng * 180.0) / (_WGS84_A / sqrtMagic * Math.cos(radlat) * Math.PI)
  return [lng * 2 - (lng + dlng), lat * 2 - (lat + dlat)]
}

export function wgs84ToGcj02(lng: number, lat: number): [number, number] {
  if (_outOfChina(lng, lat)) return [lng, lat]
  let dlat = _transformLat(lng - 105.0, lat - 35.0)
  let dlng = _transformLng(lng - 105.0, lat - 35.0)
  const radlat = lat / 180.0 * Math.PI
  const magic = 1 - _WGS84_EE * Math.sin(radlat) ** 2
  const sqrtMagic = Math.sqrt(magic)
  dlat = (dlat * 180.0) / ((_WGS84_A * (1 - _WGS84_EE)) / (magic * sqrtMagic) * Math.PI)
  dlng = (dlng * 180.0) / (_WGS84_A / sqrtMagic * Math.cos(radlat) * Math.PI)
  return [lng + dlng, lat + dlat]
}

export function bd09ToGcj02(lng: number, lat: number): [number, number] {
  const x = lng - 0.0065
  const y = lat - 0.006
  const z = Math.sqrt(x * x + y * y) - 0.00002 * Math.sin(y * Math.PI * 3000.0 / 180.0)
  const theta = Math.atan2(y, x) - 0.000003 * Math.cos(x * Math.PI * 3000.0 / 180.0)
  return [z * Math.cos(theta), z * Math.sin(theta)]
}

export function gcj02ToBd09(lng: number, lat: number): [number, number] {
  const x = lng
  const y = lat
  const z = Math.sqrt(x * x + y * y) + 0.00002 * Math.sin(y * Math.PI * 3000.0 / 180.0)
  const theta = Math.atan2(y, x) + 0.000003 * Math.cos(x * Math.PI * 3000.0 / 180.0)
  return [z * Math.cos(theta), z * Math.sin(theta)]
}

export function bd09ToWgs84(lng: number, lat: number): [number, number] {
  const gcj = bd09ToGcj02(lng, lat)
  return gcj02ToWgs84(gcj[0], gcj[1])
}

export function wgs84ToBd09(lng: number, lat: number): [number, number] {
  const gcj = wgs84ToGcj02(lng, lat)
  return gcj02ToBd09(gcj[0], gcj[1])
}
```

#### 7.4 `crs-transformer.ts`
核心转换器，镜像后端 [_crs_transformer.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/_crs_transformer.py)：

```ts
import proj4 from 'proj4'
import {
  gcj02ToWgs84, wgs84ToGcj02, bd09ToGcj02, gcj02ToBd09,
  bd09ToWgs84, wgs84ToBd09,
} from './gcj-bd'
import type { TransformOptions } from './crs-types'

const ENCRYPTED_CODES = new Set(['GCJ02', 'BD09'])
const WGS84 = 'EPSG:4326'

function isEncrypted(code: string): boolean {
  return ENCRYPTED_CODES.has(code) || ENCRYPTED_CODES.has(code.replace('-', ''))
}

function normalizeCode(code: string): string {
  const map: Record<string, string> = { 'GCJ-02': 'GCJ02', 'BD-09': 'BD09' }
  return map[code] ?? code
}

/**
 * 单点转换。加密系走 gcj-bd.ts，EPSG 系走 proj4。
 * 偏移在 CRS 转换**后**应用（与后端一致）。
 */
export function transformPoint(
  lng: number, lat: number,
  sourceCode: string, targetCode: string,
  opts: TransformOptions = {},
): [number, number] {
  const src = normalizeCode(sourceCode)
  const tgt = normalizeCode(targetCode)
  let result: [number, number]
  if (src === tgt) {
    result = [lng, lat]
  } else if (isEncrypted(src) || isEncrypted(tgt)) {
    result = transformEncrypted(lng, lat, src, tgt)
  } else {
    result = proj4(src, tgt, [lng, lat]) as [number, number]
  }
  return [result[0] + (opts.lngOffset ?? 0), result[1] + (opts.latOffset ?? 0)]
}

/** bounds 四角点转换（投影系精确，加密系四角分别转换） */
export function transformBounds(
  bounds: [number, number, number, number], // [west, south, east, north]
  sourceCode: string, targetCode: string,
): [number, number, number, number] {
  const [w, s, e, n] = bounds
  const corners: Array<[number, number]> = [[w, s], [e, s], [e, n], [w, n]]
  const transformed = corners.map(([lng, lat]) => transformPoint(lng, lat, sourceCode, targetCode))
  const lngs = transformed.map((p) => p[0])
  const lats = transformed.map((p) => p[1])
  return [Math.min(...lngs), Math.min(...lats), Math.max(...lngs), Math.max(...lats)]
}

/** 批量点转换（CSV/POI 提交时用） */
export function transformPointsBatch(
  points: Array<[number, number]>,
  sourceCode: string, targetCode: string,
  opts: TransformOptions = {},
): Array<[number, number]> {
  return points.map(([lng, lat]) => transformPoint(lng, lat, sourceCode, targetCode, opts))
}

// 内部：加密系 6 条直连路径 + 通用路径（经 WGS84 中转）
function transformEncrypted(lng: number, lat: number, src: string, tgt: string): [number, number] {
  // 直连
  if (src === 'GCJ02' && tgt === WGS84) return gcj02ToWgs84(lng, lat)
  if (src === WGS84 && tgt === 'GCJ02') return wgs84ToGcj02(lng, lat)
  if (src === 'BD09' && tgt === 'GCJ02') return bd09ToGcj02(lng, lat)
  if (src === 'GCJ02' && tgt === 'BD09') return gcj02ToBd09(lng, lat)
  if (src === 'BD09' && tgt === WGS84) return bd09ToWgs84(lng, lat)
  if (src === WGS84 && tgt === 'BD09') return wgs84ToBd09(lng, lat)
  // 通用路径：经 WGS84 中转
  const wgs = src === 'BD09' ? bd09ToWgs84(lng, lat) : gcj02ToWgs84(lng, lat)
  if (tgt === 'BD09') return wgs84ToBd09(wgs[0], wgs[1])
  if (tgt === 'GCJ02') return wgs84ToGcj02(wgs[0], wgs[1])
  // 加密系 → EPSG 系：先转 WGS84 再 proj4
  return proj4(WGS84, tgt, wgs) as [number, number]
}
```

#### 7.5 `crs-detector.ts`
客户端轻量 bounds 启发式检测（raster 检测交给后端 `/import/raster`），镜像后端 [_crs_detector.detect_from_bounds](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/_crs_detector.py#L226-L289) Task 6.4 增强版：

```ts
import type { CRSDetectionResult } from './crs-types'

/** 客户端 bounds 启发式（与后端 _crs_detector.detect_from_bounds 一致，含 GK/Lambert 增强） */
export function detectFromBounds(bounds: [number, number, number, number]): CRSDetectionResult {
  const [w, s, e, n] = bounds
  const isGeographic = (
    w >= -180 && w <= 180 && e >= -180 && e <= 180 &&
    s >= -90 && s <= 90 && n >= -90 && n <= 90 &&
    w < e && s < n
  )
  if (isGeographic) {
    return {
      sourceCrs: 'EPSG:4326', confidence: 0.5, method: 'bounds_heuristic',
      suggestedCrs: 'EPSG:4326', needsUserConfirm: true,
      notes: `bounds (${w},${s},${e},${n}) 在 ±180/±90 内，推断为地理坐标系`,
    }
  }
  if (Math.abs(w) > 180 || Math.abs(e) > 180) {
    // 高斯-克吕格 3 度带 false easting 模式：X 在 39000000-42000000（zone 39/40/41）
    if ((w > 39000000 && w < 42000000) || (e > 39000000 && e < 42000000)) {
      const midX = (w + e) / 2
      const zone = Math.floor(midX / 1000000)
      const suggested = zone === 40 ? 'EPSG:4528' : zone === 41 ? 'EPSG:4529' : 'EPSG:4527'
      return {
        sourceCrs: suggested, confidence: 0.5, method: 'bounds_heuristic',
        suggestedCrs: suggested, needsUserConfirm: true,
        notes: `bounds 匹配高斯-克吕格 3 度带（zone ${zone}），建议 ${suggested}`,
      }
    }
    // Lambert Europe (EPSG:3035) 范围
    if (w > 1000000 && w < 8000000 && e > 1000000 && e < 8000000) {
      return {
        sourceCrs: 'EPSG:3035', confidence: 0.3, method: 'bounds_heuristic',
        suggestedCrs: 'EPSG:3035', needsUserConfirm: true,
        notes: 'bounds 在 Lambert Europe 范围内，建议 EPSG:3035',
      }
    }
    return {
      sourceCrs: 'EPSG:32650', confidence: 0.3, method: 'bounds_heuristic',
      suggestedCrs: 'EPSG:32650', needsUserConfirm: true,
      notes: 'bounds 数值超出 ±180，推断为投影坐标系（默认建议 UTM 50N）',
    }
  }
  return {
    sourceCrs: 'EPSG:4326', confidence: 0.3, method: 'bounds_heuristic',
    suggestedCrs: 'EPSG:4326', needsUserConfirm: true,
    notes: 'bounds 无法明确分类，默认 WGS84',
  }
}
```

#### 7.6 `index.ts`
统一导出：
```ts
export * from './crs-types'
export * from './crs-registry'
export * from './gcj-bd'
export * from './crs-transformer'
export * from './crs-detector'
```

#### 7.7 `crs-transformer.test.ts`
vitest 单测（模式参考 [data-import.test.ts](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/services/data-import.test.ts)）：

```ts
import { describe, expect, it } from 'vitest'
import proj4 from 'proj4'
import { transformPoint, transformBounds, transformPointsBatch } from './crs-transformer'
import { getCrs, listCrs } from './crs-registry'
import { bd09ToGcj02, gcj02ToBd09 } from './gcj-bd'
import { detectFromBounds } from './crs-detector'

describe('crs-registry', () => {
  it('注册 13 个 CRS', () => {
    expect(listCrs().length).toBe(13)
  })

  it('getCrs 兼容 GCJ-02 旧码', () => {
    expect(getCrs('GCJ-02')?.code).toBe('GCJ02')
    expect(getCrs('BD-09')?.code).toBe('BD09')
  })

  it('包含 Task 6.4 新增的 GK/Lambert CRS', () => {
    expect(getCrs('EPSG:4527')).toBeDefined()
    expect(getCrs('EPSG:4528')).toBeDefined()
    expect(getCrs('EPSG:4529')).toBeDefined()
    expect(getCrs('EPSG:3035')).toBeDefined()
  })
})

describe('crs-transformer', () => {
  it('EPSG:4326 → EPSG:3857 与 proj4 一致', () => {
    const [lng, lat] = transformPoint(116.39, 39.91, 'EPSG:4326', 'EPSG:3857')
    expect(lng).toBeCloseTo(12958215, -2)
    expect(lat).toBeCloseTo(4852326, -2)
  })

  it('GCJ02 → WGS84 与后端 _gcj_bd 北京样例一致', () => {
    const [lng, lat] = transformPoint(116.39747, 39.90880, 'GCJ02', 'EPSG:4326')
    expect(lng).toBeCloseTo(116.3912, 3)
    expect(lat).toBeCloseTo(39.9087, 3)
  })

  it('BD09 → GCJ02 与直译公式一致', () => {
    const result = transformPoint(116.404, 39.915, 'BD09', 'GCJ02')
    const expected = bd09ToGcj02(116.404, 39.915)
    expect(result[0]).toBeCloseTo(expected[0], 9)
    expect(result[1]).toBeCloseTo(expected[1], 9)
  })

  it('GCJ02 → BD09 走直连路径', () => {
    const result = transformPoint(116.404, 39.915, 'GCJ02', 'BD09')
    const expected = gcj02ToBd09(116.404, 39.915)
    expect(result[0]).toBeCloseTo(expected[0], 9)
    expect(result[1]).toBeCloseTo(expected[1], 9)
  })

  it('偏移在 CRS 转换后应用', () => {
    const [lng, lat] = transformPoint(0, 0, 'EPSG:4326', 'EPSG:4326', { lngOffset: 1.5, latOffset: 2.5 })
    expect(lng).toBeCloseTo(1.5, 9)
    expect(lat).toBeCloseTo(2.5, 9)
  })

  it('EPSG:4527 → EPSG:4326 北京样例', () => {
    // 北京点 (39500000+500000, 4440000) → WGS84 ~ (116.39, 39.91)
    const [lng, lat] = transformPoint(39505000, 4440000, 'EPSG:4527', 'EPSG:4326')
    expect(lng).toBeCloseTo(116.39, 1)
    expect(lat).toBeCloseTo(39.91, 1)
  })

  it('EPSG:3035 → EPSG:4326 欧洲样例', () => {
    const [lng, lat] = transformPoint(4321000, 3210000, 'EPSG:3035', 'EPSG:4326')
    expect(lng).toBeCloseTo(10.5, 1)
    expect(lat).toBeCloseTo(51.0, 1)
  })

  it('bounds 四角转换', () => {
    const result = transformBounds([116, 39, 117, 40], 'EPSG:4326', 'EPSG:3857')
    expect(result[0]).toBeLessThan(result[2])
    expect(result[1]).toBeLessThan(result[3])
  })

  it('批量点转换', () => {
    const points: Array<[number, number]> = [[116.39, 39.91], [121.47, 31.23]]
    const result = transformPointsBatch(points, 'EPSG:4326', 'EPSG:3857')
    expect(result.length).toBe(2)
    const expected0 = proj4('EPSG:4326', 'EPSG:3857', points[0])
    expect(result[0][0]).toBeCloseTo(expected0[0], -2)
  })

  it('相同 CRS 直接返回原值', () => {
    const [lng, lat] = transformPoint(116.39, 39.91, 'EPSG:4326', 'EPSG:4326')
    expect(lng).toBeCloseTo(116.39, 9)
    expect(lat).toBeCloseTo(39.91, 9)
  })
})

describe('crs-detector', () => {
  it('地理坐标系识别', () => {
    const result = detectFromBounds([116, 39, 117, 40])
    expect(result.sourceCrs).toBe('EPSG:4326')
    expect(result.method).toBe('bounds_heuristic')
  })

  it('高斯-克吕格 zone 39 识别', () => {
    const result = detectFromBounds([39500000, 4400000, 39510000, 4410000])
    expect(result.sourceCrs).toBe('EPSG:4527')
  })

  it('Lambert Europe 识别', () => {
    const result = detectFromBounds([4000000, 2500000, 4500000, 3000000])
    expect(result.sourceCrs).toBe('EPSG:3035')
  })

  it('默认投影系 UTM 50N', () => {
    const result = detectFromBounds([447000, 4419000, 448000, 4420000])
    expect(result.sourceCrs).toBe('EPSG:32650')
  })
})
```

**验证**：
```powershell
cd Code\frontend
npx vitest run src/services/crs/
# 期望: 全部通过（~17 测试）
```

---

### Task 8：`RasterImportConfirmDialog.vue` 弹窗组件

**新建**：`Code/frontend/src/components/toolbar/RasterImportConfirmDialog.vue`

**作用**：当 `/import/raster` 返回 `needs_confirm=true` 时弹出，让用户校验/覆盖 CRS、设置偏移。

**Props**：
```ts
interface Props {
  visible: boolean
  fileName: string
  detectionResult: {
    source_crs: string
    suggested_crs: string
    needs_confirm: boolean
    detection_notes: string
    bounds: [number, number, number, number]
  }
}
```

**Emits**：
```ts
interface Emits {
  (e: 'confirm', payload: { sourceCrs: string; lngOffset: number; latOffset: number }): void
  (e: 'cancel'): void
  (e: 'skip'): void  // 跳过确认，用 suggested_crs + 0 offset
}
```

**UI 结构**（参考 [CsvImportDialog.vue](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/toolbar/CsvImportDialog.vue) 的暗色主题样式 `csv-dialog-overlay`/`csv-dialog-panel`/`panel-header`/`section-label`/`col-row`/`col-field`/`col-select`/`action-row`/`cancel-btn`/`confirm-btn`）：
- 弹窗 overlay + 居中 panel
- 标题：「确认栅格数据坐标系 — {fileName}」
- 区块 1：检测信息（只读）
  - 检测到 CRS: {source_crs}（badge）
  - 置信度备注: {detection_notes}
  - 原始 bounds: [w, s, e, n]（在 source_crs 下）
- 区块 2：用户校验
  - 下拉框：源 CRS（默认 suggested_crs，可选 13 项，从 `listCrs()` 获取）
  - 数字输入：lng_offset（默认 0，步长 0.001）
  - 数字输入：lat_offset（默认 0，步长 0.001）
  - 实时预览：转换后 WGS84 bounds（用 `transformBounds` 计算，显示四角）
- 区块 3：操作按钮
  - 「取消」emit('cancel')
  - 「跳过（用建议值）」emit('skip')
  - 「确认转换」emit('confirm', {...})

**关键实现**：
- 用 `onMounted` 从 `services/crs` import `listCrs` 填充下拉
- 用 `computed` 实时计算预览 bounds
- 样式完全复用 CsvImportDialog 的 BEM 命名（同主题）

---

### Task 9：前端集成点修改

#### 9.1 `data-import.ts` 扩展

**改写**：[Code/frontend/src/services/data-import.ts](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/services/data-import.ts)

**改动 1**：扩展 `RasterImportResult` 接口（第 18-21 行）：
```ts
export interface RasterImportResult {
  layer_id: string
  bounds?: [number, number, number, number]
  source_crs?: string
  suggested_crs?: string
  needs_confirm?: boolean
  detection_notes?: string
}
```

**改动 2**：新增 3 个函数（在 `uploadRasterFile` 之后）：
```ts
import type { CRSOption } from '@/services/crs'

/** GET /import/crs-options — 获取 13 项 CRS 下拉 */
export async function fetchCrsOptions(): Promise<{ count: number; items: CRSOption[] }> {
  const resp = await fetch(resolveApiUrl('/import/crs-options'))
  if (!resp.ok) throw new Error(`fetchCrsOptions failed: ${resp.status}`)
  return resp.json()
}

/** POST /import/raster/confirm — 提交确认的 CRS + 偏移，后端重投影到 WGS84 */
export async function confirmRasterImport(params: {
  layerId: string
  sourceCrs: string
  lngOffset: number
  latOffset: number
}): Promise<{
  layer_id: string
  source_crs: string
  target_crs: string
  applied_offset: [number, number]
  bounds: [number, number, number, number]
}> {
  const resp = await fetch(resolveApiUrl('/import/raster/confirm'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      layer_id: params.layerId,
      source_crs: params.sourceCrs,
      lng_offset: params.lngOffset,
      lat_offset: params.latOffset,
    }),
  })
  if (!resp.ok) throw new Error(`confirmRasterImport failed: ${resp.status}`)
  return resp.json()
}

/** POST /import/transform-point — 批量点转换（CSV/POI 预览用） */
export async function transformPointBatch(params: {
  points: Array<[number, number]>
  sourceCrs: string
  targetCrs: string
  lngOffset?: number
  latOffset?: number
}): Promise<{ count: number; points: Array<[number, number]> }> {
  const resp = await fetch(resolveApiUrl('/import/transform-point'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      points: params.points,
      source_crs: params.sourceCrs,
      target_crs: params.targetCrs,
      lng_offset: params.lngOffset ?? 0,
      lat_offset: params.latOffset ?? 0,
    }),
  })
  if (!resp.ok) throw new Error(`transformPointBatch failed: ${resp.status}`)
  return resp.json()
}
```

#### 9.2 `useDataImportFlow.ts` 插入 CRS 确认步骤

**改写**：[Code/frontend/src/composables/useDataImportFlow.ts](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/composables/useDataImportFlow.ts)

**改动**：`importRasterFile`（第 79-101 行）上传后不再直接 `addImportedRasterLayer`，改为：
1. 上传 → 拿 `RasterImportResult`
2. 若 `needs_confirm=false`：直接 `addImportedRasterLayer`（WGS84 数据，bounds 即可用）
3. 若 `needs_confirm=true`：把结果存到 `pendingRasterConfirm` ref，触发 `RasterImportConfirmDialog` 弹窗
4. 弹窗 confirm → 调 `confirmRasterImport` → 用返回的 WGS84 bounds `addImportedRasterLayer`
5. 弹窗 skip → 用 suggested_crs + 0 offset 调 `confirmRasterImport`
6. 弹窗 cancel → `deleteLayer(layer_id)` 清理后端临时文件

**新增 ref + 函数**：
```ts
const pendingRasterConfirm = ref<{
  layerId: string
  fileName: string
  detectionResult: RasterImportResult
} | null>(null)

async function confirmRasterCrs(payload: { sourceCrs: string; lngOffset: number; latOffset: number }) {
  if (!pendingRasterConfirm.value) return
  const { layerId, fileName } = pendingRasterConfirm.value
  try {
    const result = await confirmRasterImport({
      layerId, sourceCrs: payload.sourceCrs,
      lngOffset: payload.lngOffset, latOffset: payload.latOffset,
    })
    addImportedRasterLayer(fileName, layerId, result.bounds, {
      sourceCrs: payload.sourceCrs,
      lngOffset: payload.lngOffset, latOffset: payload.latOffset,
    })
  } finally {
    pendingRasterConfirm.value = null
  }
}

async function skipRasterConfirm() {
  if (!pendingRasterConfirm.value) return
  const { layerId, fileName, detectionResult } = pendingRasterConfirm.value
  try {
    const result = await confirmRasterImport({
      layerId,
      sourceCrs: detectionResult.suggested_crs ?? 'EPSG:4326',
      lngOffset: 0, latOffset: 0,
    })
    addImportedRasterLayer(fileName, layerId, result.bounds)
  } finally {
    pendingRasterConfirm.value = null
  }
}

async function cancelRasterConfirm() {
  if (!pendingRasterConfirm.value) return
  const { layerId } = pendingRasterConfirm.value
  // 清理后端临时文件
  await fetch(resolveApiUrl(`/import/raster/${layerId}`), { method: 'DELETE' }).catch(() => {})
  pendingRasterConfirm.value = null
}
```

**返回值新增**：`pendingRasterConfirm`, `confirmRasterCrs`, `skipRasterConfirm`, `cancelRasterConfirm`

#### 9.3 `CsvImportDialog.vue` 改走 services/crs + fetchCrsOptions

**改写**：[Code/frontend/src/components/toolbar/CsvImportDialog.vue](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/toolbar/CsvImportDialog.vue)

**改动 1**：把第 29-38 行硬编码 `CRS_OPTIONS` 改为 ref + `onMounted` 从 `/import/crs-options` 获取：
```ts
import { fetchCrsOptions } from '@/services/data-import'
import { transformPoint } from '@/services/crs'

const CRS_OPTIONS = ref<Array<{ code: string; label: string; category: string }>>([])
onMounted(async () => {
  const data = await fetchCrsOptions()
  CRS_OPTIONS.value = data.items
})
```

**改动 2**：把第 95-98 行 `_proj4Convert` 替换为 `services/crs` 的 `transformPoint`：
```ts
// 改前
async function _proj4Convert(lng: number, lat: number, fromCrs: string): Promise<[number, number]> {
  const proj4 = (await import('proj4')).default
  return proj4(fromCrs, 'EPSG:4326', [lng, lat])
}

// 改后
function _convertPoint(lng: number, lat: number, fromCrs: string): [number, number] {
  return transformPoint(lng, lat, fromCrs, 'EPSG:4326')
}
```

**收益**：
- CRS 下拉从 8 项扩展到 13 项（含 GCJ02/BD09/ETRS89/EASE-Grid/GK/Lambert）
- CSV 导入现在支持加密系 POI 转换（GCJ02/BD09 → WGS84）
- 移除动态 `import('proj4')`，统一走 `services/crs` 单例

#### 9.4 `imported-raster.ts` + `layers/index.ts` 加 CRS/offset 字段

**改写文件 1**：[Code/frontend/src/stores/layers/imported-raster.ts](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/stores/layers/imported-raster.ts)

扩展 `ImportedRasterPayload` 接口（第 4-10 行）：
```ts
export interface ImportedRasterPayload {
  overlayLayerId: string
  bounds?: [number, number, number, number]
  fileName?: string
  sourceCrs?: string
  lngOffset?: number
  latOffset?: number
}
```

**改写文件 2**：[Code/frontend/src/stores/layers/index.ts](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/stores/layers/index.ts)

`addImportedRasterLayer`（第 852-878 行）增加第 4 个可选参数：
```ts
function addImportedRasterLayer(
  name: string,
  overlayLayerId: string,
  bounds?: [number, number, number, number],
  options?: { sourceCrs?: string; lngOffset?: number; latOffset?: number },
): ActiveLayer
```

在函数体内把 `options.sourceCrs`/`lngOffset`/`latOffset` 写入 `ActiveLayer` 的 metadata（用于后续 `overlay-image-module.ts` 的 bounds 校验，以及图层信息面板展示）。

---

### Task 10：`overlay-image-module.ts` 防御性 bounds 校验

**改写**：[Code/frontend/src/components/map/overlay-image-module.ts](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/map/overlay-image-module.ts)

**改动**：`_addOverlay` 函数（第 138-244 行）在拿到 `boundsData.bounds` 后、调 `addSource` 前插入防御性校验：

```ts
function _validateWgs84Bounds(bounds: [number, number, number, number]): {
  valid: boolean
  warning?: string
} {
  const [w, s, e, n] = bounds
  if (!Number.isFinite(w) || !Number.isFinite(s) || !Number.isFinite(e) || !Number.isFinite(n)) {
    return { valid: false, warning: 'bounds 含 NaN/Infinity，可能栅格无有效像素' }
  }
  if (w < -180 || e > 180 || s < -90 || n > 90) {
    return { valid: false, warning: `bounds 超出 ±180/±90，疑似未转换到 WGS84: [${w}, ${s}, ${e}, ${n}]` }
  }
  if (w >= e || s >= n) {
    return { valid: false, warning: `bounds 顺序错误（west>=east 或 south>=north）: [${w}, ${s}, ${e}, ${n}]` }
  }
  if (e - w > 180) {
    return { valid: true, warning: `bounds 跨 ±180° 经线（width=${e - w}°），MapLibre 可能渲染异常` }
  }
  return { valid: true }
}

// 在 _addOverlay 内：
const meta = boundsData.meta ?? {}
const validation = _validateWgs84Bounds(boundsData.bounds)
if (!validation.valid) {
  console.warn(`[overlay] 图层 ${layerId} bounds 校验失败: ${validation.warning}（已跳过加载）`)
  return  // 不加载无效图层
}
if (validation.warning && meta.crs && meta.crs !== 'EPSG:4326') {
  console.warn(`[overlay] 图层 ${layerId} meta.crs=${meta.crs}（非 WGS84），bounds 可能不准: ${validation.warning}`)
}
// 正常 addSource...
```

**策略**：
- 校验失败 → 不加载（避免 MapLibre 崩溃）
- 警告但仍 valid → 加载 + console.warn
- meta.crs 非 WGS84 → 加载 + console.warn（用户可后续重新 confirm）

---

### Task 11：代码审查 + 项目重启

#### 11.1 TRAE-code-review skill 审查

**调用**：`Skill` tool with `name="TRAE-code-review"`

**审查范围**（所有改动文件）：
- Backend:
  - `app/services/raster_preview_service.py`（标量 mask 修复）
  - `app/services/crs/crs_registry.py`（新增 4 CRS）
  - `app/services/crs/_gcj_bd.py`（新增 gcj02_to_bd09）
  - `app/services/crs/_crs_detector.py`（bounds 启发式增强）
  - `tests/test_crs_detector.py` / `tests/test_crs_transformer.py` / `tests/test_import_raster_crs.py`
- Frontend:
  - `src/services/crs/` 整个目录（6 文件 + 1 测试）
  - `src/components/toolbar/RasterImportConfirmDialog.vue`（新建）
  - `src/components/toolbar/CsvImportDialog.vue`
  - `src/services/data-import.ts`
  - `src/composables/useDataImportFlow.ts`
  - `src/stores/layers/imported-raster.ts` / `src/stores/layers/index.ts`
  - `src/components/map/overlay-image-module.ts`

**审查重点**（用户要求"着重于旧代码使用和逻辑混乱问题"）：
1. **旧代码使用**：是否还有调用已废弃的 `coordinate_transform_service` 旧 API（应已迁移到 `services/crs/`）？
2. **逻辑混乱**：CRS 转换路由是否清晰（加密系 vs EPSG 系分流）？偏移应用时机是否一致（转换后）？
3. **前后端一致性**：13 个 CRS 是否完全对齐？proj4 串是否与后端 `proj4_def` 完全一致？
4. **错误处理**：网络失败/CRS 不识别/bounds 越界是否优雅降级？
5. **类型安全**：TypeScript 类型是否完整（无 any 滥用）？

#### 11.2 项目重启 + E2E 冒烟

**重启步骤**：
```powershell
# 1. 重启后端
cd Code\backend
# 终止现有 backend 进程
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
# 启动 backend（隐藏窗口，按项目惯例）
Start-Process python -ArgumentList "-u","-m","uvicorn","app.main:app","--host","0.0.0.0","--port","8000" -WindowStyle Hidden

# 2. 重启前端
cd Code\frontend
Get-Process node -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Process npm -ArgumentList "run","dev" -WindowStyle Hidden
```

**E2E 冒烟清单**（手动验证）：
- [ ] `GET /import/crs-options` 返回 13 项（Postman/curl）
- [ ] 上传 WGS84 TIF（如 `I:\Geograph_DataSet\` 下的任一 WGS84 栅格）→ needs_confirm=false → 直接显示在地图上
- [ ] 上传 UTM 50N TIF → needs_confirm=true → 弹 RasterImportConfirmDialog → 确认 → 重投影后显示在正确位置
- [ ] 上传 Gauss-Krüger zone 39 TIF → needs_confirm=true → suggested_crs='EPSG:4527' → 确认 → 显示正确
- [ ] 上传 Lambert Europe TIF → needs_confirm=true → suggested_crs='EPSG:3035' → 确认 → 显示正确
- [ ] CSV 导入：选 GCJ02 → 点位正确转换到 WGS84 位置（与底图对齐）
- [ ] CSV 导入：选 BD09 → 点位正确转换到 WGS84 位置
- [ ] 图层 show/hide 性能正常（无卡顿）
- [ ] 已有图层（SMAP/CLCD/Biomass 等）显示无回归
- [ ] 测量工具（measure 模式）正常工作

---

## 三、Assumptions & Decisions

### 决策记录
1. **CRS 扩展范围**：新增 4 项（EPSG:4527/4528/4529 + EPSG:3035），不全量覆盖 21 个 GK zone（4513-4533）。理由：用户主要数据集中在京津冀/长三角/东北，3 个 zone 足够；如需扩展，注册表结构支持追加。
2. **Lambert 选择 EPSG:3035**（ETRS89 / LCC Europe）：用户列举了 ETRS89 + Lambert，3035 同时覆盖两者；中国区域 Lambert 无标准 EPSG，按需后续添加。
3. **Bug 修复改生产代码**（不改测试 fixture 绕过）：根治所有无 nodata 栅格的预览失败。
4. **`gcj02_to_bd09` 后端补齐**：与前端对称，避免前后端算法不一致。
5. **detector 启发式增强**：仅影响无 CRS 元数据的兜底路径，主路径仍走 rasterio CRS（confidence 0.95）。
6. **保留所有 v2 锁定决策**：垫片保留、OverlaySpec.crs 默认 WGS84、前端预览+后端收口、不做双点校准、显式偏移字段。

### 假设
- pyproj 3.7.2 已安装且支持 EPSG:4527/4528/4529/3035（标准 EPSG，pyproj 内置）
- proj4.js 2.20.9 支持上述 4 个 CRS 的 proj4 串（手动注册 via `proj4.defs()`）
- 用户已有 WGS84/UTM/GK/Lambert 测试数据位于 `I:\Geograph_DataSet\` 下
- 前端 dev server 端口与后端 8000 已配置好代理（`resolveApiUrl` 处理）

### 风险与缓解
- **风险**：新增 4 CRS 可能与某些老测试冲突（如 `test_returns_9_items`）
- **缓解**：Task 6.4 显式列出所有需更新的测试文件
- **风险**：proj4.js 对 EPSG:4527 的 false easting（39500000）数值精度
- **缓解**：Task 7.7 vitest 含北京点转换测试，验证精度到 0.1°

## 四、验证步骤汇总

```powershell
# Backend
cd Code\backend
python -m pytest tests/test_crs_transformer.py tests/test_crs_detector.py tests/test_import_raster_crs.py -v
# 期望: 23 + 63 + 12 = 98 测试全通过

# Frontend
cd Code\frontend
npx vitest run src/services/crs/
# 期望: ~17 测试全通过

# Type check
npx vue-tsc --noEmit
# 期望: 0 errors

# E2E 冒烟（手动）
# 按 Task 11.2 清单逐项验证
```

## 五、执行顺序

1. **Task 6.3-fix**（5 分钟）— 改 raster_preview_service.py 2 行 + 更新 test docstring
2. **Task 6.4**（30 分钟）— 后端 CRS 扩展 4 项 + 测试
3. **Task 7**（60 分钟）— 前端 services/crs/ 7 文件
4. **Task 8**（30 分钟）— RasterImportConfirmDialog.vue
5. **Task 9**（45 分钟）— 4 个集成点修改
6. **Task 10**（15 分钟）— overlay-image-module.ts 防御校验
7. **Task 11.1**（20 分钟）— TRAE-code-review skill 审查
8. **Task 11.2**（15 分钟）— 项目重启 + E2E 冒烟

总计预估：~3.5 小时
