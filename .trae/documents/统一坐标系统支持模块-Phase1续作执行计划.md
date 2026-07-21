# 统一坐标系统支持模块 — Phase 1 续作执行计划

> **背景**：原计划 [统一坐标系统支持模块-Phase1续作计划.md](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/.trae/documents/统一坐标系统支持模块-Phase1续作计划.md) 已通过用户审批并开始执行。截至本计划生成时：
> - **Task 1（基础包）**：✅ 完成 — `crs_types.py` / `crs_registry.py` / `_gcj_bd.py` / `__init__.py`，9 个 CRS 已注册
> - **Task 2（transformer）**：✅ 完成 — `_crs_transformer.py` + 21 个单测全部通过
> - **Task 3（detector）**：⚠️ 实现完成，51 个测试通过，6 个因 Windows `tmp_path` 权限报错（**非代码缺陷**）
> - **Task 4–11**：⏳ 待执行
>
> 用户原始需求：构建覆盖 WGS84/ETRS89/EASE-Grid 2.0/CGCS2000/GCJ-02/BD-09 + 高斯-克吕格/UTM/Lambert/Web Mercator 的统一 CRS 模块，支持显式偏移字段，前端预览 + 后端收口，上传时检测 + 用户确认。用户额外指令：「做整个修改完后进行一次代码审查，着重于旧代码使用和逻辑混乱问题，然后重启整个项目」。
>
> 本计划接续执行剩余任务，不重新决策已锁定项。

## 一、当前状态确认

### 1.1 已完成产物（本轮不动）

| 文件 | 状态 |
|---|---|
| [Code/backend/app/services/crs/crs_types.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/crs_types.py) | ✅ `CRSCategory` 枚举 + `CRSDef` frozen dataclass + `CoordinatePoint` |
| [Code/backend/app/services/crs/crs_registry.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/crs_registry.py) | ✅ 9 个 CRS（3 地理 + 2 加密 + 4 投影）+ `get_crs`/`list_crs`/`to_api_payload` |
| [Code/backend/app/services/crs/_gcj_bd.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/_gcj_bd.py) | ✅ 纯 Python GCJ-02/BD-09，`_WGS84_A = 6378245.0` |
| [Code/backend/app/services/crs/__init__.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/__init__.py) | ✅ PEP 562 延迟导入，`_` 前缀避免子模块/属性名冲突 |
| [Code/backend/app/services/crs/_crs_transformer.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/_crs_transformer.py) | ✅ `CRSTransformer` + LRU 缓存 + 加密系路由 + 偏移后置 |
| [Code/backend/app/services/crs/_crs_detector.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/crs/_crs_detector.py) | ✅ `CRSDetector` + raster/geojson/bounds 三路检测 |
| [Code/backend/tests/test_crs_transformer.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/test_crs_transformer.py) | ✅ 21 测试全通过 |
| [Code/backend/tests/test_crs_detector.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/test_crs_detector.py) | ⚠️ 51 通过 + 6 个 Windows tmp_path 权限错误 |

### 1.2 Task 3 测试报错根因

```
ERROR tests/test_crs_detector.py::TestDetectFromRaster::test_wgs84_geotiff
  - PermissionError: [WinError 5] 拒绝访问。: 'C:\Users\likr\AppData\Local\Temp\pytest-of-likr'
```

**根因**：pytest `tmp_path` fixture 默认基于 `C:\Users\likr\AppData\Local\Temp\pytest-of-likr`，该目录在 Windows 下存在 ACL 限制。**不是代码缺陷**，是环境配置问题。

**修复方案**（Task 3-fix）：在 [conftest.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/conftest.py) 中加 `tmp_path_factory` fixture，把 basetemp 重定向到项目内可写目录 `Code/backend/.pytest_tmp`。

### 1.3 集成点扫描结果

