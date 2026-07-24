/** 风场三态官方中文（禁止对用户露出 particle_flow / streamline / off） */
export const WIND_COPY = {
  particle: '粒子流',
  streamline: '流量场',
  off: '关闭',
  explainerOn: '色带对应风速网格底色；粒子流/流量场表示流向（颜色随风速提亮）。',
  explainerOff: '色带对应风速网格底色；粒子流/流量场当前已关闭。',
} as const

export function windModeUiLabel(mode: 'particle' | 'streamline' | 'off'): string {
  return WIND_COPY[mode]
}
