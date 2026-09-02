/**
 * 3D 地球渲染引擎契约（MapLibre 主链 + Cesium 实验）。
 * MapLibre 路径仍由 MapCanvas 承载；Cesium 实现见 ./cesium/。
 */

export type GlobeRenderEngine = 'maplibre' | 'cesium'

/** 可挂载的引擎宿主最小接口（后续 basemap / overlay 适配器挂这里）。 */
export interface GlobeEngineHost {
  kind: GlobeRenderEngine
  mount(el: HTMLElement): Promise<void>
  resize(): void
  destroy(): void
}
