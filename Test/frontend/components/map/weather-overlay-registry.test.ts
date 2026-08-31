/**
 * WEATHER_OVERLAY_RENDERERS 分派测试。
 *
 * 2026-08-25 平滑渲染修复回归锁：heatmap 图层（后端 constants.py 给
 * temperature/humidity 等标量层的 paint_mode）此前直接调 grid fill
 * （MapLibre 网格），完全绕过 syncScalarFieldWebGL（WebGL 连续面），
 * 导致「平滑渲染-连续数值面」开关对这类图层无效。现在 heatmap 与
 * grid_fill 同构：WebGL 优先，失败回退 grid fill。
 */
import { describe, expect, it, vi } from 'vitest'

import { renderWeatherOverlayState } from '../../../../Code/frontend/src/components/map/weather-overlay-registry'
import type { WeatherOverlayState } from '../../../../Code/frontend/src/components/map/weather-overlay-registry'

function buildState(paint_mode: string): WeatherOverlayState {
  return {
    catalogId: 'temperature',
    geojsonUrl: null,
    geojsonData: {
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [113, 23] },
          properties: { temperature_2m: 25 },
        },
      ],
    },
    cogPreviewUrl: null,
    cogBbox: null,
    viewportBounds: null,
    renderHint: {
      layer_id: 'temperature',
      paint_mode,
      palette: 'thermal-orange',
      primary_metric: 'temperature_2m',
      unit_label: '°C',
      opacity: 0.82,
      legend_ticks: [-10, 0, 10, 20, 30, 40],
      notes: [],
    },
    opacity: 0.82,
  }
}

function buildContext(options?: { scalarResult?: boolean }) {
  const scalar = vi.fn(() => options?.scalarResult ?? true)
  const gridFill = vi.fn()
  const context = {
    enabledParticleFlowCatalogId: null,
    markRendered: vi.fn(),
    syncWeatherCogOverlay: vi.fn(),
    syncWeatherGridFillOverlay: gridFill,
    syncWeatherPointOverlay: vi.fn(),
    syncWindParticleFlow: vi.fn(),
    syncScalarFieldWebGL: scalar,
  }
  return { context, scalar, gridFill }
}

describe('renderWeatherOverlayState heatmap 平滑渲染分派', () => {
  it('WebGL 可用时 heatmap 优先走 syncScalarFieldWebGL，不落 grid fill', () => {
    const state = buildState('heatmap')
    const { context, scalar, gridFill } = buildContext({ scalarResult: true })

    const rendered = renderWeatherOverlayState(state, context, 1)

    expect(rendered).toBe(true)
    expect(scalar).toHaveBeenCalledTimes(1)
    expect(gridFill).not.toHaveBeenCalled()
    expect(context.markRendered).toHaveBeenCalledWith('temperature')
  })

  it('WebGL 不可用时 heatmap 回退 grid fill（paint_mode 归一为 grid_fill）', () => {
    const state = buildState('heatmap')
    const { context, scalar, gridFill } = buildContext({ scalarResult: false })

    const rendered = renderWeatherOverlayState(state, context, 1)

    expect(rendered).toBe(true)
    expect(scalar).toHaveBeenCalledTimes(1)
    expect(gridFill).toHaveBeenCalledTimes(1)
    // 回退时把 paint_mode 归一为 grid_fill（与修复前行为一致）
    expect(gridFill.mock.calls[0][0].renderHint.paint_mode).toBe('grid_fill')
  })

  it('grid_fill 图层保持 WebGL 优先 + 回退的原行为', () => {
    const state = buildState('grid_fill')
    const ok = buildContext({ scalarResult: true })
    renderWeatherOverlayState(state, ok.context, 1)
    expect(ok.scalar).toHaveBeenCalledTimes(1)
    expect(ok.gridFill).not.toHaveBeenCalled()

    const fallback = buildContext({ scalarResult: false })
    renderWeatherOverlayState(state, fallback.context, 1)
    expect(fallback.gridFill).toHaveBeenCalledTimes(1)
  })
})
