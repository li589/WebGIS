# 进度：前端可调配色 / NaN（C+Y 一期）

**日期**：2026-08-05  
**状态**：一期已落地

## 一期完成

- 后端：`raster_preview_service` 统一 palette + `nodata_mode`/`nodata_color`；`/overlay-preview`、`/overlay-tiles` 接受样式 query；`overlay-bounds` meta 含 `supports_recolor`
- 前端：图层 `paletteOverride` / `vminOverride` / `vmaxOverride` / `nodataMode` / `nodataColor` + workspace 持久化
- `isMapLinkedPalette(supportsRecolor)`；InfoPanel 解锁配色 / 值域 / NaN
- `overlay-image-module` URL 带样式并刷新；工作流 `buildWorkflowOverlayState` 使用合并后 `layer.renderHint`

## 二期（未实施）

原始浮点网格 / WebGL 上色（对齐天气瓦片路径）：新建 `/overlay-grid` 或 COG+`raster-color`，即时改色不重拉服务端 PNG。见计划 C+Y。

## 验证

```text
Env\Python312\python.exe -m pytest Test/backend/test_overlay_tile_service.py Test/backend/test_overlay_recolor.py -q
cd Code/frontend && npm run test -- layer-symbology overlay-symbology workflow-overlay-render-hint
```
