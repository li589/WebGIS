import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

const activeLayers = ref<
  Array<{
    instanceId: string
    catalogId: string
    visible: boolean
    opacity: number
    isAdminBoundary?: boolean
    name?: string
  }>
>([])

const toggleLayerVisibility = vi.fn((instanceId: string) => {
  const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
  if (layer) layer.visible = !layer.visible
})
const setLayerOpacity = vi.fn((instanceId: string, opacity: number) => {
  const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
  if (layer) layer.opacity = opacity
})
const addLayer = vi.fn((catalogId: string) => {
  activeLayers.value.push({
    instanceId: `inst-${catalogId}`,
    catalogId,
    visible: true,
    opacity: 1,
  })
})
const selectLayer = vi.fn()
const setSidebarView = vi.fn()
const getCatalogAddBlockReason = vi.fn((_catalogId: string) => null as string | null)

vi.mock('@/stores/layers/selectors', () => ({
  useLayerWorkspace: () => ({
    activeLayers,
    toggleLayerVisibility,
    setLayerOpacity,
    addLayer,
    selectLayer,
    setSidebarView,
    getCatalogAddBlockReason,
  }),
}))

describe('executeAgentUiIntent', () => {
  beforeEach(() => {
    activeLayers.value = [
      {
        instanceId: 'i1',
        catalogId: 'cmfd-precip-cn',
        visible: false,
        opacity: 1,
      },
    ]
    vi.clearAllMocks()
  })

  it('toggles visibility on when requested', async () => {
    const { executeAgentUiIntent } = await import('@/components/agent/agent-ui-intent')
    const result = executeAgentUiIntent({
      name: 'set_layer_visibility',
      args: { catalog_id: 'cmfd-precip-cn', visible: true },
    })
    expect(result.ok).toBe(true)
    expect(toggleLayerVisibility).toHaveBeenCalledWith('i1')
    expect(activeLayers.value[0]?.visible).toBe(true)
  })

  it('adds layer when missing then shows it', async () => {
    activeLayers.value = []
    const { executeAgentUiIntent } = await import('@/components/agent/agent-ui-intent')
    const result = executeAgentUiIntent({
      name: 'set_layer_visibility',
      args: { catalog_id: 'dem-etopo', visible: true },
    })
    expect(addLayer).toHaveBeenCalledWith('dem-etopo')
    expect(result.ok).toBe(true)
  })

  it('refuses to add when catalog is blocked', async () => {
    activeLayers.value = []
    getCatalogAddBlockReason.mockReturnValueOnce('无权限')
    const { executeAgentUiIntent } = await import('@/components/agent/agent-ui-intent')
    const result = executeAgentUiIntent({
      name: 'set_layer_visibility',
      args: { catalog_id: 'secret-layer', visible: true },
    })
    expect(result.ok).toBe(false)
    expect(addLayer).not.toHaveBeenCalled()
  })

  it('sets opacity', async () => {
    const { executeAgentUiIntent } = await import('@/components/agent/agent-ui-intent')
    const result = executeAgentUiIntent({
      name: 'set_layer_opacity',
      args: { catalog_id: 'cmfd-precip-cn', opacity: 0.5 },
    })
    expect(result.ok).toBe(true)
    expect(setLayerOpacity).toHaveBeenCalledWith('i1', 0.5)
  })

  it('fits layer via handler', async () => {
    const fit = vi.fn(() => true)
    const { executeAgentUiIntent } = await import('@/components/agent/agent-ui-intent')
    const result = executeAgentUiIntent(
      { name: 'fit_layer', args: { catalog_id: 'cmfd-precip-cn' } },
      { fitToLayerExtent: fit },
    )
    expect(result.ok).toBe(true)
    expect(fit).toHaveBeenCalledWith('i1')
  })

  it('lists active layers with names instead of opaque placeholder', async () => {
    activeLayers.value = [
      {
        instanceId: 'i1',
        catalogId: 'cmfd-precip-cn',
        visible: true,
        opacity: 1,
        name: 'CMFD 降水',
      },
      {
        instanceId: 'i2',
        catalogId: 'admin-boundary',
        visible: true,
        opacity: 1,
        isAdminBoundary: true,
        name: '边界',
      },
    ]
    const { executeAgentUiIntent } = await import('@/components/agent/agent-ui-intent')
    const result = executeAgentUiIntent({ name: 'list_active_layers', args: {} })
    expect(result.ok).toBe(true)
    expect(result.message).toContain('CMFD 降水')
    expect(result.message).toContain('cmfd-precip-cn')
    expect(result.message).not.toContain('已使用客户端活动图层上下文')
    expect(result.message).not.toContain('边界')
  })

  it('reports empty active layers clearly', async () => {
    activeLayers.value = []
    const { executeAgentUiIntent } = await import('@/components/agent/agent-ui-intent')
    const result = executeAgentUiIntent({ name: 'list_active_layers', args: {} })
    expect(result.ok).toBe(true)
    expect(result.message).toContain('没有活动图层')
  })
})
