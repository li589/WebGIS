/**
 * 风场 UI 三态（WindDisplayMode）与目录 paint_mode 是两条轴，勿混用：
 *
 * - catalog `paint_mode`（layer capabilities / renderHint）：
 *   `particle_flow` | `grid_fill` | `heatmap` | `point_symbol` | `barb` | …
 *   决定默认渲染器；其中 `barb` 仅是 paint_mode，不是 WindDisplayMode。
 *
 * - UI `windDisplayMode`：`particle` | `streamline` | `off`
 *   控制「当前风场图层」的粒子流/流量场/网格（仅色底）三态；`off` 时仍可保留 particleFlowCatalogId 归属。
 *
 * 映射：UI `particle` ↔ paint_mode `particle_flow`（内部契约，不对用户展示英文 id）。
 * 用户可见文案见 `ui-copy` / windDisplayModeLabel。
 *
 * D1 修复后：类型与纯映射函数真源已移至 src/types/wind-display.ts，
 * 本文件 re-export 并保留依赖 ui-copy 的文案函数。
 */
import { windModeUiLabel } from '../../ui-copy'
import type { WindDisplayMode } from '../../types/wind-display'

export {
  isWindDisplayMode,
  paintModeToWindDisplayMode,
  WIND_DISPLAY_MODES,
  windDisplayModeChip,
  windDisplayModeToPaintMode,
  type WeatherPaintModeChip,
  type WindDisplayMode,
} from '../../types/wind-display'

/** 用户可见中文标签（粒子流 / 流量场 / 网格） */
export function windDisplayModeLabel(mode: WindDisplayMode): string {
  return windModeUiLabel(mode)
}
