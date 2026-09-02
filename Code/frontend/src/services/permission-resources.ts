/**
 * ACL 资源目录服务（主题默认 ACL / 用户权限覆盖的输入辅助）。
 *
 * 从既有后端端点汇聚可选资源（图层 / 图层分组 / 工作流 / 数据源），
 * 供设置界面的资源选择器下拉使用；后端不可用时回落静态清单，
 * 手动输入 ID 始终可用（选择器不强制收录）。
 */
import { requestJson } from './_http'
import type { components } from '../types/api-contracts'

export interface ResourceOption {
  id: string
  label: string
  /** 次要信息（如图层所属分组），下拉中弱化展示 */
  hint?: string
}

export interface PermissionResourceCatalog {
  layers: ResourceOption[]
  layerGroups: ResourceOption[]
  workflows: ResourceOption[]
  dataSources: ResourceOption[]
}

// ── 静态兜底（后端目录不可用时） ────────────────────────────────────────────

const FALLBACK_LAYERS: ResourceOption[] = [
  { id: 'wind-field', label: '风场（10m）' },
  { id: 'temperature', label: '温度（2m）' },
  { id: 'precipitation', label: '降水' },
  { id: 'humidity', label: '湿度' },
  { id: 'visibility', label: '能见度' },
  { id: 'smap-soil-moisture', label: 'SMAP 土壤水分' },
  { id: 'smap-omega', label: 'SMAP 反演 ω' },
  { id: 'modis-ndvi', label: 'MODIS NDVI' },
]

const FALLBACK_WORKFLOWS: ResourceOption[] = [
  { id: 'smap-soil-inversion', label: 'SMAP 土壤水分反演' },
  { id: 'modis-ndvi-inversion', label: 'MODIS NDVI 反演' },
  { id: 'terrain-shade', label: '地形阴影' },
  { id: 'rain-stats', label: '降水统计' },
]

/** 数据源无公开列表端点：精选常用 provider/model id（可手动输入其他） */
export const KNOWN_DATA_SOURCES: ResourceOption[] = [
  { id: 'open-meteo-local', label: 'Open-Meteo（本地）' },
  { id: 'open-meteo-online', label: 'Open-Meteo（在线）' },
  { id: 'gfs_global', label: 'GFS（全球）' },
  { id: 'ecmwf_ifs025', label: 'ECMWF IFS 0.25°' },
  { id: 'icon_seamless', label: 'ICON（融合）' },
  { id: 'era5', label: 'ERA5' },
  { id: 'smap', label: 'SMAP（NASA 资源）' },
  { id: 'modis', label: 'MODIS（NASA 资源）' },
]

// ── 端点响应形状（这些列表端点返回 {body: {workflows: [...]}} 服务包装） ──────

interface WorkflowListEnvelope {
  body?: { workflows?: Array<{ name?: string; description?: string }> }
}

async function safeGet<T>(url: string): Promise<T | null> {
  try {
    return await requestJson<T>(url, { silent: true })
  } catch {
    return null
  }
}

function fromWorkflowEnvelope(data: unknown): ResourceOption[] {
  const list = (data as WorkflowListEnvelope | null)?.body?.workflows ?? []
  return list
    .map((w) => ({ id: w.name ?? '', label: w.description || w.name || '' }))
    .filter((w) => w.id && w.label)
}

/** 汇聚 ACL 可选资源目录；部分失败时对应类别回落静态清单。 */
export async function fetchPermissionResourceCatalog(): Promise<PermissionResourceCatalog> {
  const [layerData, groupData, algoData, providerData] = await Promise.all([
    safeGet<components['schemas']['LayerCatalogResponse']>('/layers'),
    safeGet<components['schemas']['LayerCategoryResponse']>('/layers/categories'),
    safeGet<WorkflowListEnvelope>('/algorithm/workflows'),
    safeGet<WorkflowListEnvelope>('/provider/workflows'),
  ])

  const layers: ResourceOption[] = (layerData?.items ?? [])
    .map((item) => ({
      id: item.layer_id,
      label: item.display_name || item.layer_id,
      hint: item.category,
    }))
    .filter((o) => o.id)

  const layerGroups: ResourceOption[] = (groupData?.items ?? [])
    .map((item) => ({
      id: item.id,
      label: item.name,
      hint: item.is_custom ? '自建分组' : '种子分组',
    }))
    .filter((o) => o.id)

  const workflows: ResourceOption[] = [
    ...fromWorkflowEnvelope(algoData),
    ...fromWorkflowEnvelope(providerData),
  ].filter((w, index, all) => all.findIndex((x) => x.id === w.id) === index)

  return {
    layers: layers.length ? layers : FALLBACK_LAYERS,
    layerGroups,
    workflows: workflows.length ? workflows : FALLBACK_WORKFLOWS,
    dataSources: KNOWN_DATA_SOURCES,
  }
}
