/**
 * Explicit wind vs scalar WebGL compositing policy.
 *
 * 规则（已更新）：
 * - smoothRendering 开启（默认）：标量场 WebGL 与风场粒子/流线可共存，
 *   WebGL 不让步，两者同时渲染叠加。
 * - smoothRendering 关闭：回退原始互斥策略——风场粒子/流线活跃时，
 *   标量场 WebGL 让步，回退 MapLibre fill。
 */
import type { WindDisplayMode } from './wind-display-mode'

export interface WindScalarCompositingInput {
  enabledParticleFlowCatalogId: string | null
  windDisplayMode: WindDisplayMode
  /** 用户显式开启平滑渲染时，WebGL 标量场不让步于风粒子 */
  smoothRendering?: boolean
}

/** True when wind animation should suppress scalar-field WebGL. */
export function shouldYieldScalarWebGLToWind(input: WindScalarCompositingInput): boolean {
  // 用户显式开启平滑渲染时，WebGL 不让步（即使风粒子活跃）
  if (input.smoothRendering) return false
  return Boolean(input.enabledParticleFlowCatalogId) && input.windDisplayMode !== 'off'
}
