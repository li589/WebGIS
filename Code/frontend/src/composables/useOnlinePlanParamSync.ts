/**
 * useOnlinePlanParamSync — 流水线在线节点表单 ↔ 计划会话 draft 同源。
 */
import { useOnlinePlanSessionStore } from '../stores/online-plan-session'
import {
  ONLINE_PLAN_PARAM_KEYS,
  mergePlanParamOverrides,
  type OnlinePlanParamKey,
} from '../utils/online-plan-params'

export function useOnlinePlanParamSync() {
  const plan = useOnlinePlanSessionStore()

  function pushFormParamToPlan(key: string, value: unknown, catalogId?: string | null) {
    if (!ONLINE_PLAN_PARAM_KEYS.includes(key as OnlinePlanParamKey)) return
    const targetId = catalogId || plan.activeCatalogId
    if (!targetId) return
    const tab = plan.tabs.find((t) => t.catalogId === targetId)
    if (!tab) return
    plan.updateTab(targetId, {
      paramOverrides: mergePlanParamOverrides(tab.paramOverrides, { [key]: value }),
    })
  }

  function pullPlanParamsForForm(catalogId?: string | null): Record<string, unknown> | null {
    const targetId = catalogId || plan.activeCatalogId
    if (!targetId) return null
    const tab = plan.tabs.find((t) => t.catalogId === targetId)
    return tab?.paramOverrides ?? null
  }

  return { pushFormParamToPlan, pullPlanParamsForForm, plan }
}
