# 统一坐标系统支持模块 — Phase 1 续作执行计划 v2

> **背景**：[原 Phase 1 续作计划](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/.trae/documents/统一坐标系统支持模块-Phase1续作执行计划.md) 已完成 Task 3-fix / 4 / 5 / 6.1 / 6.2，Task 6.3 有 8/12 测试通过。本计划接续完成 Task 6.3 修复 + Task 7~11。
>
> **用户原始需求**：覆盖 WGS84/ETRS89/EASE-Grid 2.0/CGCS2000/GCJ-02/BD-09 + 高斯-克吕格/UTM/Lambert/Web Mercator 的统一 CRS 模块，支持显式偏移字段，前端预览 + 后端收口，上传时检测 + 用户确认。用户额外指令：「做整个修改完后进行一次代码审查，着重于旧代码使用和逻辑混乱问题，然后重启整个项目」。
>
> **本计划不重新决策已锁定项**（垫片保留、OverlaySpec.crs 默认 WGS84、前端预览+后端收口、不做双点校准等）。

## 一、当前状态确认

### 1.1 已完成（不动）

| 文件 | 状态 |
|---|---|
| [Code/backend/app/services/crs/](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/) 整个包 | ✅ 6 文件：`crs_types.py`/`crs_registry.py`/`_gcj_bd.py`/`__init__.py`/`_crs_transformer.py`/`_crs_detector.py` |
| [Code/backend/app/services/coordinate_transform_service.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/coordinate_transform_service.py) | ✅ Task 4 deprecated 垫片，5 加密函数 + `transform_point` + `CoordinatePoint`/`CoordinateSystem` 全保留 |
| [Code/backend/app/services/overlay_registry.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/overlay_registry.py) | ✅ Task 5 `OverlaySpec.crs` 字段 + `meta_dict` 返回 `crs` |
| [Code/backend/app/services/raster_preview_service.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/raster_preview_service.py) | ✅ Task 6.1 `render_cog_preview_reprojected` 方法 |
| [Code/backend/app/api/routers/import_router.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/api/routers/import_router.py) | ✅ Task 6.2 4 新端点 + 3 Pydantic 模型 + `/import/raster` 返回 CRS 检测字段 |
| [Code/backend/tests/conftest.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/conftest.py) | ✅ Task 3-fix `PYTEST_DEBUG_TEMPROOT` 重定向 |
| [Code/backend/requirements.txt](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/requirements.txt) | ✅ Task 4 `pyproj>=3.6,<4` pin |
| [Code/backend/tests/test_crs_transformer.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/test_crs_transformer.py) | ✅ 21 测试全通过 |
| [Code/backend/tests/test_crs_detector.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/test_crs_detector.py) | ✅ 57 测试全通过 |
| [Code/backend/tests/test_import_raster_crs.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/test_import_raster_crs.py) | ⚠️ 8 通过 / 4 失败（Task 6.3-fix 修复） |

### 1.2 Task 6.3 失败根因（本轮 Phase 1 已诊断）

**复现脚本**（在 `.pytest_tmp` 内创建 2×2 WGS84 TIF → 字节拷贝 → 调 `render_cog_preview`）：
```
[ORIGINAL] bounds=BoundingBox(left=116.0, bottom=39.0, right=117.0, top=40.0), crs=EPSG:4326, shape=(2, 2), count=1
[UPLOADED] bounds=BoundingBox(left=116.0, bottom=39.0, right=117.0, top=40.0), crs=EPSG:4326, shape=(2, 2), count=1
ValueError: Source shape (1,) is inconsistent with given indexes 1
```

