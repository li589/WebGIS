/**
 * 风场 UI 三态（WindDisplayMode）与目录 paint_mode 是两条轴，勿混用：
 *
 * - catalog `paint_mode`（layer capabilities / renderHint）：
 *   `particle_flow` | `grid_fill` | `heatmap` | `point_symbol` | `barb` | …
 *   决定默认渲染器；其中 `barb` 仅是 paint_mode，不是 WindDisplayMode。
 *
 * - UI `windDisplayMode`：`particle` | `streamline` | `off`
 *   控制「当前风场图层」的粒子/流线/关闭三态；`off` 时仍可保留 particleFlowCatalogId 归属。
 *
 * 映射：UI `particle` ↔ chip/paint 展示名 `particle_flow`（见 windDisplayModeChip）。
 */

export type WindDisplayMode = 'particle' | 'streamline' | 'off'

export const WIND_DISPLAY_MODES: WindDisplayMode[] = ['particle', 'streamline', 'off']

/** Catalog paint_mode 字符串（与 WindDisplayMode 不同命名空间） */
export type WeatherPaintModeChip =
  'particle_flow' | 'streamline' | 'off' | 'barb' | 'grid_fill' | 'heatmap' | 'point_symbol'

export function isWindDisplayMode(value: unknown): value is WindDisplayMode {
  return value === 'particle' || value === 'streamline' || value === 'off'
}

export function windDisplayModeLabel(mode: WindDisplayMode): string {
  switch (mode) {
    case 'particle':
      return '粒子流'
    case 'streamline':
      return '流量场'
    case 'off':
      return '关闭'
  }
}

/**
 * 样式 chip / 与 paint_mode 对齐的展示标签。
 * 注意：返回值可能是 `particle_flow`（paint_mode 词汇），不是 WindDisplayMode。
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
