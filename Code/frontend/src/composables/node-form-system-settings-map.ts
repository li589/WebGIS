/**
 * 节点表单 path 字段 ↔ 系统设置键映射（P2 契约真源）。
 * 供 system-settings-fill 与各 node-form 共用，避免新增节点漏接。
 */
export type SystemSettingsSource = 'dataRoot' | 'outputRoot' | 'cacheDir' | string

export type NodeFormSystemSettingsEntry = {
  nodeType: string
  formFields: Record<string, SystemSettingsSource>
}

/** 下载 / 预处理节点 path 字段映射表 */
export const NODE_FORM_SYSTEM_SETTINGS_MAP: NodeFormSystemSettingsEntry[] = [
  {
    nodeType: 'download/fy_preprocess',
    formFields: { input_dir: 'dataRoot', output_dir: 'outputRoot' },
  },
  {
    nodeType: 'download/gldas_download',
    formFields: { local_dir: 'dataRoot' },
  },
  {
    nodeType: 'download/gldas_nc4_to_mat',
    formFields: {
      input_dir: 'dataRoot',
      output_dir: 'dataRoot',
      ancillary_mat: 'dataRoot',
    },
  },
  {
    nodeType: 'download/cds_download',
    formFields: { target_dir: 'dataRoot' },
  },
  {
    nodeType: 'download/nomads_grib_download',
    formFields: { target_dir: 'dataRoot' },
  },
  {
    nodeType: 'download/cdse_download',
    formFields: { target_dir: 'dataRoot' },
  },
  {
    nodeType: 'download/nsidc_smap_download',
    formFields: { local_dir: 'dataRoot' },
  },
  {
    nodeType: 'download/ssh_sync',
    formFields: { local_path: 'dataRoot' },
  },
]

export function fieldMapForNodeType(nodeType: string): Record<string, SystemSettingsSource> {
  const entry = NODE_FORM_SYSTEM_SETTINGS_MAP.find((e) => e.nodeType === nodeType)
  return entry ? { ...entry.formFields } : {}
}