执行 `grep -l "coordinate_transform_service\|transform_point" Code/backend/app -r` 确认旧模块调用方仅：
- [layer_router.py:6](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/api/routers/layer_router.py#L6) — `from app.services.coordinate_transform_service import transform_point`
- [tile_proxy_service.py:25-31](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/tile_proxy_service.py#L25-L31) — 5 个加密函数 + `CoordinatePoint` 类型

前端 `Code/frontend/src/services/` 下**无 `crs/` 子目录** — Task 7 全新创建。

`requirements.txt` 中**无 pyproj 显式声明** — 仅靠 rasterio 传递依赖，本轮 Task 4 补上 pin。

## 二、Proposed Changes（按 Task 顺序，本轮执行）

### Task 3-fix：修复 Windows tmp_path 权限报错

**改写**：[Code/backend/tests/conftest.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/conftest.py)

**改动**：在现有 `sys.path` 补齐逻辑后追加 `tmp_path_factory` fixture，重定向 basetemp：

```python
import pytest

@pytest.fixture(scope="session")
def tmp_path_factory(tmp_path_factory):
    """重定向 pytest 临时目录到项目内，规避 Windows ACL 限制。"""
    return tmp_path_factory  # 占位，实际通过 basetemp 命令行/ini 控制
```

实际采用更稳的方案：在 `conftest.py` 顶部加 `os.environ` 设置 + 创建 [pytest.ini](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/pytest.ini) 指定 `tmp_path_factory.basetemp`：

**新建**：`Code/backend/pytest.ini`
```ini
[pytest]
tmp_path_basetemp = .pytest_tmp
```

若无 `tmp_path_basetemp` ini 选项支持（旧 pytest），改用 `conftest.py` 内 `pytest_configure` 钩子 + `os.environ["PYTEST_DEBUG_TEMPROOT"]` 或直接在 fixture 内用 `Path(__file__).parent.parent / ".pytest_tmp" / "tmp"`。

**最终选定方案**（最稳）：在 [conftest.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/conftest.py) 加：

```python
import os
from pathlib import Path

# 重定向 pytest tmp_path 到项目内可写目录，规避 Windows ACL 限制
_PROJECT_TMP = Path(__file__).resolve().parent.parent / ".pytest_tmp"
_PROJECT_TMP.mkdir(parents=True, exist_ok=True)
os.environ["PYTEST_DEBUG_TEMPROOT"] = str(_PROJECT_TMP)
```

并新增 `.gitignore` 条目 `.pytest_tmp/`。

**验证**：`python -m pytest tests/test_crs_detector.py -v` 应 57 全通过。

### Task 4：转换 `coordinate_transform_service.py` 为 deprecated 垫片

**改写**：[Code/backend/app/services/coordinate_transform_service.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/coordinate_transform_service.py)

**策略**：保留所有旧函数签名 + 类型 + Literal，全部委托新 `crs` 包，加 `DeprecationWarning`。

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
CoordinatePoint = _NewPoint  # 二进制兼容（同字段 lng/lat）

_DEPRECATION_MSG = "coordinate_transform_service is deprecated; use app.services.crs"

def gcj02_to_wgs84(lng, lat):
    warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
    return _gcj02_to_wgs84(lng, lat)

def wgs84_to_gcj02(lng, lat):
    warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
    return _wgs84_to_gcj02(lng, lat)

def bd09_to_gcj02(lng, lat):
    warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
    return _bd09_to_gcj02(lng, lat)

def bd09_to_wgs84(lng, lat):
    warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
    return _bd09_to_wgs84(lng, lat)

def wgs84_to_bd09(lng, lat):
    warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
    return _wgs84_to_bd09(lng, lat)

def wgs84_to_epsg3857(lng, lat):
    warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
    from app.services.crs import crs_transformer
    return crs_transformer.transform_point(lng, lat, 'EPSG:4326', 'EPSG:3857')

def transform_point(lng, lat, source, target='EPSG:3857'):
    """旧签名兼容：source/target 用 'GCJ-02'/'BD-09'/'EPSG:3857' 字面量。"""
    warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
    from app.services.crs import crs_transformer
    # 旧字面量 'GCJ-02'/'BD-09' → 新 code 'GCJ02'/'BD09'
    src = 'GCJ02' if source == 'GCJ-02' else source
    tgt = 'BD09' if target == 'BD-09' else target
    return crs_transformer.transform_point(lng, lat, src, tgt)
```

**注意**：
- `tile_proxy_service.py` 的 5 个加密函数 + `CoordinatePoint` 类型 re-export，**零代码改动**即可兼容
- `layer_router.py:6` 的 `transform_point` 透明委托，旧字面量归一化在垫片内完成
- **不删除** `tile_proxy_service.py`/`layer_router.py` 的 import 语句（Phase 3 再统一迁移）

**新增 pin**：[Code/backend/requirements.txt](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/requirements.txt) 追加 `pyproj>=3.6,<4`（当前 3.7.2）。

**验证**：
```powershell
python -c "from app.services.coordinate_transform_service import gcj02_to_wgs84; print(gcj02_to_wgs84(116.39747, 39.9088))"
# 应输出 WGS84 + DeprecationWarning
python -m pytest tests/test_crs_transformer.py -v  # 旧测试中 test_wgs84_to_epsg3857_matches_legacy 应仍通过
```

### Task 5：`OverlaySpec.crs` 字段 + `meta_dict` 更新

**改写**：[Code/backend/app/services/overlay_registry.py:33-135](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/overlay_registry.py#L33-L135)

**改动点**：
1. `OverlaySpec` dataclass 新增字段（在 `opacity` 后、`source_path` 前）：
```python
crs: str = "EPSG:4326"
"""图层 bounds 所用坐标系。默认 WGS84。导入非 WGS84 栅格时由 /import/raster/confirm 写入。"""
```
2. `meta_dict()` 返回字典追加：
```python
"crs": self.crs,
```
3. **不动**现有 18+ 个 `register_overlay()` 静态调用 — 它们默认 `crs='EPSG:4326'`，与现有 PNG 导出脚本一致
4. **不动** `import_router.py` 现有 `/import/raster` 端点的 `register_overlay` 调用 — Task 6 由 `/import/raster/confirm` 替代写入正确 CRS

**验证**：
```powershell
python -c "from app.services.overlay_registry import OverlaySpec; spec = OverlaySpec(layer_id='x', overlay_dir='.'); print(spec.crs, spec.meta_dict().get('crs'))"
# 应输出: EPSG:4326 EPSG:4326
```

### Task 6：后端 4 个新端点 + `render_cog_preview_reprojected` + 集成测试

#### 6.1 新增 `raster_preview_service.render_cog_preview_reprojected`

**改写**：[Code/backend/app/services/raster_preview_service.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/raster_preview_service.py)

新增方法（不改动原 `render_cog_preview`）：

```python
def render_cog_preview_reprojected(
    self,
    *,
    cog_path: str | Path,
    palette: str,
    width: int,
    height: int,
    source_crs: str,
    target_crs: str = "EPSG:4326",
    min_value: float | None = None,
    max_value: float | None = None,
) -> tuple[bytes, tuple[float, float, float, float]]:
    """重投影到 target_crs 后生成 PNG，返回 (png_bytes, target_bounds)。

    内部用 rasterio.warp.calculate_default_transform + reproject，
    模式参考 spatial_aligner.py:88-98 与 universal_reader.py:374。
    """
    # 1. calculate_default_transform(src_crs, dst_crs, w, h, west, south, east, north)
    #    得到 dst_transform / dst_width / dst_height
    # 2. reproject(source=src_band, destination=dst_array, src_transform, src_crs,
    #              dst_transform, dst_crs, resampling=bilinear, src_nodata, dst_nodata)
    # 3. 按 render_cog_preview 的着色逻辑生成 PNG
    # 4. transform_bounds(src_crs, dst_crs, *src_bounds, densify_pts=21) 得 target_bounds
    # 5. 返回 (png_bytes, target_bounds)
```

#### 6.2 新增 4 个端点

**改写**：[Code/backend/app/api/routers/import_router.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/api/routers/import_router.py)

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

**Pydantic 请求模型**（同文件内）：
```python
from pydantic import BaseModel

class ConfirmRequest(BaseModel):
    layer_id: str
    source_crs: str
    lng_offset: float = 0.0
    lat_offset: float = 0.0

class TransformPointRequest(BaseModel):
    points: list[tuple[float, float]]
    source_crs: str
    target_crs: str = "EPSG:4326"
    lng_offset: float = 0.0
    lat_offset: float = 0.0

class TransformBoundsRequest(BaseModel):
    bounds: list[float]  # [west, south, east, north]
    source_crs: str
    target_crs: str = "EPSG:4326"
```

**`/raster/confirm` 关键流程**：
1. 从 `_IMPORTS_DIR/{layer_id}/` 读原始 TIF（保留 `source_filename` 在 bounds.json meta）
2. 用 `crs_detector.detect_from_raster` 二次确认（若用户覆盖了检测值，以用户值为准）
3. 调 `render_cog_preview_reprojected(source_crs=user_crs, target_crs='EPSG:4326')` 生成新 PNG + WGS84 bounds
4. 应用 `lng_offset`/`lat_offset` 到 bounds（按用户规格"偏移在 CRS 转换后应用"）
5. 覆盖 `preview.png` + `bounds.json`（保留原 TIF 不动）
6. `unregister_overlay(layer_id)` + `register_overlay(OverlaySpec(..., crs='EPSG:4326'))` 重新注册
7. 返回 `{layer_id, bounds: [...], source_crs, applied_offset: [lng, lat]}`

**`/import/raster` 端点小改**：返回值新增 `source_crs`/`suggested_crs`/`needs_confirm` 字段（来自 `crs_detector.detect_from_raster`），bounds **保持源 CRS 不转换**（让前端先展示原 bounds，用户确认后再调 `/raster/confirm` 转换）。

#### 6.3 集成测试

**新建**：[Code/backend/tests/test_import_raster_crs.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/tests/test_import_raster_crs.py)

测试用例（用项目内 `tmp_path` fixture + 合成 GeoTIFF）：
- `GET /import/crs-options` 返回 9 项，含 GCJ02/BD09
- `POST /import/transform-point` 批量转 GCJ02 → WGS84，结果与 `_gcj_bd.gcj02_to_wgs84` 一致
- `POST /import/transform-bounds` 转换 UTM 50N bounds 到 WGS84，结果在中国区域 (73~137, 15~59)
- `POST /import/raster/confirm` 用 `source_crs='EPSG:32650'`：覆盖 preview.png + bounds.json，`OverlaySpec.crs == 'EPSG:4326'`，返回 bounds 在中国区域
- `POST /import/raster` 上传 WGS84 TIF → `needs_confirm=False`，bounds 在 ±180/±90 内
- `POST /import/raster` 上传 EPSG:32650 TIF → `needs_confirm=True`，`suggested_crs='EPSG:32650'`

### Task 7：前端 `services/crs/` 服务模块 + vitest

**新建目录**：`Code/frontend/src/services/crs/`

**文件清单**：
- `index.ts` — 公共导出（`CRS_REGISTRY`/`getCrs`/`listCrs`/`transformPoint`/`transformBounds`/`transformPointsBatch`/`detectFromBounds`）
- `crs-registry.ts` — 镜像后端 9 个 CRS（`CRSCategory` 联合类型 + `CRSOption`/`CRSDef`/`CRS_REGISTRY`/`listCrs`/`getCrs`）
- `gcj-bd.ts` — 纯 TS GCJ-02/BD-09 算法（从后端 `_gcj_bd.py` 直译，保留 `WGS84_A = 6378245.0`）
- `crs-transformer.ts` — `transformPoint`/`transformBounds`/`transformPointsBatch`；EPSG 系走 proj4，加密系走 `gcj-bd.ts`
- `crs-detector.ts` — 客户端轻量检测（仅 bounds 启发式，raster 检测交给后端）
- `crs-transformer.test.ts` — vitest 单测

**关键代码骨架**（`crs-transformer.ts`）：
```ts
import proj4 from 'proj4'
import { getCrs } from './crs-registry'
import { gcj02ToWgs84, bd09ToWgs84, wgs84ToGcj02, wgs84ToBd09, gcj02ToBd09, bd09ToGcj02 } from './gcj-bd'

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
  } else if (isEncrypted(sourceCode) || isEncrypted(targetCode)) {
    result = transformEncrypted(lng, lat, sourceCode, targetCode)
  } else {
    result = proj4(sourceCode, targetCode, [lng, lat])
  }
  return [result[0] + (opts.lngOffset ?? 0), result[1] + (opts.latOffset ?? 0)]
}

