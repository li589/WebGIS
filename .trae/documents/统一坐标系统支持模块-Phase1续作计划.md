# 统一坐标系统支持模块 — Phase 1 续作计划

> **背景**：上一轮会话已完成 Task 1（CRS 包基础：`crs_types.py` + `crs_registry.py` + `_gcj_bd.py` + `__init__.py`，9 个 CRS 已注册，GCJ-02/BD-09 算法经北京天安门样例验证正确）。本计划接续 Task 2–11，完成 Phase 1 全部交付并执行用户要求的 Phase 4 代码审查与项目重启。

## 一、当前状态分析

### 1.1 已完成（Task 1，本轮不动）

| 文件 | 状态 | 关键内容 |
|---|---|---|
| [crs_types.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/crs_types.py) | ✅ | `CRSCategory` 枚举、`CRSDef` frozen dataclass、`CoordinatePoint` |
| [crs_registry.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/crs_registry.py) | ✅ | 9 个 CRS（3 地理 + 2 加密 + 4 投影）、`get_crs`/`list_crs`/`to_api_payload`、旧码归一化 |
| [_gcj_bd.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/_gcj_bd.py) | ✅ | 纯 Python GCJ-02/BD-09 算法，`_WGS84_A = 6378245.0`（Krasovsky 1940，故意值） |
| [__init__.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/__init__.py) | ✅ | PEP 562 延迟导入 `crs_transformer`/`crs_detector` |

### 1.2 关键集成点（本轮改造对象）

