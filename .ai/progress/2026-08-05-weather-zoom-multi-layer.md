# 进度：天气缩放加载与多层加速

**日期**：2026-08-05  
**状态**：已落地（含周边组件适配）

## 完成

- 修复 `weather-viewport` maxWait 过期 snap：fire 始终读 live `currentMap*`；手势结束 `{ immediate: true }` flush
- `map-interaction-module`：`zoom` 中途同步；`move` ≥100ms 节流；`zoomend`/`moveend` immediate
- `weather-tile-manager`：同优先级图层 round-robin；可见层 ≥2 时邻域 depth=1、跳过邻小时预取
- 未提高 FE/BE 并发上限（仍 ≤4，对齐 Open-Meteo）

> **2026-08-06 更新**：并发 cap 已调至 **6**（见 `2026-08-06-weather-tile-holes-idl.md`）。

## 周边组件适配

- 时间轴：`watch(currentHour) → flushWeatherTileViewports(hour)` 仍立即生效，与视口防抖互斥（flush 会取消挂起 debounce）
- 分析/视口驱动 workflow：仍仅非天气层走 `handleViewportChange` 500ms debounce，不受天气 immediate 影响
- 工作流状态：`hasActiveWorkflows` 含天气合成态；天气合成行增加视口填充进度条（`cached/viewport`）
- 地图横幅：订阅 `activityVersion`；半填充+pending 时显示 partial 进度文案

## 验证

```text
cd Code/frontend && npm run test -- weather-viewport weather-tile-manager.fairness map-interaction-module weather-tile weather-tile-banner workflow-status
cd Code/frontend && npm run lint && npm run build
```

相关：`Code/frontend/README.md` 缩放/多层/进度指示说明已同步。