function isEncrypted(code: string): boolean {
  return code === 'GCJ02' || code === 'BD09'
}

function transformEncrypted(lng: number, lat: number, src: string, tgt: string): [number, number] {
  // 直连路径 + 通用路径（与后端 _transform_encrypted 一致）
  // ...
}

// transformBounds / transformPointsBatch 类似（proj4 + 加密系四角点）
```

**测试**（`crs-transformer.test.ts`）：
- EPSG:4326 → EPSG:3857 与 proj4 直接调用一致
- GCJ02 → WGS84 与后端 `_gcj_bd.py` 北京天安门样例一致（116.39747, 39.9088 → ~116.3912, ~39.9074，1e-6 精度）
- BD09 → WGS84 同上
- 偏移应用：`transformPoint(0, 0, 'EPSG:4326', 'EPSG:4326', {lngOffset: 1, latOffset: 2})` → `[1, 2]`
- source == target 无偏移：原样返回

### Task 8：前端 `RasterImportConfirmDialog.vue`

**新建**：[Code/frontend/src/components/toolbar/RasterImportConfirmDialog.vue](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/toolbar/RasterImportConfirmDialog.vue)

**功能**：
- props：`{ layerId, fileName, sourceCrs, suggestedCrs, needsConfirm, originalBounds }`
- 显示检测到的 CRS + 可编辑下拉（用户可覆盖）
- 显示偏移输入框（`lng_offset`/`lat_offset`，默认 0）
- 实时预览：调 `/import/transform-bounds` 显示转换后 WGS84 bounds
- 「确认」按钮 → 调 `/import/raster/confirm` → emit `confirm({layerId, bounds, sourceCrs, lngOffset, latOffset})`
- 「跳过」按钮 → emit `skip()`，用原 bounds 直接加入图层列表（向后兼容 WGS84 数据）

**UI 风格**：复用 `CsvImportDialog.vue` 的 dark theme 样式（panel-header / section-label / col-row / action-row）

### Task 9：前端集成

#### 9.1 `data-import.ts` 扩展

**改写**：[Code/frontend/src/services/data-import.ts](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/services/data-import.ts)

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
- `transformPointBatch(points, sourceCode, targetCode, opts)` → 调 `/import/transform-point`（CSV 行数 > 1000 时用后端）
- `transformBoundsApi(bounds, sourceCode, targetCode)` → 调 `/import/transform-bounds`

#### 9.2 `useDataImportFlow.ts` 插入确认步骤

**改写**：[Code/frontend/src/composables/useDataImportFlow.ts](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/composables/useDataImportFlow.ts)

新增响应式状态：
- `pendingRasterConfirm = ref<PendingRasterConfirm | null>(null)`

`importRasterFile` 改动：
1. 调 `uploadRasterFile` 得到 `{layer_id, bounds, source_crs, suggested_crs, needs_confirm}`
2. 若 `needs_confirm === true`：设 `pendingRasterConfirm = {layerId, fileName, sourceCrs, suggestedCrs, originalBounds: bounds}`，**不立即**加入图层列表，等用户在弹框确认
3. 若 `needs_confirm === false`：直接 `addImportedRasterLayer`（WGS84 数据快路径）

新增函数：
- `confirmRasterCrs(sourceCrs, lngOffset, latOffset)` → 调 `confirmRasterImport` → `addImportedRasterLayer` 传 `sourceCrs`/`lngOffset`/`latOffset` → 清空 `pendingRasterConfirm`
- `skipRasterConfirm()` → 用原 bounds 直接 `addImportedRasterLayer` → 清空 `pendingRasterConfirm`

返回值新增：`pendingRasterConfirm, confirmRasterCrs, skipRasterConfirm`

#### 9.3 `CsvImportDialog.vue` 扩展

**改写**：[Code/frontend/src/components/toolbar/CsvImportDialog.vue](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/toolbar/CsvImportDialog.vue)

`CRS_OPTIONS` 改为运行时从 `/import/crs-options` 拉取（保留硬编码 fallback），覆盖 9 个 CRS。

预览逻辑改动：
- `crs.value` 是 `EPSG:*`：继续走 proj4 客户端转换（行数 ≤ 1000）
- `crs.value` 是 `GCJ02`/`BD09`：走本地 `gcj-bd.ts` 纯 TS 算法（无需后端往返，实时预览）
- 行数 > 1000 且 `crs.value` 非 4326/3857：提示「预览仅前 5 行，确认时后端批量转换」

`handleConfirm` 改动：
- 行数 ≤ 1000：前端 proj4/gcj-bd 完成全部转换后 emit
- 行数 > 1000：emit 原始 rows + `crs`，由调用方触发后端 `/import/transform-point` 批量转换

#### 9.4 `imported-raster.ts` 加 CRS 字段

**改写**：[Code/frontend/src/stores/layers/imported-raster.ts](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/stores/layers/imported-raster.ts)

```ts
export interface ImportedRasterPayload {
  overlayLayerId: string
  bounds?: [number, number, number, number]
  fileName?: string
  sourceCrs?: string    // 新增：源 CRS（默认 'EPSG:4326'）
  lngOffset?: number    // 新增：经度偏移（度）
  latOffset?: number    // 新增：纬度偏移（度）
}
```

`buildImportedRasterPayload` 同步扩展。

### Task 10：前端 `overlay-image-module.ts` 防御性检查

**改写**：[Code/frontend/src/components/map/overlay-image-module.ts](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/map/overlay-image-module.ts)（`_addOverlay` 函数内）

在 `_addOverlay` 拿到 `bounds` 后、`addSource` 之前插入校验：

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

### Task 11：Phase 4 — 代码审查 + 项目重启 + E2E 冒烟

#### 11.1 代码审查（用 `TRAE-code-review` skill）

**审查范围**：
- 新增：`crs/` 整个包（6 文件）、`tests/test_crs_*.py`（3 文件）、`RasterImportConfirmDialog.vue`、`services/crs/`（5 文件）
- 改动：`coordinate_transform_service.py`（垫片）、`overlay_registry.py`（crs 字段）、`import_router.py`（4 端点）、`raster_preview_service.py`（新方法）、`data-import.ts`、`useDataImportFlow.ts`、`CsvImportDialog.vue`、`imported-raster.ts`、`overlay-image-module.ts`、`conftest.py`、`requirements.txt`

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
1. 后端：`StopCommand` 现有 uvicorn 进程 → 重新启动（确保加载新 `crs` 包与垫片）
2. 前端：`StopCommand` 现有 vite dev server → 重新启动

**冒烟测试**（手动验证清单）：
- `GET /import/crs-options` 返回 9 项
- 上传一个 WGS84 TIF → 无确认弹框，直接进图层列表
- 上传一个 EPSG:32650 TIF → 弹确认框 → 选 EPSG:32650 → 确认 → 图层 bounds 在中国区域 (73~137, 15~59) 内
- CSV 导入选 GCJ-02 → 预览前 5 行坐标偏移约 0.006°（北京区域）→ 确认导入
- 旧 `/geo/transform?lng=116.391&lat=39.907&source=GCJ-02&target=EPSG:3857` 端点仍可用（垫片生效）

## 三、Assumptions & Decisions（沿用原计划）

### 关键假设
1. **pyproj 已安装**（rasterio 传递依赖，3.7.2）— Task 4 在 requirements.txt 显式 pin
2. **现有 18 个静态 `register_overlay` 调用的 bounds 已是 WGS84**（上一轮会话已修复 `export_overlay_assets.py`）— 默认 `crs='EPSG:4326'` 无需改动
3. **`tile_proxy_service.py`/`layer_router.py` 本轮不迁移 import** — 垫片透明兼容，Phase 3 统一迁移
4. **前端 GCJ-02/BD-09 算法与后端结果在 1e-6 精度内一致** — 同算法直译，无精度差异
5. **CSV 行数阈值 1000** — 超过时前端不批量转换，提交时走后端 `/import/transform-point`

### 关键决策
1. **`OverlaySpec.crs` 默认 `'EPSG:4326'`**：向后兼容现有 18 个静态注册
2. **`/import/raster` 仍返回源 CRS bounds**：让前端先展示原 bounds，确认后再 `/raster/confirm` 转换 — 避免上传时同步阻塞做重投影
3. **前端 proj4 + 纯 TS GCJ-02/BD-09**：用户决策「前端预览 + 后端最终转换」
4. **垫片保留 `CoordinateSystem` Literal 类型**：`tile_proxy_service.py` 用到 `"GCJ-02"` 字面量比较，不能改类型定义
5. **不做双点校准 UI**：Phase 2 内容，本轮仅做 `lng_offset`/`lat_offset` 显式字段

### 范围外（明确不做）
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
# 期望: 全部通过（Task 3-fix 后 test_crs_detector.py 57 全通过）

# 前端
cd Code\frontend
npm test -- src/services/crs/crs-transformer.test.ts
```

