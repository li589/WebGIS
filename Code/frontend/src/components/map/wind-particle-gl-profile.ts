/**
 * 风粒子 WebGL 密度档位：核显 / 显式 lite 时降低 PARTICLE_RESOLUTION。
 */

export const PARTICLE_RESOLUTION_FULL = 72
/** ~2304 点，显著降低 readPixels 带宽 */
export const PARTICLE_RESOLUTION_LITE = 48

export function isWindGlLiteRequested(): boolean {
  if (typeof window === 'undefined') return false
  try {
    if (new URLSearchParams(window.location.search).get('windgl') === 'lite') return true
    if (window.localStorage?.getItem('cgda.windgl') === 'lite') return true
  } catch {
    /* ignore */
  }
  return false
}

/** 探测是否更可能跑在 Intel / 非高性能 GPU（Chrome 核显常见）。 */
export function detectLikelyIntegratedGpu(): boolean {
  if (typeof document === 'undefined') return false
  try {
    const canvas = document.createElement('canvas')
    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl')
    if (!gl || !(gl instanceof WebGLRenderingContext)) return false
    const ext = gl.getExtension('WEBGL_debug_renderer_info')
    const renderer = ext
      ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || '')
      : String(gl.getParameter(gl.RENDERER) || '')
    const lowered = renderer.toLowerCase()
    if (!lowered) return false
    if (lowered.includes('intel')) return true
    if (lowered.includes('uhd') || lowered.includes('iris')) return true
    // ANGLE 上报常含 SwiftShader / Microsoft Basic — 当 lite 处理
    if (lowered.includes('swiftshader') || lowered.includes('microsoft basic')) return true
    return false
  } catch {
    return false
  }
}

export function resolveParticleResolution(): number {
  if (isWindGlLiteRequested() || detectLikelyIntegratedGpu()) {
    return PARTICLE_RESOLUTION_LITE
  }
  return PARTICLE_RESOLUTION_FULL
}