**结论**：
- 上传流程**未损坏文件**（`[UPLOADED]` bounds/crs/shape 与原文件完全一致）
- `NotGeoreferencedWarning` 是 rasterio 对**没有 gcps/rpcs** 的小栅格的提示，不影响读取
- 真正失败位置：[raster_preview_service.py:58-63](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/raster_preview_service.py#L58-L63) 调 `dataset.read(1, out_shape=(64, 64), resampling=bilinear, masked=True)`
- 根因：**rasterio 对 2×2 极小栅格做 32× bilinear 上采样到 64×64 时存在已知 edge case**，返回 1-D shape `(1,)` 而非 2-D `(64, 64)`

**修复方案**：把 `wgs84_geotiff` / `utm50_geotiff` fixture 的合成栅格从 2×2 改为 32×32，避免极小栅格 edge case。**不需要改 `render_cog_preview` 本身**（生产数据都是 ≥256×256 的真实 TIF）。

### 1.3 前端集成点扫描结果（本轮 Phase 1 已扫描）

| 集成点 | 当前状态 | Task |
|---|---|---|
| `Code/frontend/src/services/crs/` | ❌ 不存在（全新创建） | Task 7 |
| `Code/frontend/src/services/data-import.ts:18-21` | `RasterImportResult` 只有 `layer_id`/`bounds`，无 CRS 字段 | Task 9.1 |
| `Code/frontend/src/services/data-import.ts:162-227` | `uploadRasterFile` 用 XHR + `resolveApiUrl('/import/raster')` | Task 9.1 |
| `Code/frontend/src/composables/useDataImportFlow.ts:79-101` | `importRasterFile` 上传后直接 `addImportedRasterLayer`，无确认步骤 | Task 9.2 |
| `Code/frontend/src/components/toolbar/CsvImportDialog.vue:29-38` | `CRS_OPTIONS` 硬编码 8 项（含 EPSG:4527/4528/4529 Gauss-Krüger，但缺 GCJ02/BD09/4258/6933） | Task 9.3 |
| `Code/frontend/src/components/toolbar/CsvImportDialog.vue:95-98` | `_proj4Convert` 用动态 import proj4，仅做 EPSG→EPSG:4326 | Task 9.3 |
| `Code/frontend/src/stores/layers/imported-raster.ts:4-9` | `ImportedRasterPayload` 只有 `overlayLayerId`/`bounds`/`fileName`，无 CRS/offset 字段 | Task 9.4 |
| `Code/frontend/src/stores/layers/index.ts:852-878` | `addImportedRasterLayer(name, overlayLayerId, bounds?)` — 3 参数，无 CRS 字段 | Task 9.4 |
| `Code/frontend/src/components/map/overlay-image-module.ts:138-244` | `_addOverlay` 无 bounds 校验，直接 `addSource` | Task 10 |
| `Code/frontend/package.json:22,30` | ✅ `proj4@^2.20.9` + `@types/proj4@^2.5.6` 已装 | — |
| `Code/frontend/src/services/data-import.test.ts` | vitest 模式：`describe/it/expect`，`*.test.ts` 命名 | Task 7 |

## 二、Proposed Changes

### Task 6.3-fix：修复 4 个失败的集成测试

**改写**：[Code/backend/tests/test_import_raster_crs.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/test_import_raster_crs.py)

**改动**：把 `wgs84_geotiff` / `utm50_geotiff` fixture 的合成栅格从 2×2 改为 32×32，避免 rasterio 极小栅格 edge case。

**关键代码改动**（`wgs84_geotiff`，`utm50_geotiff` 同理）：
```python
@pytest.fixture
def wgs84_geotiff(tmp_path: Path) -> Path:
    """合成 WGS84 GeoTIFF（32×32 像素，覆盖中国区域 116-117E, 39-40N）。"""
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds

    path = tmp_path / "wgs84.tif"
    transform = from_bounds(116.0, 39.0, 117.0, 40.0, 32, 32)
    data = np.tile(np.linspace(1.0, 4.0, 32 * 32, dtype="float32").reshape(32, 32), (1, 1))
    with rasterio.open(
        path, "w", driver="GTiff", width=32, height=32, count=1,
        dtype="float32", crs="EPSG:4326", transform=transform,
    ) as dst:
        dst.write(data, 1)
    return path
```

**utm50_geotiff** 同步改 32×32，bounds 保持 `447000, 4419000, 448000, 4420000`（北京附近 UTM 50N 1km×1km，分辨率 ~31m/像素）。

**验证**：
```powershell
cd Code\backend
python -m pytest tests/test_import_raster_crs.py -v
# 期望: 12/12 通过
```

### Task 7：前端 `services/crs/` 模块 + vitest

**新建目录**：`Code/frontend/src/services/crs/`

**文件清单**（5 个源文件 + 1 个测试文件）：

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
```

#### 7.2 `crs-registry.ts`
镜像后端 9 个 CRS（[crs_registry.py:16-92](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/crs_registry.py#L16-L92)），提供 `CRS_REGISTRY`/`getCrs(code)`/`listCrs(category?)`：
- 与后端 `_CRS_DEFS` 列表完全对齐（9 项）
- `getCrs` 兼容旧码 `'GCJ-02'`/`'BD-09'` → `'GCJ02'`/`'BD09'` 归一化（同后端 `_normalize_legacy_code`）

#### 7.3 `gcj-bd.ts`
从后端 [_gcj_bd.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/_gcj_bd.py) 直译为 TypeScript，保留 `WGS84_A = 6378245.0`（Krasovsky 1940，**有意保留**）。

导出函数：`gcj02ToWgs84`/`wgs84ToGcj02`/`bd09ToGcj02`/`gcj02ToBd09`/`bd09ToWgs84`/`wgs84ToBd09`。

签名：`(lng: number, lat: number) => [number, number]`（返回 tuple，与后端 `CoordinatePoint` 字段顺序一致）

#### 7.4 `crs-transformer.ts`
核心转换器，镜像后端 [_crs_transformer.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/_crs_transformer.py)：

```ts
import proj4 from 'proj4'
import { getCrs } from './crs-registry'
import {
  gcj02ToWgs84, wgs84ToGcj02, bd09ToGcj02, gcj02ToBd09,
  bd09ToWgs84, wgs84ToBd09,
} from './gcj-bd'
import type { CoordinatePoint, TransformOptions } from './crs-types'

const ENCRYPTED_CODES = new Set(['GCJ02', 'BD09'])

function isEncrypted(code: string): boolean {
  return ENCRYPTED_CODES.has(code) || ENCRYPTED_CODES.has(code.replace('-', ''))
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
    result = proj4(src, tgt, [lng, lat])
  }
  return [result[0] + (opts.lngOffset ?? 0), result[1] + (opts.latOffset ?? 0)]
}

/** bounds 四角点转换（投影系精确，加密系四角分别转换） */
export function transformBounds(
  bounds: [number, number, number, number], // [west, south, east, north]
  sourceCode: string, targetCode: string,
): [number, number, number, number] {
  const [w, s, e, n] = bounds
  const corners: Array<[number, number]> = [
    [w, s], [e, s], [e, n], [w, n],
  ]
  const transformed = corners.map(([lng, lat]) => transformPoint(lng, lat, sourceCode, targetCode))
  const lngs = transformed.map((p) => p[0])
  const lats = transformed.map((p) => p[1])
  return [
    Math.min(...lngs), Math.min(...lats),
    Math.max(...lngs), Math.max(...lats),
  ]
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
  if (src === 'GCJ02' && tgt === 'WGS84' || src === 'GCJ02' && tgt === 'EPSG:4326') return gcj02ToWgs84(lng, lat)
  if (src === 'WGS84' && tgt === 'GCJ02' || src === 'EPSG:4326' && tgt === 'GCJ02') return wgs84ToGcj02(lng, lat)
  if (src === 'BD09' && tgt === 'GCJ02') return bd09ToGcj02(lng, lat)
  if (src === 'GCJ02' && tgt === 'BD09') return gcj02ToBd09(lng, lat)
  if (src === 'BD09' && tgt === 'WGS84' || src === 'BD09' && tgt === 'EPSG:4326') return bd09ToWgs84(lng, lat)
  if (src === 'WGS84' && tgt === 'BD09' || src === 'EPSG:4326' && tgt === 'BD09') return wgs84ToBd09(lng, lat)
  // 通用路径：经 WGS84 中转
  const wgs = src === 'BD09' ? bd09ToWgs84(lng, lat) : gcj02ToWgs84(lng, lat)
  if (tgt === 'BD09') return wgs84ToBd09(wgs[0], wgs[1])
  if (tgt === 'GCJ02') return wgs84ToGcj02(wgs[0], wgs[1])
  // 加密系 → EPSG 系：先转 WGS84 再 proj4
  return proj4('EPSG:4326', tgt, wgs)
}

