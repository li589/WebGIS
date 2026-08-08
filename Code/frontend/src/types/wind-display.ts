/**
 * 风场显示模式（WindDisplayMode）共享类型与纯映射函数。
 *
 * 从 components/map/wind-display-mode.ts 提取（D1 依赖倒置修复）：
 * - catalog `paint_mode`（layer capabilities / renderHint）：
 *   `particle_flow` | `grid_fill` | `heatmap` | `point_symbol` | `barb` | …
 *   决定默认渲染器；其中 `barb` 仅是 paint_mode，不是 WindDisplayMode。
 * - UI `windDisplayMode`：`particle` | `streamline` | `off`
 *   控制「当前风场图层」的粒子流/流量场/网格（仅色底）三态。
 * 映射：UI `particle` ↔ paint_mode `particle_flow`（内部契约，不对用户展示英文 id）。
 *
 * 用户可见文案 windDisplayModeLabel 依赖 ui-copy，保留在 components 层。
 */

export type WindDisplayMode = 'particle' | 'streamline' | 'off'

export const WIND_DISPLAY_MODES: WindDisplayMode[] = ['particle', 'streamline', 'off']

/** Catalog paint_mode 字符串（与 WindDisplayMode 不同命名空间） */
export type WeatherPaintModeChip =
  'particle_flow' | 'streamline' | 'off' | 'barb' | 'grid_fill' | 'heatmap' | 'point_symbol'

export function isWindDisplayMode(value: unknown): value is WindDisplayMode {
  return value === 'particle' || value === 'streamline' || value === 'off'
}

/**
 * 与 paint_mode 对齐的内部 chip id（勿直接展示给用户；UI 用 windDisplayModeLabel）。
 */
export function windDisplayModeChip(mode: WindDisplayMode): WeatherPaintModeChip {
  switch (mode) {
    case 'particle':
      return 'particle_flow'
    case 'streamline':
      return 'streamline'
    case 'off':
      return 'off'
  }
}

/** UI particle ↔ catalog paint_mode particle_flow */
export function windDisplayModeToPaintMode(
  mode: WindDisplayMode,
): 'particle_flow' | 'streamline' | 'off' {
  return windDisplayModeChip(mode) as 'particle_flow' | 'streamline' | 'off'
}

export function paintModeToWindDisplayMode(
  paintMode: string | null | undefined,
): WindDisplayMode | null {
  if (paintMode === 'particle_flow') return 'particle'
  if (paintMode === 'streamline') return 'streamline'
  if (paintMode === 'off') return 'off'
  // barb / grid_fill / … 不属于 WindDisplayMode
  return null
}
