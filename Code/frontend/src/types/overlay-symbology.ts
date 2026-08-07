/**
 * 叠加图层符号化元数据（调色板/值域/单位/透明度）。
 *
 * 从 components/map/layer-symbology.ts 提取（D1 依赖倒置修复）：
 * stores/ 持久化与恢复仅依赖本类型，不反向依赖 components 渲染实现。
 */
export interface OverlaySymbologyMeta {
  palette?: string
  vmin?: number | null
  vmax?: number | null
  unit?: string
  opacity?: number
  /** 有可读源时可服务端重着色 */
  supports_recolor?: boolean
}