| 文件 | 现状 | 问题 |
|---|---|---|
| [coordinate_transform_service.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/coordinate_transform_service.py) | 纯 Python，含 `transform_point(lng,lat,source,target)` 与 5 个 GCJ/BD/3857 函数 | 与新模块算法重复，需转为 deprecated 垫片 |
| [layer_router.py:6](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/api/routers/layer_router.py#L6) | `from app.services.coordinate_transform_service import transform_point` 用于 `/geo/transform` 端点 | 仅 1 处调用，垫片透明兼容 |
| [tile_proxy_service.py:25-31](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/tile_proxy_service.py#L25-L31) | 导入 `bd09_to_gcj02`/`gcj02_to_wgs84`/`wgs84_to_bd09`/`wgs84_to_gcj02`/`CoordinatePoint`，用于底图 tile 坐标转换 | 5 处函数 + 1 处类型，垫片 re-export 兼容 |
| [overlay_registry.py:33-135](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/overlay_registry.py#L33-L135) | `OverlaySpec` 无 `crs` 字段，`meta_dict()` 不返回 CRS | 所有 bounds 隐式按 WGS84 处理，非 WGS84 数据前端错位 |
| [import_router.py:47-185](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/api/routers/import_router.py#L47-L185) | `POST /import/raster` 把源 CRS 写入 `meta.source_crs` 但 bounds **未转换**；前端拿到非 WGS84 bounds 直接用于 MapLibre image source → 错位 | 需新增 `/import/raster/confirm` + `/import/crs-options` + `/import/transform-point` + `/import/transform-bounds` 4 个端点 |
| [raster_preview_service.py:35-94](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/raster_preview_service.py#L35-L94) | `render_cog_preview()` 直接读源 band，不重投影 | 需新增 `render_cog_preview_reprojected()`，内部 `rasterio.warp.reproject` 到 WGS84 后再着色 |
| [CsvImportDialog.vue:29-38](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/toolbar/CsvImportDialog.vue#L29-L38) | 8 个 CRS 选项，全部用 proj4 客户端转换 | 缺 GCJ-02/BD-09/ETRS89/EASE-Grid；GCJ-02/BD-09 走客户端纯 TS 算法，其他仍走 proj4 |
| [data-import.ts:18-21](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/services/data-import.ts#L18-L21) | `RasterImportResult = {layer_id, bounds?}`，无 CRS | 需扩展 `source_crs`/`suggested_crs`/`needs_confirm` 字段 |
| [useDataImportFlow.ts:79-101](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/composables/useDataImportFlow.ts#L79-L101) | `importRasterFile()` 上传后直接 `addImportedRasterLayer`，无确认步骤 | 需在 `needs_confirm` 时弹出 `RasterImportConfirmDialog` |
| [imported-raster.ts:4-9](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/stores/layers/imported-raster.ts#L4-L9) | `ImportedRasterPayload` 无 CRS | 加 `sourceCrs?`/`lngOffset?`/`latOffset?` 字段 |
| [overlay-image-module.ts:190-199](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/map/overlay-image-module.ts#L190-L199) | `addSource(type:'image', coordinates:[bounds...])` 默认 WGS84 | 需在加载前防御性校验 bounds 经纬度范围（-180~180/-90~90），异常时记录警告并跳过 |

### 1.3 现有可复用模式

- **rasterio.warp.reproject 模式**：[spatial_aligner.py:88-98](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/algorithms/providers/Python/data_access/spatial_aligner.py#L88-L98) `resample_to_grid()` 已验证 `reproject(source, destination, src_transform, src_crs, dst_transform, dst_crs, resampling, src_nodata, dst_nodata)` 调用约定
- **rasterio.warp.transform_bounds**：memory 记录 `universal_reader.py:374` 已用此函数转 bounds
- **后端测试约定**：[tests/](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests) 下 20+ pytest 文件，已有 `conftest.py`
- **前端测试约定**：[data-import.test.ts](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/services/data-import.test.ts) 用 vitest，`describe/it/expect` 简洁风格
- **proj4 已装**：`proj4@^2.20.9`、`@types/proj4@^2.5.6`、`vitest@^4.1.10` 均在 [package.json](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/package.json) 已声明
- **pyproj 已装**（rasterio 传递依赖），但 [requirements.txt](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/requirements.txt) 未显式 pin，本轮补上

## 二、用户已锁定的设计决策

| 决策项 | 选择 | 含义 |
|---|---|---|
| 交付节奏 | 分阶段交付 | Phase 1 仅含 9 个 CRS，不一次性铺全 UTM/Gauss-Krüger/Lambert 全系列 |
| 偏移机制 | 显式 `lng_offset`/`lat_offset` 字段 + 双点校准 | 偏移在 CRS 转换**之后**应用；双点校准 UI 留 Phase 2 |
| 转换分工 | 前端预览（proj4 + 纯 TS GCJ-02/BD-09） + 后端最终转换（pyproj） | 前端实时预览精度足够，提交时后端用 pyproj 收口 |
| 检测时机 | 上传时检测 + 用户确认对话框 | TIF 上传后端用 rasterio 检测 CRS，前端弹框让用户确认/覆盖 |
| 收尾 | 代码审查（旧代码 + 逻辑混乱） + 项目重启 + E2E 冒烟 | 用户最后一条额外指令 |

## 三、Proposed Changes（按 Task 顺序）

### Task 2：后端 `crs/crs_transformer.py` + 单元测试

**新建**：[crs_transformer.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/crs_transformer.py)

**核心 API**：
```python
class CRSTransformer:
    _CACHE: dict[tuple[str, str], "pyproj.Transformer"] = {}  # 类级 LRU

    def transform_point(self, lng, lat, source_code, target_code,
                        lng_offset=0.0, lat_offset=0.0) -> CoordinatePoint
    def transform_bounds(self, west, south, east, north,
                         source_code, target_code) -> tuple[float, float, float, float]
    def transform_points_batch(self, points, source_code, target_code,
                               lng_offset=0.0, lat_offset=0.0) -> list[CoordinatePoint]

crs_transformer = CRSTransformer()  # 模块级单例
```

**实现要点**：
1. `transform_point`：
   - source == target：跳过 CRS 转换，仅应用偏移
   - source 或 target 是 `ENCRYPTED`（GCJ02/BD09）：路由到 `_gcj_bd` 模块，不走 pyproj
   - 混合路径（如 GCJ02 → EPSG:3857）：先 GCJ02 → WGS84（`_gcj_bd.gcj02_to_wgs84`），再 WGS84 → EPSG:3857（pyproj）
   - 否则：`pyproj.Transformer.from_crs(source, target, always_xy=True)`（关键：`always_xy=True` 因代码库统一用 (lng, lat)）
   - 偏移在最后应用：`return CoordinatePoint(lng=result.lng + lng_offset, lat=result.lat + lat_offset)`
2. `transform_bounds`：委托 `rasterio.warp.transform_bounds(src_crs, dst_crs, west, south, east, north, densify_pts=21)`，与 `universal_reader.py:374` 一致；加密系先转 WGS84 再走 rasterio
3. `transform_points_batch`：用 `pyproj.Transformer.itransform` 批量转，加密系逐点调用 `_gcj_bd`
4. LRU 缓存：`_CACHE` 按 `(source_code, target_code)` 缓存 `pyproj.Transformer` 实例（构造昂贵，线程安全）；加密系不缓存

**新建测试**：[tests/test_crs_transformer.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/test_crs_transformer.py)

测试用例（精度阈值写在常量里方便调整）：
- `EPSG:4326 → EPSG:3857` 与旧 `wgs84_to_epsg3857` 结果 1e-6 一致（北京 116.391, 39.907 → ~12958217, 4852327）
- `GCJ02 → EPSG:4326` 与 `gcj02_to_wgs84` 完全一致（同算法路径）
- `BD09 → EPSG:4326` 与 `bd09_to_wgs84` 完全一致
- `EPSG:32650 → EPSG:4326`：北京天安门 (447950, 4419460) → (116.391±0.001, 39.907±0.001)
- `EPSG:6933 → EPSG:4326`：EASE-Grid 中心点往返（先转 WGS84 再转回 6933，误差 < 1m）
- 偏移应用顺序：`transform_point(0, 0, 'EPSG:4326', 'EPSG:4326', 1.0, 2.0)` → `(1.0, 2.0)`
- 偏移在 CRS 转换后应用：`transform_point(116, 39, 'EPSG:4326', 'EPSG:3857', 1.0, 2.0)` 结果 = 纯转换结果 + (1.0, 2.0)
- LRU 命中：连续两次相同 (source, target) 调用，第二次 `_CACHE` 命中（用 `monkeypatch` 验证 `from_crs` 调用次数 = 1）
- source == target 且无偏移：原样返回

### Task 3：后端 `crs/crs_detector.py` + 单元测试

**新建**：[crs_detector.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/crs_detector.py)

**核心 API**：
```python
@dataclass(frozen=True)
class CRSDetectionResult:
    source_crs: str           # 检测到的 CRS code（如 'EPSG:32650'），未识别返回 'EPSG:4326' 作默认
    confidence: float         # 0.0~1.0
    method: str               # 'rasterio_crs' | 'geojson_crs' | 'mat_transform' | 'bounds_heuristic' | 'default'
    suggested_crs: str        # 等同 source_crs，前端展示用
    needs_user_confirm: bool  # confidence < 0.7 时为 True
    notes: str                # 检测过程说明

class CRSDetector:
    def detect_from_raster(self, path: Path) -> CRSDetectionResult
    def detect_from_geojson(self, geojson: dict) -> CRSDetectionResult
    def detect_from_bounds(self, bounds: tuple[float, float, float, float]) -> CRSDetectionResult

crs_detector = CRSDetector()  # 模块级单例
```

**实现要点**：
1. `detect_from_raster`：用 `rasterio.open(path).crs` 读 CRS，转字符串后用 `crs_registry.get_crs()` 反查；若 rasterio 返回 EPSG:4326 但 bounds 超出 ±180/±90 → 标记低 confidence 并提示用户可能是投影坐标系
2. `detect_from_geojson`：读 `geojson.crs.properties.name`（旧格式）或顶层 `crs` 字段；现代 GeoJSON 默认 EPSG:4326
3. `detect_from_bounds`：启发式 — west/east 在 ±180 内且 south/north 在 ±90 内 → 可能是地理坐标系（confidence 0.5）；数值 > 1000 → 投影坐标系（confidence 0.3，需用户确认）
4. 对 EPSG:4490（CGCS2000）和 EPSG:4326（WGS84）的区分：rasterio CRS 字符串里若含 `CGCS2000` 则判定 4490，否则 4326；两者数值上 ≈ 等价，转换误差可忽略

**新建测试**：[tests/test_crs_detector.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/test_crs_detector.py)

测试用例：
- 合成一个 WGS84 GeoTIFF（用 `rasterio.open(memfile)` 写入），检测返回 `EPSG:4326`，confidence ≥ 0.9
- GeoJSON 含 `crs: {properties: {name: 'urn:ogc:def:crs:EPSG::4490'}}` → 返回 `EPSG:4490`
- GeoJSON 无 crs 字段 → 默认 `EPSG:4326`，method=`default`
- bounds = (73, 15, 137, 59) → confidence 0.5，needs_user_confirm=True
- bounds = (447950, 4419460, 448000, 4419500) → 投影系，confidence 0.3，needs_user_confirm=True

### Task 4：转换 `coordinate_transform_service.py` 为 deprecated 垫片

**改写**：[coordinate_transform_service.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/coordinate_transform_service.py)

**策略**：保留所有旧函数签名（`gcj02_to_wgs84`/`bd09_to_wgs84`/`wgs84_to_epsg3857`/`wgs84_to_gcj02`/`wgs84_to_bd09`/`bd09_to_gcj02`/`transform_point` + `CoordinatePoint` 类型 + `CoordinateSystem` Literal），全部改为 re-export + 委托，加入 `DeprecationWarning`。

**关键代码骨架**：
```python
"""[Deprecated] 旧坐标转换服务 — 已由 app.services.crs 取代。

新代码应直接 from app.services.crs import crs_transformer。
本模块仅保留以兼容 layer_router.py 和 tile_proxy_service.py 旧调用，
将在 Phase 3+ 完全移除。
"""
from __future__ import annotations
import warnings
from typing import Literal

from app.services.crs import CoordinatePoint as _NewPoint
from app.services.crs._gcj_bd import (
    gcj02_to_wgs84 as _gcj02_to_wgs84,
    wgs84_to_gcj02 as _wgs84_to_gcj02,
    bd09_to_gcj02 as _bd09_to_gcj02,
    bd09_to_wgs84 as _bd09_to_wgs84,
    wgs84_to_bd09 as _wgs84_to_bd09,
)

CoordinateSystem = Literal['EPSG:3857', 'GCJ-02', 'BD-09']

# re-export 类型（二进制兼容：字段同为 lng/lat）
CoordinatePoint = _NewPoint

_DEPRECATION_MSG = "coordinate_transform_service is deprecated; use app.services.crs"

def gcj02_to_wgs84(lng, lat):
    warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
    return _gcj02_to_wgs84(lng, lat)

# ... 其他 4 个加密函数同样模式 ...

def wgs84_to_epsg3857(lng, lat):
    warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
    from app.services.crs import crs_transformer
    return crs_transformer.transform_point(lng, lat, 'EPSG:4326', 'EPSG:3857')

def transform_point(lng, lat, source, target='EPSG:3857'):
    """旧签名兼容：source/target 用 'GCJ-02'/'BD-09'/'EPSG:3857' 字面量。"""
    warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
    from app.services.crs import crs_transformer
    # 旧签名 source='GCJ-02' → 新代码 'GCJ02'
    src = 'GCJ02' if source == 'GCJ-02' else source
    tgt = 'BD09' if target == 'BD-09' else target
    return crs_transformer.transform_point(lng, lat, src, tgt)
```

**注意**：
- `tile_proxy_service.py` 导入的 5 个函数 + `CoordinatePoint` 类型全部 re-export，**零代码改动**即可兼容
- `layer_router.py:6` 的 `transform_point` 透明委托，旧签名 `'GCJ-02'`/`'BD-09'` 字面量在垫片内归一化
- 不删除 `tile_proxy_service.py`/`layer_router.py` 的 import 语句（Phase 3 再统一迁移，本轮范围控制）

### Task 5：`OverlaySpec.crs` 字段 + `meta_dict` 更新

**改写**：[overlay_registry.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/overlay_registry.py#L33-L135)

**改动点**：
1. `OverlaySpec` dataclass 新增字段（默认 `'EPSG:4326'`，向后兼容）：
```python
crs: str = "EPSG:4326"
"""图层 bounds 所用坐标系。默认 WGS84。导入非 WGS84 栅格时由 /import/raster/confirm 写入。"""
```
2. `meta_dict()` 返回字典追加 `"crs": self.crs`
3. **不动**现有 18+ 个 `register_overlay()` 静态调用 — 它们默认 `crs='EPSG:4326'`，与现有 PNG 导出脚本（已全部转 WGS84 bounds）一致
4. **不动** `import_router.py` 现有 `/import/raster` 端点的 `register_overlay` 调用 — 它会在 Task 6 由 `/import/raster/confirm` 替代写入正确 CRS

### Task 6：后端 4 个新端点 + `render_cog_preview_reprojected` + 集成测试

#### 6.1 新增 `raster_preview_service.render_cog_preview_reprojected`

**改写**：[raster_preview_service.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/raster_preview_service.py)

新增方法（不改动原 `render_cog_preview`）：
```python
def render_cog_preview_reprojected(
    self, *, cog_path, palette, width, height,
    source_crs: str, target_crs: str = "EPSG:4326",
    min_value=None, max_value=None,
) -> tuple[bytes, tuple[float, float, float, float]]:
    """重投影到 target_crs 后生成 PNG，返回 (png_bytes, target_bounds)。

    内部用 rasterio.warp.calculate_default_transform + reproject，
    模式参考 spatial_aligner.py:88-98 与 universal_reader.py:374。
    """
```

实现：`rasterio.warp.calculate_default_transform(src_crs, dst_crs, width, height, *bounds)` 得到 dst_transform/dst_width/dst_height，然后 `reproject` 到目标网格，最后按原着色逻辑生成 PNG，并用 `transform_bounds` 返回目标 bounds。

#### 6.2 新增 4 个端点

**改写**：[import_router.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/api/routers/import_router.py)

```python
@router.get("/crs-options", dependencies=[Depends(require_write_access)])
async def list_crs_options() -> dict:
    """返回前端下拉用 CRS 列表（按 category 分组）。委托 crs_registry.to_api_payload()。"""

@router.post("/raster/confirm", dependencies=[Depends(require_write_access)])
async def confirm_imported_raster(body: ConfirmRequest) -> dict:
    """用户确认 CRS 后：1) 重投影 PNG 2) 重算 bounds 3) 更新 OverlaySpec.crs 4) 返回新 bounds。
    body: {layer_id, source_crs, lng_offset=0.0, lat_offset=0.0}
    """

@router.post("/transform-point", dependencies=[Depends(require_write_access)])
async def transform_point_endpoint(body: TransformPointRequest) -> dict:
    """前端 CSV/POI 预览用：批量点转换。委托 crs_transformer.transform_points_batch。"""

@router.post("/transform-bounds", dependencies=[Depends(require_write_access)])
async def transform_bounds_endpoint(body: TransformBoundsRequest) -> dict:
    """前端栅格预览用：bounds 转换。委托 crs_transformer.transform_bounds。"""
```

**关键流程**（`/raster/confirm`）：
1. 从 `_IMPORTS_DIR/{layer_id}` 读原始 TIF
2. 用 `crs_detector.detect_from_raster` 二次确认（若用户覆盖了检测值，以用户值为准）
3. 调 `render_cog_preview_reprojected(source_crs=user_crs, target_crs='EPSG:4326')` 生成新 PNG + WGS84 bounds
4. 应用 `lng_offset`/`lat_offset` 到 bounds（按用户规格"偏移在 CRS 转换后应用"）
5. 覆盖 `preview.png` + `bounds.json`（保留原 TIF 不动）
6. `unregister_overlay` + `register_overlay` 重新注册（更新 `crs` 字段）
7. 返回 `{layer_id, bounds: [...], source_crs, applied_offset: [lng, lat]}`

**`/import/raster` 端点小改**：返回值新增 `source_crs`/`suggested_crs`/`needs_confirm` 字段（来自 `crs_detector`），bounds **保持源 CRS 不转换**（让前端先展示原 bounds，用户确认后再调 `/raster/confirm` 转换）。

#### 6.3 集成测试

**新建**：[tests/test_import_raster_crs.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/test_import_raster_crs.py)

测试用例（用 `tmp_path` fixture + 合成 GeoTIFF）：
- 上传 WGS84 TIF → `needs_confirm=False`，bounds 在 ±180/±90 内
- 上传 EPSG:32650 TIF → `needs_confirm=True`，`suggested_crs='EPSG:32650'`
- 调 `/raster/confirm` 用 `source_crs='EPSG:32650'` → 返回 WGS84 bounds，overlay_registry 中 `OverlaySpec.crs == 'EPSG:4326'`
- `/crs-options` 返回 9 项，含 GCJ02/BD09
- `/transform-point` 批量转 GCJ02 → WGS84，结果与 `_gcj_bd.gcj02_to_wgs84` 一致

### Task 7：前端 `services/crs/` 服务模块 + vitest

**新建目录**：`Code/frontend/src/services/crs/`

**文件清单**：
- `index.ts` — 公共导出
- `crs-registry.ts` — 镜像后端 9 个 CRS（含 `CRSCategory`/`CRSOption`/`CRS_REGISTRY`/`listCrs`/`getCrs`）
- `gcj-bd.ts` — 纯 TS GCJ-02/BD-09 算法（从后端 `_gcj_bd.py` 直译，保留 `WGS84_A = 6378245.0`）
- `crs-transformer.ts` — `transformPoint`/`transformBounds`/`transformPointsBatch`；EPSG 系走 proj4，加密系走 `gcj-bd.ts`
- `crs-detector.ts` — 客户端轻量检测（bounds 启发式，主要逻辑在后端）
- `crs-transformer.test.ts` — vitest 单测

**关键代码骨架**（`crs-transformer.ts`）：
```ts
import proj4 from 'proj4'
import { CRS_REGISTRY, getCrs, CRSDef, CRSCategory } from './crs-registry'
import { gcj02ToWgs84, bd09ToWgs84, wgs84ToGcj02, wgs84ToBd09 } from './gcj-bd'

export interface TransformOptions {
  lngOffset?: number
  latOffset?: number
}

export function transformPoint(
  lng: number, lat: number,
  sourceCode: string, targetCode: string,
  opts: TransformOptions = {},
): [number, number] {
  let result: [number, number]
  if (sourceCode === targetCode) {
    result = [lng, lat]
  } else if (getCrs(sourceCode)?.category === 'encrypted' || getCrs(targetCode)?.category === 'encrypted') {
    result = transformEncrypted(lng, lat, sourceCode, targetCode)
  } else {
    result = proj4(sourceCode, targetCode, [lng, lat])
  }
  return [result[0] + (opts.lngOffset ?? 0), result[1] + (opts.latOffset ?? 0)]
}

// transformBounds / transformPointsBatch 类似
```

**测试**（`crs-transformer.test.ts`）：
- EPSG:4326 → EPSG:3857 与 proj4 直接调用一致
- GCJ02 → WGS84 与后端 `_gcj_bd.py` 北京天安门样例一致（116.39747, 39.9088 → ~116.3912, ~39.9074）
- 偏移应用：`transformPoint(0, 0, 'EPSG:4326', 'EPSG:4326', {lngOffset: 1, latOffset: 2})` → `[1, 2]`
- source == target 无偏移：原样返回

### Task 8：前端 `RasterImportConfirmDialog.vue`

**新建**：[RasterImportConfirmDialog.vue](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/toolbar/RasterImportConfirmDialog.vue)

**功能**：
- 接收 props：`{ layerId, fileName, sourceCrs, suggestedCrs, needsConfirm, originalBounds }`
- 显示检测到的 CRS + confidence + 可编辑下拉（用户可覆盖）
- 显示偏移输入框（`lng_offset`/`lat_offset`，默认 0）
- 实时预览：调 `/import/transform-bounds` 显示转换后 WGS84 bounds
- 「确认」按钮 → 调 `/import/raster/confirm` → emit `confirm({layerId, bounds, sourceCrs, lngOffset, latOffset})`
- 「跳过」按钮 → emit `skip()`，用原 bounds 直接加入图层列表（向后兼容 WGS84 数据）

**UI 风格**：复用 `CsvImportDialog.vue` 的 dark theme 样式（panel-header / section-label / col-row / action-row）

### Task 9：前端集成

#### 9.1 `data-import.ts` 扩展

**改写**：[data-import.ts:18-21](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/services/data-import.ts#L18-L21)

```ts
export interface RasterImportResult {
  layer_id: string
  bounds?: [number, number, number, number]
  source_crs?: string         // 检测到的源 CRS
  suggested_crs?: string      // 建议用户确认的 CRS
  needs_confirm?: boolean     // true 时前端弹确认框
}
```

新增函数：
- `confirmRasterImport(layerId, sourceCrs, lngOffset, latOffset)` → 调 `/import/raster/confirm`，返回 `{layer_id, bounds, source_crs, applied_offset}`
- `fetchCrsOptions()` → 调 `/import/crs-options`
- `transformPointBatch(points, sourceCode, targetCode, opts)` → 调 `/import/transform-point`（CSV 行数 > 1000 时用后端，否则前端 proj4）
- `transformBoundsApi(bounds, sourceCode, targetCode)` → 调 `/import/transform-bounds`

#### 9.2 `useDataImportFlow.ts` 插入确认步骤

**改写**：[useDataImportFlow.ts:79-101](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/composables/useDataImportFlow.ts#L79-L101)

新增响应式状态：
- `pendingRasterConfirm = ref<PendingRasterConfirm | null>(null)`

`importRasterFile` 改动：
1. 调 `uploadRasterFile` 得到 `{layer_id, bounds, source_crs, suggested_crs, needs_confirm}`
2. 若 `needs_confirm === true`：设 `pendingRasterConfirm = {layerId, fileName, sourceCrs, suggestedCrs, originalBounds: bounds}`，**不立即**加入图层列表，等用户在弹框确认
3. 若 `needs_confirm === false`：直接 `addImportedRasterLayer`（WGS84 数据快路径）

新增函数：
- `confirmRasterCrs(sourceCrs, lngOffset, latOffset)` → 调 `confirmRasterImport` → `addImportedRasterLayer` 并传入 `sourceCrs`/`lngOffset`/`latOffset` → 清空 `pendingRasterConfirm`
- `skipRasterConfirm()` → 用原 bounds 直接 `addImportedRasterLayer` → 清空 `pendingRasterConfirm`

返回值新增：`pendingRasterConfirm, confirmRasterCrs, skipRasterConfirm`

#### 9.3 `CsvImportDialog.vue` 扩展

**改写**：[CsvImportDialog.vue:29-38](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/toolbar/CsvImportDialog.vue#L29-L38)

`CRS_OPTIONS` 改为运行时从 `/import/crs-options` 拉取（保留硬编码 fallback 以防 API 不可用），覆盖 9 个 CRS。

预览逻辑改动：
- `crs.value` 是 `EPSG:*`：继续走 proj4 客户端转换（行数 ≤ 1000）
- `crs.value` 是 `GCJ02`/`BD09`：走本地 `gcj-bd.ts` 纯 TS 算法（无需后端往返，实时预览）
- 行数 > 1000 且 `crs.value` 非 4326/3857：提示「预览仅前 5 行，确认时后端批量转换」

`handleConfirm` 改动：
- 行数 ≤ 1000：前端 proj4/gcj-bd 完成全部转换后 emit
- 行数 > 1000：emit 原始 rows + `crs`，由调用方触发后端 `/import/transform-point` 批量转换（保留前端预览的前 5 行结果）

#### 9.4 `imported-raster.ts` 加 CRS 字段

**改写**：[imported-raster.ts:4-22](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/stores/layers/imported-raster.ts#L4-L22)

```ts
export interface ImportedRasterPayload {
  overlayLayerId: string
  bounds?: [number, number, number, number]
  fileName?: string
  sourceCrs?: string    // 新增：源 CRS（默认 'EPSG:4326'）
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
): ImportedRasterPayload { /* ... */ }
```

### Task 10：前端 `overlay-image-module.ts` 防御性检查

**改写**：[overlay-image-module.ts:163-199](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/map/overlay-image-module.ts#L163-L199)

在 `_addOverlay` 中拿到 `bounds` 后、`addSource` 之前插入校验：
```ts
function _validateWgs84Bounds(bounds: [number, number, number, number]): boolean {
  const [west, south, east, north] = bounds
  if (!Number.isFinite(west) || !Number.isFinite(south) || !Number.isFinite(east) || !Number.isFinite(north)) return false
  if (west < -180 || east > 180 || south < -90 || north > 90) return false
  if (west >= east || south >= north) return false
  return true
}

// 在 _addOverlay 内：
if (!_validateWgs84Bounds(bounds)) {
  console.warn(`[Overlay] ${layerId} bounds invalid or non-WGS84, skipping:`, bounds)
  return
}
```

若 `boundsData.meta.crs` 存在且 ≠ `'EPSG:4326'`，记录警告但仍尝试加载（Phase 1 不做前端重投影，依赖后端 `/raster/confirm` 已转好）。

### Task 11：Phase 4 — 代码审查 + 项目重启

#### 11.1 代码审查（用 TRAE-code-review skill）

**审查范围**：
- 新增：`crs/` 整个包（4 + 2 个新文件）、`tests/test_crs_*.py`、`RasterImportConfirmDialog.vue`、`services/crs/`
- 改动：`coordinate_transform_service.py`（垫片）、`overlay_registry.py`（crs 字段）、`import_router.py`（4 端点）、`raster_preview_service.py`（新方法）、`data-import.ts`、`useDataImportFlow.ts`、`CsvImportDialog.vue`、`imported-raster.ts`、`overlay-image-module.ts`

**审查重点**（用户指定）：
1. **旧代码使用**：检查是否还有文件直接 import `coordinate_transform_service` 而非走新 `crs` 包（除已知的 `layer_router.py`/`tile_proxy_service.py` 垫片兼容路径）
2. **逻辑混乱**：
   - 偏移应用顺序是否一致（CRS 转换后）
   - `transform_point` 旧签名（`source`/`target` 字面量）与新签名（`source_code`/`target_code`/offsets）是否在垫片正确归一化
   - LRU 缓存 key 是否包含加密系（应不包含，加密系不缓存）
   - `always_xy=True` 是否所有 pyproj 调用都设置
   - 前端 `transformPoint` 与后端 `transform_point` 结果是否在 proj4 精度范围内一致

#### 11.2 项目重启 + E2E 冒烟

**重启步骤**：
1. 后端：`StopCommand` 现有 uvicorn 进程 → 重新启动（确保加载新 `crs` 包）
2. 前端：`StopCommand` 现有 vite dev server → 重新启动
3. 冒烟测试（手动验证清单，不写自动化）：
   - `GET /import/crs-options` 返回 9 项
   - 上传一个 WGS84 TIF → 无确认弹框，直接进图层列表
   - 上传一个 EPSG:32650 TIF → 弹确认框 → 选 EPSG:32650 → 确认 → 图层 bounds 在中国区域 (73~137, 15~59) 内
   - CSV 导入选 GCJ-02 → 预览前 5 行坐标偏移约 0.006°（北京区域）→ 确认导入
   - 旧 `/geo/transform?lng=116.391&lat=39.907&source=GCJ-02&target=EPSG:3857` 端点仍可用（垫片生效）

## 四、Assumptions & Decisions

### 关键假设
1. **pyproj 已安装**（rasterio 传递依赖）— 若 `import pyproj` 失败，Task 2 需先 `pip install pyproj` 并 pin 到 `requirements.txt`
2. **现有 18 个静态 `register_overlay` 调用的 bounds 已是 WGS84**（上一轮会话已修复 `export_overlay_assets.py`）— 默认 `crs='EPSG:4326'` 无需改动
3. **`tile_proxy_service.py`/`layer_router.py` 本轮不迁移 import** — 垫片透明兼容，Phase 3 统一迁移
4. **前端 GCJ-02/BD-09 算法与后端结果在 1e-6 精度内一致** — 同算法直译，无精度差异
5. **CSV 行数阈值 1000** — 超过时前端不批量转换，提交时走后端 `/import/transform-point`

### 关键决策
1. **`OverlaySpec.crs` 默认 `'EPSG:4326'`**：向后兼容现有 18 个静态注册
2. **`/import/raster` 仍返回源 CRS bounds**：让前端先展示原 bounds，确认后再 `/raster/confirm` 转换 — 避免上传时同步阻塞做重投影
3. **前端 proj4 + 纯 TS GCJ-02/BD-09**：用户决策「前端预览 + 后端最终转换」
4. **垫片保留 `CoordinateSystem` Literal 类型**：`tile_proxy_service.py` 用到 `template.coord_system == "GCJ-02"` 字面量比较，不能改类型定义
5. **不做双点校准 UI**：Phase 2 内容，本轮仅做 `lng_offset`/`lat_offset` 显式字段

### 范围外（明确不做）
- 全 UTM 系列（EPSG:32601-32660）、全 Gauss-Krüger 3 度带（EPSG:4513-4533）、Lambert Conformal Conic — Phase 2
- 双点校准 UI — Phase 2
- 算法输出图层的 CRS 元数据注入 — Phase 3
- 15+ 现有数据集 CRS 回归测试 — Phase 3
- `layer_router.py`/`tile_proxy_service.py` 的 import 迁移到新包 — Phase 3

## 五、Verification Steps

### 单元测试
```powershell
# 后端
cd Code\backend
python -m pytest tests/test_crs_transformer.py tests/test_crs_detector.py tests/test_import_raster_crs.py -v

# 前端
cd Code\frontend
npm test -- src/services/crs/crs-transformer.test.ts
```

### 集成验证
1. `python -c "from app.services.crs import crs_transformer; print(crs_transformer.transform_point(116.39747, 39.9088, 'GCJ02', 'EPSG:4326'))"` → 应输出 WGS84 (116.3912, 39.9074)
2. `python -c "from app.services.coordinate_transform_service import gcj02_to_wgs84; print(gcj02_to_wgs84(116.39747, 39.9088))"` → 同上 + DeprecationWarning
3. 启动后端 → `curl /import/crs-options` → 9 项
4. 前端 dev server → 上传 EPSG:32650 TIF → 弹确认框

### 类型检查
```powershell
cd Code\frontend
npm run build  # vue-tsc + vite build
```

### Phase 4 收尾
- TRAE-code-review skill 跑一遍改动文件
- 项目重启 + 手动 E2E 冒烟（按 11.2 清单）

## 六、执行顺序与依赖

```
Task 2 (transformer) ─┐
                      ├─► Task 4 (垫片) ──┐
Task 3 (detector) ────┤                    │
                      ├─► Task 6 (端点) ───┤
Task 5 (OverlaySpec) ─┘                    ├─► Task 11 (审查 + 重启)
                                            │
Task 7 (前端 crs/) ─► Task 8 (Dialog) ──────┤
                      │                     │
                      ├─► Task 9 (集成) ────┤
                      │                     │
Task 10 (防御性检查) ─────────────────────────┘
```

可并行：Task 2 + Task 3 + Task 5 + Task 7 + Task 10（互不依赖）
必须串行：Task 4 依赖 Task 2；Task 6 依赖 Task 2+3+5；Task 8 依赖 Task 7；Task 9 依赖 Task 7+