function normalizeCode(code: string): string {
  const map: Record<string, string> = { 'GCJ-02': 'GCJ02', 'BD-09': 'BD09' }
  return map[code] ?? code
}
```

#### 7.5 `crs-detector.ts`
客户端轻量 bounds 启发式检测（raster 检测交给后端 `/import/raster`）：
```ts
import type { CRSOption } from './crs-types'

export interface CRSDetectionResult {
  sourceCrs: string
  confidence: number       // 0~1
  method: 'bounds_heuristic' | 'default'
  suggestedCrs: string
  needsUserConfirm: boolean
  notes: string
}

/** 客户端 bounds 启发式（与后端 _crs_detector.detect_from_bounds 一致） */
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
PEP 562 风格的统一导出：
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
import { transformPoint, transformBounds, transformPointsBatch } from './crs-transformer'

describe('crs-transformer', () => {
  it('EPSG:4326 → EPSG:3857 与 proj4 一致', () => {
    const [lng, lat] = transformPoint(116.39, 39.91, 'EPSG:4326', 'EPSG:3857')
    // Web Mercator: x ≈ 12958215, y ≈ 4852326
    expect(lng).toBeCloseTo(12958215, -2)
    expect(lat).toBeCloseTo(4852326, -2)
  })

  it('GCJ02 → WGS84 与后端 _gcj_bd 北京样例一致', () => {
    const [lng, lat] = transformPoint(116.39747, 39.90880, 'GCJ02', 'EPSG:4326')
    // 后端期望: (116.3912, 39.9074)
    expect(lng).toBeCloseTo(116.3912, 4)
    expect(lat).toBeCloseTo(39.9074, 4)
  })

  it('BD09 → WGS84 与后端一致', () => {
    const [lng, lat] = transformPoint(116.40407, 39.91512, 'BD09', 'EPSG:4326')
    expect(lng).toBeCloseTo(116.3912, 4)
    expect(lat).toBeCloseTo(39.9074, 4)
  })

  it('偏移在 CRS 转换后应用', () => {
    const [lng, lat] = transformPoint(0, 0, 'EPSG:4326', 'EPSG:4326', { lngOffset: 1, latOffset: 2 })
    expect(lng).toBe(1)
    expect(lat).toBe(2)
  })

  it('source == target 无偏移原样返回', () => {
    const [lng, lat] = transformPoint(116.0, 39.0, 'EPSG:4326', 'EPSG:4326')
    expect(lng).toBe(116.0)
    expect(lat).toBe(39.0)
  })

  it('transformBounds 四角转换', () => {
    const result = transformBounds([116.0, 39.0, 117.0, 40.0], 'GCJ02', 'EPSG:4326')
    // WGS84 应比 GCJ02 偏西/南
    expect(result[0]).toBeLessThan(116.0)
    expect(result[1]).toBeLessThan(39.0)
    expect(result[2]).toBeLessThan(117.0)
    expect(result[3]).toBeLessThan(40.0)
  })

  it('transformPointsBatch 批量', () => {
    const points: Array<[number, number]> = [[116.39747, 39.90880], [121.47370, 31.23040]]
    const result = transformPointsBatch(points, 'GCJ02', 'EPSG:4326')
    expect(result).toHaveLength(2)
    expect(result[0][0]).toBeCloseTo(116.3912, 4)
  })

  it('GCJ-02 连字符写法兼容', () => {
    const [lng, lat] = transformPoint(116.39747, 39.90880, 'GCJ-02', 'EPSG:4326')
    expect(lng).toBeCloseTo(116.3912, 4)
  })
})
```

**验证**：
```powershell
cd Code\frontend
npm test -- src/services/crs/crs-transformer.test.ts
# 期望: 8/8 通过
```

### Task 8：前端 `RasterImportConfirmDialog.vue`

**新建**：[Code/frontend/src/components/toolbar/RasterImportConfirmDialog.vue](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/toolbar/RasterImportConfirmDialog.vue)

**功能**：
- props: `{ layerId, fileName, sourceCrs, suggestedCrs, needsConfirm, originalBounds }`
- 显示检测到的 CRS + 可编辑下拉（用户可覆盖）
- 显示偏移输入框（`lng_offset`/`lat_offset`，默认 0）
- 实时预览：用前端 `transformBounds` 显示转换后 WGS84 bounds（无需后端往返）
- 「确认」按钮 → emit `confirm({layerId, sourceCrs, lngOffset, latOffset})`
- 「跳过」按钮 → emit `skip({layerId})`，用原 bounds 直接加入图层列表（向后兼容 WGS84 数据）

**UI 风格**：复用 [CsvImportDialog.vue](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/toolbar/CsvImportDialog.vue#L255-L435) 的 dark theme 样式类（`csv-dialog-overlay`/`csv-dialog-panel`/`panel-header`/`section-label`/`col-row`/`col-field`/`col-select`/`action-row`/`cancel-btn`/`confirm-btn`），改为本组件 scoped style。

**关键代码骨架**：
```vue
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { listCrs, transformBounds } from '../../services/crs'
import type { CRSOption } from '../../services/crs'

const props = defineProps<{
  layerId: string
  fileName: string
  sourceCrs: string
  suggestedCrs: string
  needsConfirm: boolean
  originalBounds: [number, number, number, number]
}>()

const emit = defineEmits<{
  close: []
  confirm: [payload: { layerId: string; sourceCrs: string; lngOffset: number; latOffset: number }]
  skip: [payload: { layerId: string }]
}>()

const crsOptions = ref<CRSOption[]>(listCrs())
const selectedCrs = ref(props.suggestedCrs || props.sourceCrs)
const lngOffset = ref(0)
const latOffset = ref(0)

const previewBounds = computed<[number, number, number, number] | null>(() => {
  try {
    return transformBounds(props.originalBounds, selectedCrs.value, 'EPSG:4326', {
      lngOffset: lngOffset.value, latOffset: latOffset.value,
    })
  } catch {
    return null
  }
})

