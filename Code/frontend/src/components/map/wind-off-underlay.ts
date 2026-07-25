/**
 * 风场「网格」(off) 模式下色底策略：平滑开=WebGL 连续面，平滑关=MapLibre 网格色块。
 */
export function shouldUseSmoothWindOffUnderlay(
  smoothRendering: boolean,
  hasSmoothSync: boolean,
): boolean {
  return Boolean(smoothRendering && hasSmoothSync)
}
