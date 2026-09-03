// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'

import {
  notifyPermissionResourcesStale,
  onOpenLayerGroupManager,
  onPermissionResourcesStale,
  requestOpenLayerGroupManager,
} from '@/utils/layer-group-manager-bridge'

describe('layer-group-manager-bridge', () => {
  it('requestOpenLayerGroupManager dispatches themeId', () => {
    const handler = vi.fn()
    const stop = onOpenLayerGroupManager(handler)
    requestOpenLayerGroupManager(42)
    expect(handler).toHaveBeenCalledWith(42)
    stop()
  })

  it('notifyPermissionResourcesStale notifies ACL refresh listeners', () => {
    const handler = vi.fn()
    const stop = onPermissionResourcesStale(handler)
    notifyPermissionResourcesStale()
    expect(handler).toHaveBeenCalledTimes(1)
    stop()
  })

  it('requestOpenLayerGroupManager without id passes null', () => {
    const handler = vi.fn()
    const stop = onOpenLayerGroupManager(handler)
    requestOpenLayerGroupManager()
    expect(handler).toHaveBeenCalledWith(null)
    stop()
  })
})