### 集成验证
```powershell
# 1. transformer 单点验证
python -c "from app.services.crs import crs_transformer; print(crs_transformer.transform_point(116.39747, 39.9088, 'GCJ02', 'EPSG:4326'))"
# 应输出 WGS84 (116.3912, 39.9074)

# 2. 垫片验证（应同时输出结果 + DeprecationWarning）
python -c "from app.services.coordinate_transform_service import gcj02_to_wgs84; print(gcj02_to_wgs84(116.39747, 39.9088))"

# 3. 启动后端 → curl /import/crs-options → 9 项
# 4. 前端 dev server → 上传 EPSG:32650 TIF → 弹确认框
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
Task 3-fix (修 tmp_path) ──┐
                           ▼
Task 4 (垫片) ─────────────┐
                           │
Task 5 (OverlaySpec.crs) ──┤
                           ├─► Task 6 (4 端点 + reproject + 集成测试) ──┐
                           │                                              │
                           │                                              │
Task 7 (前端 crs/) ────────┼─► Task 8 (Dialog) ─► Task 9 (集成) ─────────┤
                           │                                              │
                           │                                              │
Task 10 (防御性检查) ───────────────────────────────────────────────────┤
                                                                        ▼
                                                          Task 11 (审查 + 重启)
```

可并行：Task 4 + Task 5 + Task 7 + Task 10（互不依赖）
必须串行：Task 6 依赖 Task 4+5；Task 8 依赖 Task 7；Task 9 依赖 Task 7+8；Task 11 依赖全部

