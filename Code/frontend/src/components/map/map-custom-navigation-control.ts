/**
 * 兼容入口：实现已迁至 map-chrome-controls.ts（缩放/旋转/定位 + 比例尺）。
 * 新代码请直接从 './map-chrome-controls' 导入。
 */
export {
  MapChromeNavigationControl,
  MapCustomNavigationControl,
  createMapChromeScaleControl,
  addMapChromeControls,
  ensureMapChromeControlStyles,
  type MapChromeNavigationOptions,
  type AddMapChromeControlsOptions,
} from './map-chrome-controls'
