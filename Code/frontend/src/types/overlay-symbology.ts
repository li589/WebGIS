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
  /** 变量代号（SM / VOD / OMEGA）。后端 2026-10-26 起与 `unit` 分开返回 */
  label?: string
  opacity?: number
  /** 有可读源时可服务端重着色 */
  supports_recolor?: boolean
  /** 来源代号（smap / fy / station…）。后端 /overlay-bounds 的 meta 直接给出 */
  source?: string
  /** 来源中文标签（SMAP / 风云卫星）。用于区分同名图层与日期提示前缀 */
  source_label?: string
  /** 变量中文标签（土壤水分 / 植被光学厚度） */
  variable_label?: string
  /** 单位中文写法（m³/m³ / 无量纲） */
  unit_label?: string
}
