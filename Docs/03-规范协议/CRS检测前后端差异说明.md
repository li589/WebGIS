# CRS 检测前后端差异说明

> 日期：2026-08-15 ｜ 来源：数据源管理与工作流深度审计（Phase D3）
> 结论：**导入主链以后端为权威**；前端检测器为本地预览/兜底工具，**不强制对齐**。

## 1. 角色定位

| 端 | 实现 | 角色 |
|----|------|------|
| 后端 | `Code/backend/app/services/crs/_crs_detector.py`（+ `crs_registry.py` / `_crs_transformer.py`） | **权威**。数据导入（`import_router`）主链路使用：rasterio 元数据 → GeoJSON crs 字段 → bounds 启发式三层检测，产出 `CRSDetectionResult`（含 confidence / needs_user_confirm）驱动前端确认弹窗与重投影。 |
| 前端 | `Code/frontend/src/services/crs/crs-detector.ts`（+ `crs-registry.ts` / `crs-transformer.ts`） | **预览/兜底**。仅 bounds 启发式；截至本次审计**无生产调用方**（仅 `services/crs/index.ts` 导出与 `crs-transformer.test.ts` 引用），不参与导入判定。 |

## 2. 能力差异（bounds 启发式分支对比）

| 检测分支 | 后端 | 前端 |
|----------|------|------|
| 地理坐标系（±180/±90） | ✅ conf 0.5 | ✅ conf 0.5 |
| EASE-Grid 2.0（EPSG:6933，宽高比 2.0~2.7 对称框） | ✅ conf 0.65 | ❌ |
| Web Mercator（EPSG:3857，跨度 > 1e6 判据） | ✅ conf 0.6 | ❌ |
| 高斯-克吕格 3 度带 zone 39/40/41（X∈3.9e7~4.2e7） | ✅ conf 0.5 | ✅ conf 0.5 |
| 高斯-克吕格更广范围（zone 25-45，`suggest_gk_zone`） | ✅ conf 0.45 | ❌ |
| Lambert Europe（EPSG:3034） | ✅ conf 0.3 | ✅ conf 0.3 |
| UTM 推断 | ✅ 按 northing 粗估纬度 + 区域经度选带（conf 0.4/0.3） | ⚠️ 固定默认 UTM 50N（EPSG:32650，conf 0.3） |
| rasterio 栅格元数据检测 | ✅（最可靠，conf 0.95/0.7；CGCS2000→4490 识别；地理系 bounds 越界二次校验） | ❌ |
| GeoJSON crs 字段（RFC 7946 前格式 / urn 解析 / 别名表） | ✅ | ❌ |
| XY 轴序颠倒检测（`detect_xy_swap`） | ✅ | ❌ |

## 3. 约定

1. **不改前端**：导入判定、置信度阈值（`_CONFIRM_THRESHOLD=0.7`）与确认弹窗语义均由后端结果驱动；前端复制完整启发式只会引入双真源漂移。
2. **前端若需展示预判**：仅可作 UI 提示，最终以导入接口返回的 `CRSDetectionResult` 为准（`needs_user_confirm=true` 时必须允许用户覆盖）。
3. **演进规则**：新增检测分支（如新投影类型）只改后端 `_crs_detector.py` + `crs_registry.py`，并补 `Test/backend/test_crs_detector.py` 用例；前端不镜像实现。
4. **验证命令**（改后端 CRS 时）：`Env/Python312/python.exe -m pytest Test/backend/test_import_raster_crs.py Test/backend/test_crs_detector.py -q`（仓库根执行）。