## 六、本轮执行 Todo 清单

1. ✅ Task 3-fix：修复 `conftest.py` + 新增 `.pytest_tmp/` gitignore → `test_crs_detector.py` 57 全通过
2. ✅ Task 4：`coordinate_transform_service.py` 转 deprecated 垫片 + `requirements.txt` pin pyproj
3. ✅ Task 5：`OverlaySpec.crs` 字段 + `meta_dict` 返回 `crs`
4. ✅ Task 6.1：`raster_preview_service.render_cog_preview_reprojected` 方法
5. ✅ Task 6.2：`import_router.py` 4 个新端点 + `ConfirmRequest`/`TransformPointRequest`/`TransformBoundsRequest` Pydantic 模型 + `/import/raster` 返回值扩展
6. ✅ Task 6.3：`tests/test_import_raster_crs.py` 集成测试
7. ✅ Task 7：前端 `services/crs/` 5 个文件 + vitest
8. ✅ Task 8：`RasterImportConfirmDialog.vue`
9. ✅ Task 9.1：`data-import.ts` 扩展（`RasterImportResult` + 4 个新函数）
10. ✅ Task 9.2：`useDataImportFlow.ts` 插入确认步骤
11. ✅ Task 9.3：`CsvImportDialog.vue` CRS_OPTIONS 拉取 + GCJ/BD 走本地算法
12. ✅ Task 9.4：`imported-raster.ts` 加 `sourceCrs`/`lngOffset`/`latOffset` 字段
13. ✅ Task 10：`overlay-image-module.ts` 防御性 bounds 校验
14. ✅ Task 11.1：`TRAE-code-review` skill 跑改动文件
15. ✅ Task 11.2：项目重启 + E2E 冒烟（按 11.2 清单手动验证）
