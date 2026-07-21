/**
 * 风粒子控制器工厂 — 在 Canvas 2D 与 WebGL 两种实现间选择。
 *
 * 选择策略（WebGL 默认主路径）：
 *   - 默认使用 WebGL（需具备 WebGL + 顶点纹理采样能力）。
 *   - `?windgl=0` 或 localStorage `windgl=0` 强制回退 Canvas（对比/排查）。
 *   - `?windgl=1` / localStorage `windgl=1` 显式确认 WebGL（兼容旧开关）。
 *   - 探测失败时回退 Canvas；WebGL controller 内部也会在运行时失败时再回退一次。
 *
 * 两种实现均满足 `WindParticleControllerContract`，可互换。
 */
import type { Map as MaplibreMap } from 'maplibre-gl'
import { WindParticleOverlayController } from './wind-particle-overlay-controller'
import { WindParticleWebGLOverlayController } from './wind-particle-webgl-controller'
import type { WindParticleControllerContract } from './wind-particle-controller-contract'
import { probeWindParticleWebGLSupport } from './wind-particle-webgl-renderer'

/**
 * 是否启用 WebGL 风粒子。
 * 默认开启；URL 参数优先于 localStorage；仅显式 `0` 关闭。
 */
export function isWebGLWindEnabled(): boolean {
  if (typeof window === 'undefined') return false
  try {
    const params = new URLSearchParams(window.location.search)
    const fromUrl = params.get('windgl')
    if (fromUrl === '0') return false
    if (fromUrl === '1') return true
    const fromStorage = window.localStorage.getItem('windgl')
    if (fromStorage === '0') return false
    if (fromStorage === '1') return true
    return true
  } catch {
    return true
  }
}

/** 浏览器是否支持基础 WebGL（不含顶点纹理探测）。 */
export function isWebGLAvailable(): boolean {
  if (typeof window === 'undefined') return false
  const doc = (window as Window & { document?: Document }).document
  if (!doc || typeof doc.createElement !== 'function') return false
  try {
    const canvas = doc.createElement('canvas')
    const gl = (canvas as HTMLCanvasElement & { getContext: (id: string) => unknown }).getContext('webgl')
      ?? (canvas as HTMLCanvasElement & { getContext: (id: string) => unknown }).getContext('experimental-webgl')
    return !!gl
  } catch {
    return false
  }
}

/**
 * 粒子 WebGL 路径是否可用：能拿到 WebGL(2) 上下文即可。
 * 绘制改为 CPU 投影后不再依赖顶点纹理采样。
 */
export function isWebGLWindUsable(): boolean {
  if (typeof window === 'undefined') return false
  const doc = (window as Window & { document?: Document }).document
  if (!doc || typeof doc.createElement !== 'function') return false
  return probeWindParticleWebGLSupport(doc).ok
}

/** 默认控制器工厂：WebGL 优先，显式关闭或能力不足时回退 Canvas。 */
export function createDefaultWindParticleController(map: MaplibreMap): WindParticleControllerContract {
  if (isWebGLWindEnabled() && isWebGLWindUsable()) {
    return new WindParticleWebGLOverlayController(map)
  }
  return new WindParticleOverlayController(map)
}
