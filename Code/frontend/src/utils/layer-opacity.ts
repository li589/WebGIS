/**
 * 图层加载时的统一默认透明度（2026-10-21 用户要求）。
 *
 * 背景：此前"新建图层"「快照还原」「图例 hint 兜底」三条路径各写各的
 * （1 / 0.85 / 0.7 / 0.9），导致同一批图层勾上之后深浅不一，
 * 用户明确要求**所有图层加载透明度一律 0.9，不要不一样**。
 *
 * 规则：
 * - 这是"加载时"的默认值，用户之后在侧栏手动拖动透明度仍会生效（仅当前会话）。
 * - 快照还原也走本常量 ⇒ 浏览器里遗留的旧快照（0.7/0.85/1）会被拉回 0.9。
 * - 天气类渲染器内部用的视觉 alpha（scalar-contour 0.42、weather 0.7 等）
 *   不属于"图层透明度"，**不要**改成这个值。
 */
export const DEFAULT_LAYER_OPACITY = 0.9

/** 把外部传入的透明度收敛到合法区间；非有限数回落到默认值 */
export function normalizeLayerOpacity(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return DEFAULT_LAYER_OPACITY
  return Math.max(0, Math.min(1, value))
}
