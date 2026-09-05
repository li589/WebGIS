/**
 * 图层分组运行时管理 API（主题预设直写为主）。
 *
 * 分组 = 种子（catalog_seeds/layer_categories.json）⊕ 主题预设
 * （theme_layer_group_presets）。管理写操作传 theme_id 时直接改该主题预设；
 * 省略 theme_id 仍兼容个人工作区（迁移用）。读取编辑预览走
 * `fetchLayerCategories({ themeId })` / `fetchThemeLayerGroupPreset`。
 */
import type { components } from '../types/api-contracts'
import { requestJson } from './_http'

export type LayerCategoryDef = components['schemas']['LayerCategoryDef']
export type LayerGroupCreateRequest = components['schemas']['LayerGroupCreateRequest']
export type LayerCategoryListResponse = components['schemas']['LayerCategoryResponse']
export type LayerGroupUpdateRequest = components['schemas']['LayerGroupUpdateRequest']
export type LayerGroupReorderRequest = components['schemas']['LayerGroupReorderRequest']
export type LayerGroupMembersRequest = components['schemas']['LayerGroupMembersRequest']

export type ThemeLayerGroupPresetMeta = {
  theme_id: number
  has_preset: boolean
  updated_at: string | null
  updated_by_user_id: number | null
  display_name_count?: number
}

export type ThemeLayerGroupPresetDetail = ThemeLayerGroupPresetMeta & {
  groups: LayerCategoryDef[]
  assignments: Record<string, string>
  display_names: Record<string, string>
  /** 种子层 display_name（编辑器 placeholder；不受主题覆盖） */
  seed_display_names?: Record<string, string>
}

function themeQuery(themeId?: number | null): string {
  if (themeId == null || !Number.isFinite(themeId) || themeId <= 0) return ''
  return `?theme_id=${encodeURIComponent(String(themeId))}`
}

/** 新建自定义分组（推荐传 themeId 写入主题预设）。 */
export function createLayerGroup(
  payload: LayerGroupCreateRequest,
  themeId?: number | null,
): Promise<LayerCategoryDef> {
  return requestJson<LayerCategoryDef>(`/layers/categories${themeQuery(themeId)}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

/** 修改分组名称/样式/子分类。 */
export function updateLayerGroup(
  groupId: string,
  payload: LayerGroupUpdateRequest,
  themeId?: number | null,
): Promise<LayerCategoryDef> {
  return requestJson<LayerCategoryDef>(
    `/layers/categories/${encodeURIComponent(groupId)}${themeQuery(themeId)}`,
    {
      method: 'PATCH',
      body: JSON.stringify(payload),
    },
  )
}

/** 删除自定义分组（种子组由后端拒绝）。 */
export function deleteLayerGroup(
  groupId: string,
  themeId?: number | null,
): Promise<LayerCategoryListResponse> {
  return requestJson<LayerCategoryListResponse>(
    `/layers/categories/${encodeURIComponent(groupId)}${themeQuery(themeId)}`,
    { method: 'DELETE' },
  )
}

/** 按给定顺序重排分组。 */
export function reorderLayerGroups(
  payload: LayerGroupReorderRequest,
  themeId?: number | null,
): Promise<LayerCategoryListResponse> {
  return requestJson<LayerCategoryListResponse>(`/layers/categories/order${themeQuery(themeId)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

/** 全量替换分组内图层成员。 */
export function setLayerGroupMembers(
  groupId: string,
  payload: LayerGroupMembersRequest,
  themeId?: number | null,
): Promise<LayerCategoryListResponse> {
  return requestJson<LayerCategoryListResponse>(
    `/layers/categories/${encodeURIComponent(groupId)}/members${themeQuery(themeId)}`,
    {
      method: 'PUT',
      body: JSON.stringify(payload),
    },
  )
}

/** 合并写入主题图层显示名覆盖（空字符串清除）。 */
export function putThemeLayerDisplayNames(
  themeId: number,
  displayNames: Record<string, string>,
): Promise<ThemeLayerGroupPresetMeta> {
  return requestJson<ThemeLayerGroupPresetMeta>(
    `/layers/categories/theme-preset/${encodeURIComponent(String(themeId))}/display-names`,
    {
      method: 'PUT',
      body: JSON.stringify({ display_names: displayNames }),
    },
  )
}

/** 将当前管理员个人工作区导入到主题预设（一次性迁移）。 */
export function syncLayerGroupsToTheme(themeId: number): Promise<ThemeLayerGroupPresetMeta> {
  return requestJson<ThemeLayerGroupPresetMeta>(
    `/layers/categories/sync-to-theme/${encodeURIComponent(String(themeId))}`,
    { method: 'POST' },
  )
}

/** 读取主题图层分组预设详情（无预设时 groups=种子基线，has_preset=false）。 */
export function fetchThemeLayerGroupPreset(themeId: number): Promise<ThemeLayerGroupPresetDetail> {
  return requestJson<ThemeLayerGroupPresetDetail>(
    `/layers/categories/theme-preset/${encodeURIComponent(String(themeId))}`,
    { sensitiveGet: true },
  )
}

/** 清除主题图层分组预设。 */
export function deleteThemeLayerGroupPreset(
  themeId: number,
): Promise<{ theme_id: number; deleted: boolean }> {
  return requestJson<{ theme_id: number; deleted: boolean }>(
    `/layers/categories/theme-preset/${encodeURIComponent(String(themeId))}`,
    { method: 'DELETE' },
  )
}
