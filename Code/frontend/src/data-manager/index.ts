/**
 * 数据管理器公共出口。
 *
 * 宿主（ModeToolbar / LayerSidebar / InfoPanel / DashboardView）只应依赖本入口：
 * openDataWorkspace / exportLayer / registerImported* / processFiles。
 * 勿在面板外直接调用 /import 上传细节。
 */
export * from './core/api'
export * from './core/workspace-store'
export { exportLayer, exportLayersBatch, type ExportFormat } from './adapters/export'
export {
  registerImportedVectorLayer,
  registerImportedRasterLayer,
  removeImportedLayer,
  focusImportedLayer,
} from './adapters/layers'
