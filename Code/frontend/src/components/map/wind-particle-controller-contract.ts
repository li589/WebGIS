/**
 * 风粒子控制器公开契约。
 *
 * `WindParticleOverlayController`（Canvas 2D 实现）与
 * `WindParticleWebGLOverlayController`（WebGL 实现）都满足该契约，
 * 使 weather-overlay 管线可在两种实现间切换（facade 的 DI seam）。
 *
 * 说明：TypeScript 结构类型对接口只校验公开成员，类的私有字段不影响
 * 兼容性。因此现有 Canvas controller 无需任何改动即可满足本契约；
 * 管线侧仅需把类型注解从具体类拓宽为本接口（B7 阶段一次性完成）。
 */
import type { WeatherOverlayState } from './weather-overlay-registry'
import type { WindDisplayMode } from './wind-display-mode'

/** sync() 第二参数的契约（与 weather-overlay-services.ts 实际传入的形状一致）。 */
export interface WindParticleSyncOptions {
  /** 本次 overlay 同步的 token（用于过期检测） */
  overlayToken: number
  /** 读取当前全局同步 token */
  getSyncWeatherToken: () => number
  /** 读取当前启用的风场可视化图层 catalogId（mode≠off 时） */
  getEnabledParticleFlowCatalogId: () => string | null
  /** 风场显示三态；缺省按 particle 处理（兼容旧调用） */
  getWindDisplayMode?: () => WindDisplayMode
}

/** 风粒子控制器公开 API（两种实现的公共面）。 */
export interface WindParticleControllerContract {
  /** 当前激活的粒子流 catalogId（由 coordinator 的 reconcile 逻辑读写） */
  activeCatalogId: string | null

  /** 重置内部状态：销毁已创建的渲染层、中断挂起的 fetch */
  reset(options?: { invalidatePendingFetch?: boolean }): void

  /** 移除某 catalogId 对应的地图产物；若恰好是激活图层则一并 reset，返回是否命中 */
  removeCatalogArtifacts(catalogId: string): boolean

  /** 主同步入口：按 overlayState 拉取/更新风场数据并驱动渲染层 */
  sync(overlayState: WeatherOverlayState, options: WindParticleSyncOptions): Promise<void>

  /** 彻底销毁（含 reset 与激活 id 清理） */
  destroy(): void
}
