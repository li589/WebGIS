/** 风场可视化三态：粒子流 / 动画流线 / 关闭 */

export type WindDisplayMode = 'particle' | 'streamline' | 'off'

export const WIND_DISPLAY_MODES: WindDisplayMode[] = ['particle', 'streamline', 'off']

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

/** 样式 chip / paint_mode 展示用 */
export function windDisplayModeChip(mode: WindDisplayMode): string {
  switch (mode) {
    case 'particle':
      return 'particle_flow'
    case 'streamline':
      return 'streamline'
    case 'off':
      return 'off'
  }
}
