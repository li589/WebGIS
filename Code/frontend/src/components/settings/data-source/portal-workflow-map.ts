/**
 * 门户 → 下载/处理工作流映射（2026-08-25 数据源管理改版 P2）。
 *
 * 「注册并添加到图层」能力仅对有下载链映射的门户开放：
 * 选中数据集 → 注册 → 按映射提交下载/预处理工作流 → 产物物化为图层。
 *
 * 后端真源：app/services/portal_workflow_map.py（此文件与其保持同源同步，
 * 前端仅用于按钮可见性判断与提交参数构造）。
 */

export interface PortalWorkflowMapping {
  /** 工作流类型标识（提交 /remote-sources/register-and-add 用） */
  workflow: string
  /** 该门户默认下载数据集（未检索到 dataset_key 匹配时的兜底） */
  defaultDatasetKeys: string[]
}

export const PORTAL_WORKFLOW_MAP: Record<string, PortalWorkflowMapping> = {
  // NASA NSIDC — SMAP L3 土壤水分（SPL3SMP_E）
  nsidc_data: {
    workflow: 'nsidc_smap_download',
    defaultDatasetKeys: ['SPL3SMP_E'],
  },
  // NASA GES DISC — GLDAS Noah 陆面同化
  nasa_gldas: {
    workflow: 'gldas_download',
    defaultDatasetKeys: ['GLDAS_NOAH025_3H'],
  },
  nasa_ges_disc: {
    workflow: 'gldas_download',
    defaultDatasetKeys: ['GLDAS_NOAH025_3H'],
  },
  // CDS — ERA5 再分析
  ecmwf_cds: {
    workflow: 'cds_download',
    defaultDatasetKeys: ['reanalysis-era5-land'],
  },
  // ESA Copernicus Data Space — S1/S2（下载链已有 cdse_download）
  esa_copernicus: {
    workflow: 'cdse_download',
    defaultDatasetKeys: [],
  },
  esa_download: {
    workflow: 'cdse_download',
    defaultDatasetKeys: [],
  },
  // NOAA NOMADS — GFS/GEFS
  noaa_nomads: {
    workflow: 'nomads_download',
    defaultDatasetKeys: ['gfs'],
  },
  // 国家卫星气象中心 NSMC — FY3 MWRI
  cma_nsmc: {
    workflow: 'fy_preprocess',
    defaultDatasetKeys: [],
  },
  cma_data: {
    workflow: 'fy_preprocess',
    defaultDatasetKeys: [],
  },
}