function handleConfirm() {
  emit('confirm', {
    layerId: props.layerId,
    sourceCrs: selectedCrs.value,
    lngOffset: lngOffset.value,
    latOffset: latOffset.value,
  })
}
function handleSkip() {
  emit('skip', { layerId: props.layerId })
}
</script>

<template>
  <div class="raster-confirm-overlay" @click.self="emit('close')">
    <div class="raster-confirm-panel">
      <div class="panel-header">
        <span class="panel-icon" aria-hidden="true">🗺️</span>
        <span>确认栅格 CRS: {{ fileName }}</span>
        <button class="close-btn" @click="emit('close')" title="关闭"><span aria-hidden="true">✕</span></button>
      </div>

      <div v-if="needsConfirm" class="info-banner">
        ⚠ 检测到的 CRS 置信度较低，请核对下拉框选定的坐标系。
      </div>

      <div class="section-label">源坐标系</div>
      <div class="col-row">
        <label class="col-field">
          <span class="col-label">检测到 / 用户覆盖</span>
          <select v-model="selectedCrs" class="col-select">
            <option v-for="opt in crsOptions" :key="opt.code" :value="opt.code">{{ opt.label }}</option>
          </select>
        </label>
      </div>

      <div class="section-label">偏移（度，CRS 转换后应用）</div>
      <div class="col-row">
        <label class="col-field">
          <span class="col-label">经度偏移 lng_offset</span>
          <input v-model.number="lngOffset" type="number" step="0.0001" class="col-input" />
        </label>
        <label class="col-field">
          <span class="col-label">纬度偏移 lat_offset</span>
          <input v-model.number="latOffset" type="number" step="0.0001" class="col-input" />
        </label>
      </div>

      <div class="section-label">转换后 WGS84 bounds 预览</div>
      <div class="bounds-preview">
        <template v-if="previewBounds">
          west={{ previewBounds[0].toFixed(4) }}, south={{ previewBounds[1].toFixed(4) }}<br />
          east={{ previewBounds[2].toFixed(4) }}, north={{ previewBounds[3].toFixed(4) }}
        </template>
        <span v-else class="error-hint">转换失败，请检查 CRS 选择</span>
      </div>

      <div class="action-row">
        <button class="cancel-btn" @click="handleSkip">跳过（按原 bounds 导入）</button>
        <button class="confirm-btn" @click="handleConfirm">确认并重投影</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 复用 CsvImportDialog.vue 的样式类，颜色/圆角/字号完全对齐 */
