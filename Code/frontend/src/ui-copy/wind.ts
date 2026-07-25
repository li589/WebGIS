/** 风场三态官方中文（禁止对用户露出 particle_flow / streamline / off） */
export const WIND_COPY = {
  particle: '粒子流',
  streamline: '流量场',
  /** 仅风速色底（网格/连续面），不画粒子与流量场 */
  off: '网格',
  explainerOn: '色带对应风速底色；粒子流/流量场表示流向（颜色随风速提亮）。',
  explainerOff: '色带对应风速数值面（网格色块或平滑连续面）；未叠加粒子流/流量场。',
} as const

export function windModeUiLabel(mode: 'particle' | 'streamline' | 'off'): string {
  return WIND_COPY[mode]
}
