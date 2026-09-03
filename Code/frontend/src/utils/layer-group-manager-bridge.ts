/**
 * 侧栏分组管理器与主题设置之间的轻量桥接（避免设置页硬依赖 LayerSidebar）。
 */
type OpenDetail = { themeId: number | null }

const EVENT = 'cgda:open-layer-group-manager'
const REFRESH_ACL = 'cgda:permission-resources-stale'

export function requestOpenLayerGroupManager(themeId?: number | null): void {
  if (typeof window === 'undefined') return
  const detail: OpenDetail = {
    themeId: themeId != null && themeId > 0 ? themeId : null,
  }
  window.dispatchEvent(new CustomEvent(EVENT, { detail }))
}

export function onOpenLayerGroupManager(
  handler: (themeId: number | null) => void,
): () => void {
  if (typeof window === 'undefined') return () => undefined
  const listener = (ev: Event) => {
    const detail = (ev as CustomEvent<OpenDetail>).detail
    handler(detail?.themeId ?? null)
  }
  window.addEventListener(EVENT, listener)
  return () => window.removeEventListener(EVENT, listener)
}

/** 分组/主题预设变更后通知 ACL 资源选择器重新拉取目录。 */
export function notifyPermissionResourcesStale(): void {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent(REFRESH_ACL))
}

export function onPermissionResourcesStale(handler: () => void): () => void {
  if (typeof window === 'undefined') return () => undefined
  window.addEventListener(REFRESH_ACL, handler)
  return () => window.removeEventListener(REFRESH_ACL, handler)
}
