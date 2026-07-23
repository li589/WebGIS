/**
 * 天气瓦片地图横幅聚合：按层隔离，避免单层无数据盖住其它健康层。
 */

export interface WeatherTileBannerLayerInput {
  /** 显示名（优先中文 metric / label） */
  label: string
  active: boolean
  cachedInViewport: number
  missingInViewport: number
  pending: number
  gapSweepActive: boolean
  errorType: string | null
  errorMessage: string | null
}

export interface WeatherTileBannerModel {
  show: boolean
  isLoading: boolean
  error: string | null
  partial: string | null
}

const MAX_NAMED_LAYERS = 3

function formatNamedList(labels: string[], fallbackMessage: string): string {
  const named = labels.slice(0, MAX_NAMED_LAYERS)
  if (named.length === 0) return fallbackMessage
  const joined = named.join('、')
  const more = labels.length > MAX_NAMED_LAYERS ? `等${labels.length}层` : ''
  return `${joined}${more}`
}

/**
 * 聚合可见天气层状态为全图横幅。
 * - error：无一健康缓存且至少一层有 error
 * - loading：全部无缓存且有 pending
 * - partial：有缓存但仍缺洞（文案带层名）
 */
export function aggregateWeatherTileBanner(
  layers: WeatherTileBannerLayerInput[],
): WeatherTileBannerModel {
  const active = layers.filter((l) => l.active)
  if (active.length === 0) {
    return { show: false, isLoading: false, error: null, partial: null }
  }

  const anyHealthyCache = active.some((l) => l.cachedInViewport > 0)
  const errored = active.filter((l) => l.errorType && l.cachedInViewport === 0)

  if (!anyHealthyCache && errored.length > 0) {
    const parts = errored.map((l) => {
      const detail = l.errorMessage || '数据加载失败'
      return `${l.label}：${detail}`
    })
    return {
      show: true,
      isLoading: false,
      error: formatNamedList(parts, '天气数据加载失败'),
      partial: null,
    }
  }

  if (!anyHealthyCache && active.some((l) => l.pending > 0)) {
    return { show: true, isLoading: true, error: null, partial: null }
  }

  const partialLayers = active.filter(
    (l) => l.cachedInViewport > 0 && l.missingInViewport > 0 && l.pending === 0,
  )
  if (partialLayers.length > 0) {
    const parts = partialLayers.map((l) => {
      const progress = `${l.cachedInViewport}/${l.cachedInViewport + l.missingInViewport}`
      const tip = l.gapSweepActive ? '正在补全空洞…' : '部分区域待重试'
      return `${l.label} ${progress}，${tip}`
    })
    return {
      show: true,
      isLoading: false,
      error: null,
      partial: formatNamedList(parts, '部分区域待重试'),
    }
  }

  return { show: false, isLoading: false, error: null, partial: null }
}
