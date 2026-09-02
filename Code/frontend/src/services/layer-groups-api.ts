/**
 * 图层平台 P1：图层分组运行时管理 API（管理员）。
 *
 * 分组 = 种子（catalog_seeds/layer_categories.json，codegen 兜底）⊕ 运行时管理状态
 * （后端 layer_groups 表）。本服务只封装管理端点；读取走 `fetchLayerCategories`
 * （runtime-api.ts，随目录一起下发）。分组 id 同时是 ACL `layer_group` 资源 id。
 */
import type { components } from '../types/api-contracts'
import { requestJson } from './_http'

export type LayerCategoryDef = components['schemas']['LayerCategoryDef']
export type LayerGroupCreateRequest = components['schemas']['LayerGroupCreateRequest']
export type LayerCategoryListResponse = components['schemas']['LayerCategoryResponse']
export type LayerGroupUpdateRequest = components['schemas']['LayerGroupUpdateRequest']
export type LayerGroupReorderRequest = components['schemas']['LayerGroupReorderRequest']
export type LayerGroupMembersRequest = components['schemas']['LayerGroupMembersRequest']

/** 新建自定义分组（追加到分组序列末尾）。 */
export function createLayerGroup(payload: LayerGroupCreateRequest): Promise<LayerCategoryDef> {
  return requestJson<LayerCategoryDef>('/layers/categories', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

/** 修改分组名称/样式/子分类（种子组与自建组均可）。 */
export function updateLayerGroup(
  groupId: string,
  payload: LayerGroupUpdateRequest,
): Promise<LayerCategoryDef> {
  return requestJson<LayerCategoryDef>(`/layers/categories/${encodeURIComponent(groupId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

/** 删除自定义分组（种子组由后端拒绝）；成员关系解除，图层回落种子分类。 */
export function deleteLayerGroup(groupId: string): Promise<LayerCategoryListResponse> {
  return requestJson<LayerCategoryListResponse>(
    `/layers/categories/${encodeURIComponent(groupId)}`,
    {
      method: 'DELETE',
    },
  )
}

/** 按给定顺序重排分组。 */
export function reorderLayerGroups(
  payload: LayerGroupReorderRequest,
): Promise<LayerCategoryListResponse> {
  return requestJson<LayerCategoryListResponse>('/layers/categories/order', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

/** 全量替换分组内图层成员（layer_id 列表）。 */
export function setLayerGroupMembers(
  groupId: string,
  payload: LayerGroupMembersRequest,
): Promise<LayerCategoryListResponse> {
  return requestJson<LayerCategoryListResponse>(
    `/layers/categories/${encodeURIComponent(groupId)}/members`,
    {
      method: 'PUT',
      body: JSON.stringify(payload),
    },
  )
}