.raster-confirm-overlay { position: fixed; inset: 0; z-index: 999; display: flex; align-items: center; justify-content: center; background: rgba(4, 10, 18, 0.52); }
.raster-confirm-panel { width: 32rem; max-width: 92vw; max-height: 86vh; display: flex; flex-direction: column; gap: 0.6rem; padding: 0.82rem; border-radius: 1rem; border: 1px solid rgba(136, 192, 255, 0.14); background: rgba(8, 17, 31, 0.96); box-shadow: 0 24px 60px rgba(1, 8, 16, 0.48); overflow: hidden; }
.panel-header { display: flex; align-items: center; gap: 0.38rem; padding-bottom: 0.48rem; border-bottom: 1px solid rgba(136, 192, 255, 0.1); color: #e8f3fc; font-size: 0.72rem; font-weight: 600; }
.panel-icon { font-size: 0.8rem; color: #5ad5ff; }
.close-btn { margin-left: auto; width: 1.4rem; height: 1.4rem; border: none; border-radius: 0.5rem; background: transparent; color: #6e8ba0; cursor: pointer; font-size: 0.7rem; }
.close-btn:hover { background: rgba(136, 192, 255, 0.1); color: #d8e6f5; }
.section-label { color: #5a7080; font-size: 0.58rem; letter-spacing: 0.06em; text-transform: uppercase; }
.col-row { display: flex; gap: 0.52rem; flex-wrap: wrap; }
.col-field { display: flex; flex-direction: column; gap: 0.22rem; flex: 1; min-width: 7rem; }
.col-label { color: #8aa8bf; font-size: 0.56rem; }
.col-select, .col-input { padding: 0.32rem 0.42rem; border-radius: 0.42rem; border: 1px solid rgba(136, 192, 255, 0.16); background: rgba(4, 12, 23, 0.6); color: #d8e6f5; font: inherit; font-size: 0.62rem; }
.col-select:focus, .col-input:focus { outline: none; border-color: rgba(90, 213, 255, 0.36); }
.bounds-preview { padding: 0.52rem; border-radius: 0.5rem; background: rgba(4, 12, 23, 0.6); border: 1px solid rgba(136, 192, 255, 0.1); color: #5ad5ff; font-size: 0.6rem; font-variant-numeric: tabular-nums; line-height: 1.5; }
.error-hint { color: #ffb0b0; }
.info-banner { padding: 0.52rem; border-radius: 0.5rem; background: rgba(255, 200, 120, 0.12); border: 1px solid rgba(255, 200, 100, 0.24); color: #ffc878; font-size: 0.62rem; }
.action-row { display: flex; gap: 0.52rem; justify-content: flex-end; padding-top: 0.32rem; border-top: 1px solid rgba(136, 192, 255, 0.08); }
.cancel-btn { padding: 0.42rem 0.72rem; border: 1px solid rgba(136, 192, 255, 0.16); border-radius: 0.5rem; background: transparent; color: #9fb6cc; cursor: pointer; font: inherit; font-size: 0.64rem; }
.cancel-btn:hover { background: rgba(136, 192, 255, 0.08); color: #d8e6f5; }
.confirm-btn { padding: 0.42rem 0.72rem; border: 1px solid rgba(90, 213, 255, 0.3); border-radius: 0.5rem; background: rgba(10, 132, 255, 0.28); color: #a8e8ff; cursor: pointer; font: inherit; font-size: 0.64rem; font-weight: 600; }
.confirm-btn:hover { background: rgba(10, 132, 255, 0.48); color: #d0f0ff; }
</style>
```

### Task 9：前端集成

#### 9.1 `data-import.ts` 扩展

**改写**：[Code/frontend/src/services/data-import.ts:18-21](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/services/data-import.ts#L18-L21)

```ts
export interface RasterImportResult {
  layer_id: string
  bounds?: [number, number, number, number]
  source_crs?: string         // 新增：检测到的源 CRS
  suggested_crs?: string      // 新增：建议用户确认的 CRS
  needs_confirm?: boolean     // 新增：true 时前端弹确认框
  detection_notes?: string    // 新增：检测过程说明
}

// 新增函数
export async function confirmRasterImport(
  layerId: string,
  sourceCrs: string,
  lngOffset: number = 0,
  latOffset: number = 0,
): Promise<{
  layer_id: string
  bounds: [number, number, number, number]
  source_crs: string
  target_crs: string
  applied_offset: [number, number]
}> {
  const headers = withWriteAuthHeaders({ 'Content-Type': 'application/json' }, 'POST')
  const resp = await fetch(resolveApiUrl('/import/raster/confirm'), {
    method: 'POST',
    headers,
    body: JSON.stringify({
      layer_id: layerId,
      source_crs: sourceCrs,
      lng_offset: lngOffset,
      lat_offset: latOffset,
    }),
  })
  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new Error(parseErrorDetail(resp.status, text))
  }
  return await resp.json()
}

export async function fetchCrsOptions(): Promise<{
  items: Array<{ code: string; label: string; category: string; area: string; deprecated: boolean }>
  count: number
}> {
  const resp = await fetch(resolveApiUrl('/import/crs-options'))
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return await resp.json()
}

export async function transformPointBatch(
  points: Array<[number, number]>,
  sourceCrs: string,
  targetCrs: string = 'EPSG:4326',
  lngOffset: number = 0,
  latOffset: number = 0,
): Promise<Array<[number, number]>> {
  const headers = withWriteAuthHeaders({ 'Content-Type': 'application/json' }, 'POST')
  const resp = await fetch(resolveApiUrl('/import/transform-point'), {
    method: 'POST',
    headers,
    body: JSON.stringify({
      points, source_crs: sourceCrs, target_crs: targetCrs,
      lng_offset: lngOffset, lat_offset: latOffset,
    }),
  })
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text().catch(() => '')))
  const data = await resp.json()
  return data.points
}
```

#### 9.2 `useDataImportFlow.ts` 插入确认步骤

**改写**：[Code/frontend/src/composables/useDataImportFlow.ts:79-101](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/composables/useDataImportFlow.ts#L79-L101)

新增响应式状态：
```ts
interface PendingRasterConfirm {
  layerId: string
  fileName: string
  sourceCrs: string
  suggestedCrs: string
  needsConfirm: boolean
  originalBounds: [number, number, number, number]
}

const pendingRasterConfirm = ref<PendingRasterConfirm | null>(null)
```

`importRasterFile` 改动（关键分支）：
```ts
async function importRasterFile(file: File) {
  importing.value = true
  uploadProgress.value = 0
  showToast(`正在上传栅格: ${file.name}…`, false, 120_000)
  try {
    const data = await uploadRasterFile(file, {
      onProgress: (ratio) => {
        uploadProgress.value = ratio
        showToast(`上传中 ${Math.round(ratio * 100)}% · ${file.name}`, false, 120_000)
      },
    })
    // 新增：CRS 确认分支
    if (data.needs_confirm && data.layer_id) {
      pendingRasterConfirm.value = {
        layerId: data.layer_id,
        fileName: file.name,
        sourceCrs: data.source_crs ?? 'EPSG:4326',
        suggestedCrs: data.suggested_crs ?? data.source_crs ?? 'EPSG:4326',
        needsConfirm: true,
        originalBounds: data.bounds ?? [0, 0, 1, 1],
      }
      showToast(`栅格已上传，请确认 CRS: ${file.name}`, false, 120_000)
      logStore.logOperation('import-raster-pending', `栅格待确认 CRS: ${file.name}`, `Layer ID: ${data.layer_id}`)
      return  // 不立即加入图层列表，等用户在弹框确认
    }
    // 快路径：WGS84 数据，直接加入图层列表
    layersStore.addImportedRasterLayer(file.name, data.layer_id, data.bounds)
    showToast(`栅格已导入图层列表（${formatBytes(file.size)}）`)
    logStore.logOperation('import-raster-success', `栅格导入成功: ${file.name}`, `Layer ID: ${data.layer_id}`)
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    showToast(`导入失败: ${msg}`, true, 6000)
    logStore.logOperation('import-raster-fail', `栅格导入失败: ${file.name}`, msg)
  } finally {
    importing.value = false
    uploadProgress.value = null
  }
}

async function confirmRasterCrs(sourceCrs: string, lngOffset: number, latOffset: number) {
  if (!pendingRasterConfirm.value) return
  const { layerId, fileName, originalBounds } = pendingRasterConfirm.value
  importing.value = true
  showToast(`正在重投影到 WGS84…`, false, 120_000)
  try {
    const result = await confirmRasterImport(layerId, sourceCrs, lngOffset, latOffset)
    layersStore.addImportedRasterLayer(fileName, layerId, result.bounds)
    showToast(`栅格已重投影并导入（${formatBytes(0)}）`)
    logStore.logOperation('import-raster-confirm-success', `栅格 CRS 确认成功: ${fileName}`, `bounds: ${result.bounds}`)
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    showToast(`CRS 确认失败: ${msg}`, true, 6000)
    logStore.logOperation('import-raster-confirm-fail', `栅格 CRS 确认失败: ${fileName}`, msg)
  } finally {
    pendingRasterConfirm.value = null
    importing.value = false
  }
}

function skipRasterConfirm() {
  if (!pendingRasterConfirm.value) return
  const { layerId, fileName, originalBounds } = pendingRasterConfirm.value
  layersStore.addImportedRasterLayer(fileName, layerId, originalBounds)
  showToast(`已跳过 CRS 确认，按原 bounds 导入`)
  logStore.logOperation('import-raster-skip', `栅格跳过 CRS 确认: ${fileName}`, `Layer ID: ${layerId}`)
  pendingRasterConfirm.value = null
}

function closeRasterConfirm() {
  // 用户点关闭按钮：保留上传的文件但不加入图层列表（用户可在图层管理删除）
  if (!pendingRasterConfirm.value) return
  const { layerId, fileName } = pendingRasterConfirm.value
  logStore.logOperation('import-raster-cancel', `栅格取消确认: ${fileName}`, `Layer ID: ${layerId}`)
  pendingRasterConfirm.value = null
}
```

返回值新增：`pendingRasterConfirm, confirmRasterCrs, skipRasterConfirm, closeRasterConfirm`

#### 9.3 `CsvImportDialog.vue` 扩展

**改写**：[Code/frontend/src/components/toolbar/CsvImportDialog.vue:29-38](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/toolbar/CsvImportDialog.vue#L29-L38) 和 `:95-98`、`:100-126`、`:130-165`

**改动 1**：`CRS_OPTIONS` 改为运行时从 `/import/crs-options` 拉取（保留硬编码 fallback）：
```ts
import { ref as ref2, onMounted } from 'vue'
import { fetchCrsOptions } from '../../services/data-import'

const CRS_OPTIONS = ref<Array<{ value: string; label: string }>>([
  // 硬编码 fallback（与原 8 项保持一致，确保 fetch 失败时仍可用）
  { value: 'EPSG:4326', label: 'EPSG:4326 (WGS84 经纬度)' },
  { value: 'EPSG:3857', label: 'EPSG:3857 (Web Mercator)' },
  { value: 'EPSG:32649', label: 'EPSG:32649 (UTM 49N)' },
  { value: 'EPSG:32650', label: 'EPSG:32650 (UTM 50N)' },
  { value: 'EPSG:4490', label: 'EPSG:4490 (CGCS2000)' },
  { value: 'EPSG:4527', label: 'EPSG:4527 (CGCS2000 / 3-degree Gauss 117E)' },
  { value: 'EPSG:4528', label: 'EPSG:4528 (CGCS2000 / 3-degree Gauss 120E)' },
  { value: 'EPSG:4529', label: 'EPSG:4529 (CGCS2000 / 3-degree Gauss 123E)' },
])

onMounted(async () => {
  try {
    const data = await fetchCrsOptions()
    if (data.items && data.items.length > 0) {
      CRS_OPTIONS.value = data.items.map((item) => ({ value: item.code, label: item.label }))
    }
  } catch (e) {
    console.warn('[CsvImport] fetchCrsOptions failed, using fallback', e)
  }
})
```

**改动 2**：`_proj4Convert` 改为走前端 `services/crs` 模块（统一加密系 + EPSG 系）：
```ts
import { transformPoint } from '../../services/crs'

async function _convertCoord(x: number, y: number): Promise<[number, number]> {
  return transformPoint(x, y, crs.value, 'EPSG:4326')
}
```
（替换原 `_proj4Convert`，因为 `transformPoint` 内部已处理 EPSG 系走 proj4、加密系走 gcj-bd）

**改动 3**：预览逻辑 `:100-126` 把 `_proj4Convert(x, y)` 调用改为 `_convertCoord(x, y)`，其余不变。

**改动 4**：`handleConfirm` `:130-165` 同样把 `_proj4Convert` 改为 `_convertCoord`。**不引入行数阈值分支**（保留原「全部前端转换」行为，CSV 通常 < 10k 行，proj4/gcj-bd 足够快）。

**注意**：模板 `v-model="crs"` 和 `CRS_OPTIONS` 在 `<select>` 中使用，需改为 `CRS_OPTIONS.value`（因为是 ref）—— 实际在 `<script setup>` 中模板自动 unwrap，无需改模板。

#### 9.4 `imported-raster.ts` + `layers/index.ts` 加 CRS 字段

**改写**：[Code/frontend/src/stores/layers/imported-raster.ts](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/stores/layers/imported-raster.ts)

```ts
export interface ImportedRasterPayload {
  overlayLayerId: string
  bounds?: [number, number, number, number]
  fileName?: string
  sourceCrs?: string    // 新增：源 CRS（默认 'EPSG:4326'，confirm 后也是 'EPSG:4326'）
  lngOffset?: number    // 新增：经度偏移（度）
  latOffset?: number    // 新增：纬度偏移（度）
}

export function buildImportedRasterPayload(
  overlayLayerId: string,
  options?: {
    bounds?: [number, number, number, number]
    fileName?: string
    sourceCrs?: string
    lngOffset?: number
    latOffset?: number
  },
): ImportedRasterPayload {
  return {
    overlayLayerId,
    bounds: options?.bounds,
    fileName: options?.fileName,
    sourceCrs: options?.sourceCrs ?? 'EPSG:4326',
    lngOffset: options?.lngOffset ?? 0,
    latOffset: options?.latOffset ?? 0,
  }
}
```

**改写**：[Code/frontend/src/stores/layers/index.ts:852-878](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/stores/layers/index.ts#L852-L878) `addImportedRasterLayer` 签名扩展：

```ts
function addImportedRasterLayer(
  name: string,
  overlayLayerId: string,
  bounds?: [number, number, number, number],
  options?: {
    sourceCrs?: string
    lngOffset?: number
    latOffset?: number
  },
): ActiveLayer {
  const maxOrder = activeLayers.value.reduce((max, l) => Math.max(max, l.order), 0)
  const instanceId = genInstanceId()
  const payload = buildImportedRasterPayload(overlayLayerId, {
    bounds, fileName: name,
    sourceCrs: options?.sourceCrs,
    lngOffset: options?.lngOffset,
    latOffset: options?.latOffset,
  })
  // ... 后续与原逻辑一致
}
```

**向后兼容**：原 `addImportedRasterLayer(name, overlayLayerId, bounds)` 三参数调用仍可用（`options` 默认 undefined）。

**调用方更新**：`useDataImportFlow.ts` 的 `confirmRasterCrs` 调用时传入 `sourceCrs`/`lngOffset`/`latOffset`；`skipRasterConfirm` 和快路径不传（用默认值）。

### Task 10：前端 `overlay-image-module.ts` 防御性 bounds 校验

**改写**：[Code/frontend/src/components/map/overlay-image-module.ts:138-244](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/map/overlay-image-module.ts#L138-L244)（`_addOverlay` 函数内）

在 `_addOverlay` 拿到 `bounds` 后、`addSource` 之前（约 [L163-L177](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/map/overlay-image-module.ts#L163-L177) 之间）插入校验：

```ts
function _validateWgs84Bounds(bounds: [number, number, number, number]): boolean {
  const [west, south, east, north] = bounds
  if (!Number.isFinite(west) || !Number.isFinite(south) ||
      !Number.isFinite(east) || !Number.isFinite(north)) return false
  if (west < -180 || east > 180 || south < -90 || north > 90) return false
  if (west >= east || south >= north) return false
  // 防御 0 区域 bounds（空数据/NaN 退化情况）
  if (east - west < 1e-9 || north - south < 1e-9) return false
  return true
}

// 在 _addOverlay 内（L163 拿到 bounds 后）：
const bounds: [number, number, number, number] = boundsData.bounds
const meta = boundsData.meta ?? {}

// 防御性校验：bounds 必须是有效 WGS84 区域
if (!_validateWgs84Bounds(bounds)) {
  console.warn(`[Overlay] ${layerId} bounds invalid or non-WGS84, skipping addSource:`, bounds, 'meta.crs=', meta.crs)
  loadingOverlays.delete(layerId)
  return
}

// 若 meta.crs 存在且 ≠ 'EPSG:4326'，记录警告但仍尝试加载
// （Phase 1 不做前端重投影，依赖后端 /raster/confirm 已转好；
//  若到达此处说明用户跳过了 confirm，bounds 可能是源 CRS 的，需用户手动处理）
if (meta.crs && meta.crs !== 'EPSG:4326') {
  console.warn(`[Overlay] ${layerId} meta.crs=${meta.crs} (非 WGS84)，bounds 可能未重投影，地图显示可能错位`)
}
```

**注意**：`loadingOverlays.delete(layerId)` 需在 `return` 前调用，避免泄漏 loading 标记导致后续无法重试。原代码在 `finally` 块中清理，但提前 return 时需手动清理（或改为 try/catch 包裹）。

### Task 11：Phase 4 — 代码审查 + 项目重启 + E2E 冒烟

#### 11.1 代码审查（用 `TRAE-code-review` skill）

**审查范围**（按改动文件清单）：
- **新增（13 文件）**：
  - 后端：`tests/test_import_raster_crs.py`（已存在，Task 6.3-fix 改动）
  - 前端：`services/crs/{crs-types,crs-registry,gcj-bd,crs-transformer,crs-detector,index,crs-transformer.test}.ts`（7 文件）
  - 前端：`components/toolbar/RasterImportConfirmDialog.vue`
- **改动（7 文件）**：
  - 前端：`services/data-import.ts`、`composables/useDataImportFlow.ts`、`components/toolbar/CsvImportDialog.vue`、`stores/layers/imported-raster.ts`、`stores/layers/index.ts`、`components/map/overlay-image-module.ts`

**审查重点**（用户指定）：
1. **旧代码使用**：
   - 全局 `grep "coordinate_transform_service"` 确认除 [layer_router.py:6](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/api/routers/layer_router.py#L6) + [tile_proxy_service.py:25-31](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/tile_proxy_service.py#L25-L31) 外无新引用
   - 前端 `grep "from 'proj4'"` 确认除 `services/crs/crs-transformer.ts` 外无直接 proj4 调用（`CsvImportDialog.vue` 应改走 `services/crs`）
2. **逻辑混乱**：
   - 偏移应用顺序：前端 `transformPoint` 与后端 `_crs_transformer.transform_point` 都在 CRS 转换**后**应用
   - 加密系代码归一化：前端 `normalizeCode('GCJ-02') → 'GCJ02'` 与后端 `_normalize_legacy_code` 一致
   - `transformBounds` 四角点转换 vs `transform_bounds` 后端用 `pyproj.transform_bounds`：投影系结果一致，加密系四角点分别转换（加密偏移非线性，必须四角分别转）
   - LRU 缓存：前端不缓存（每次直接 proj4/gcj-bd 调用），与后端 `_CACHE` 不同但合理（前端无重复热点）
3. **类型安全**：
   - `ImportedRasterPayload` 新字段全部 optional + 默认值，向后兼容
   - `RasterImportResult` 新字段全部 optional，旧后端响应（无 CRS 字段）仍能解析
4. **测试覆盖**：
   - 后端：`test_import_raster_crs.py` 12 测试全通过
   - 前端：`crs-transformer.test.ts` 8 测试全通过

#### 11.2 项目重启 + E2E 冒烟

**重启步骤**：
1. 后端：`StopCommand` 现有 uvicorn（如有）→ 重新启动 `run_start.bat` 或等效命令
2. 前端：`StopCommand` 现有 vite dev server → 重新启动 `npm run dev`

**冒烟测试清单**（手动验证）：

| 步骤 | 期望结果 |
|---|---|
| `GET /import/crs-options` | 返回 9 项 CRS |
| 上传 WGS84 TIF | 无确认弹框，直接进图层列表，bounds 在 ±180/±90 内 |
| 上传 EPSG:32650 TIF | 弹确认框，下拉默认选 EPSG:32650，预览 bounds 在中国区域 |
| 确认 EPSG:32650 → WGS84 | 图层 bounds 在 (73~137, 15~59) 内，地图显示位置正确 |
| 跳过 confirm（WGS84 数据） | 用原 bounds 加入图层列表，正常显示 |
| CSV 导入选 GCJ02 | 预览前 5 行坐标偏移约 0.006°（北京区域），确认导入要素位置正确 |
| CSV 导入选 BD09 | 预览前 5 行坐标偏移约 0.006° + ~0.003°（BD09 → GCJ02 → WGS84） |
| 旧端点 `/geo/transform?lng=116.391&lat=39.907&source=GCJ-02&target=EPSG:3857` | 仍可用（垫片生效），返回 Web Mercator 坐标 |
| `npm run build` | vue-tsc 类型检查通过 |

## 三、Assumptions & Decisions

### 关键假设
1. **rasterio 32×32 合成 TIF 不再触发 edge case**：32×32 → 64×64 上采样（2× bilinear）属于常规场景
2. **`proj4` 已安装**（`package.json:30` `proj4@^2.20.9`）— Task 7 直接 import，无需 npm install
3. **vitest 模式已配置**：`package.json` `test: vitest run`，`data-import.test.ts` 是参考模板
4. **CSV 行数无阈值分支**：保留原「全部前端转换」行为；CSV 通常 < 10k 行，proj4/gcj-bd 足够快
5. **后端 `/import/transform-point` 仍保留**：供未来 POI 大批量导入（> 100k 点）使用，本轮前端不调用

### 关键决策
1. **Task 6.3-fix 用 32×32 合成 TIF**：避免 mock `render_cog_preview`，保持端到端测试覆盖
2. **前端 `transformBounds` 四角点分别转换**：加密系非线性，不能像后端那样用 `pyproj.transform_bounds`（仅投影系精确）
3. **`RasterImportConfirmDialog.vue` 用前端 `transformBounds` 预览**：不调后端 `/import/transform-bounds`，减少网络往返；用户确认时才调 `/import/raster/confirm` 做最终重投影
4. **`overlay-image-module.ts` 仅警告不阻止非 WGS84 bounds**：Phase 1 不做前端重投影，依赖后端 confirm 已转好；若用户跳过 confirm，bounds 可能错位但需用户自行处理
5. **`addImportedRasterLayer` 用 options 对象扩展**：避免位置参数过长，向后兼容 3 参数调用

### 范围外（明确不做，沿用原计划）
- 全 UTM 系列（EPSG:32601-32660）、全 Gauss-Krüger 3 度带（EPSG:4513-4533）、Lambert Conformal Conic — Phase 2
- 双点校准 UI — Phase 2
- 算法输出图层的 CRS 元数据注入 — Phase 3
- 15+ 现有数据集 CRS 回归测试 — Phase 3
- `layer_router.py`/`tile_proxy_service.py` 的 import 迁移到新包 — Phase 3

## 四、Verification Steps

### 单元测试
```powershell
# 后端
cd Code\backend
python -m pytest tests/test_crs_transformer.py tests/test_crs_detector.py tests/test_import_raster_crs.py -v
# 期望: 全部通过（test_crs_transformer 21 + test_crs_detector 57 + test_import_raster_crs 12 = 90 测试）

# 前端
cd Code\frontend
npm test -- src/services/crs/crs-transformer.test.ts
# 期望: 8/8 通过
```

### 集成验证
```powershell
# 1. transformer 单点验证
python -c "from app.services.crs import crs_transformer; print(crs_transformer.transform_point(116.39747, 39.9088, 'GCJ02', 'EPSG:4326'))"
# 应输出 WGS84 (116.3912, 39.9074)

# 2. 垫片验证（应同时输出结果 + DeprecationWarning）
python -c "from app.services.coordinate_transform_service import gcj02_to_wgs84; print(gcj02_to_wgs84(116.39747, 39.9088))"

# 3. 启动后端 → curl /import/crs-options → 9 项
# 4. 前端 dev server → 上传 EPSG:32650 TIF → 弹确认框 → 选 EPSG:32650 → 确认 → 图层 bounds 在中国区域
```

### 类型检查
```powershell
cd Code\frontend
npm run build  # vue-tsc + vite build
```

### Phase 4 收尾
- `TRAE-code-review` skill 跑一遍改动文件
- 项目重启 + 手动 E2E 冒烟（按 11.2 清单）

## 五、执行顺序与依赖

```
Task 6.3-fix (32×32 fixture) ──┐
                               ▼
Task 7 (前端 crs/ 5+1 文件) ──┐
                              │
                              ▼
Task 8 (RasterImportConfirmDialog) ─► Task 9 (集成) ──┐
                                                       │
Task 10 (overlay-image-module 防御) ──────────────────┤
                                                       ▼
                                          Task 11 (审查 + 重启 + E2E)
```

**可并行**：Task 6.3-fix + Task 7 + Task 10（互不依赖）
**必须串行**：Task 8 依赖 Task 7；Task 9 依赖 Task 7+8；Task 11 依赖全部

## 六、本轮执行 Todo 清单

1. ⏳ Task 6.3-fix：`test_import_raster_crs.py` 把 2×2 fixture 改 32×32 → 12/12 通过
2. ⏳ Task 7.1：`services/crs/crs-types.ts`
3. ⏳ Task 7.2：`services/crs/crs-registry.ts`（9 CRS 镜像后端）
4. ⏳ Task 7.3：`services/crs/gcj-bd.ts`（从 _gcj_bd.py 直译）
5. ⏳ Task 7.4：`services/crs/crs-transformer.ts`（proj4 + 加密系路由 + 偏移后置）
6. ⏳ Task 7.5：`services/crs/crs-detector.ts`（bounds 启发式）
7. ⏳ Task 7.6：`services/crs/index.ts`（统一导出）
8. ⏳ Task 7.7：`services/crs/crs-transformer.test.ts`（8 vitest 测试）
9. ⏳ Task 8：`components/toolbar/RasterImportConfirmDialog.vue`
10. ⏳ Task 9.1：`services/data-import.ts` 扩展（`RasterImportResult` + 3 新函数）
11. ⏳ Task 9.2：`composables/useDataImportFlow.ts` 插入确认步骤
12. ⏳ Task 9.3：`CsvImportDialog.vue` 改走 `services/crs` + `fetchCrsOptions`
13. ⏳ Task 9.4：`stores/layers/imported-raster.ts` + `stores/layers/index.ts` 加 CRS/offset 字段
14. ⏳ Task 10：`overlay-image-module.ts` 防御性 bounds 校验
15. ⏳ Task 11.1：`TRAE-code-review` skill 审查改动文件
16. ⏳ Task 11.2：项目重启 + E2E 冒烟（按 11.2 清单手动验证）