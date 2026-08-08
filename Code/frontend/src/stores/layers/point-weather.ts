/**
 * 点天气查询 slice（X1/D2 渐进拆分阶段二）。
 *
 * 从 layers/index.ts 抽离：单工作流管理（同一时间只允许一个点查询运行），
 * 每次新查询中断上一次未完成查询。状态与逻辑内聚于本模块，
 * store 依赖（currentHour / provider 查询 / 图层判定）经 deps 注入。
 */
import { ref } from 'vue'

import { getWeatherPoint } from '../../services/runtime-api'
import type { WeatherPointResponse } from '../../services/runtime-api'

export interface PointWeatherSliceDeps {
  /** 时间轴当前 hour（0-based），用于计算默认预报时长 */
  getCurrentHour: () => number
  /** 判定 catalogId 是否 weatherengine 图层（非天气图层清空并短路） */
  isWeatherEngineLayer: (catalogId: string) => boolean
  /** API provider query 参数（undefined=auto，后端按注册优先级） */
  weatherProviderQuery: (catalogId: string) => string | undefined
}

export function createPointWeatherSlice(deps: PointWeatherSliceDeps) {
  const pointWeather = ref<WeatherPointResponse | null>(null)
  const pointWeatherLoading = ref(false)
  const pointWeatherError = ref<string | null>(null)
  const lastPointWeatherQuery = ref<{ lng: number; lat: number; catalogId: string } | null>(null)
  let pointWeatherAbortController: AbortController | null = null

  /** 清除点天气查询结果与状态 */
  function clearPointWeather() {
    if (pointWeatherAbortController) {
      pointWeatherAbortController.abort()
      pointWeatherAbortController = null
    }
    pointWeather.value = null
    pointWeatherError.value = null
    pointWeatherLoading.value = false
    lastPointWeatherQuery.value = null
  }

  /**
   * 提交点天气查询（作为单一工作流管理）。
   * 每次调用会中断上一次尚未完成的查询，确保同一时间只有一条点查询工作流在运行。
   */
  async function fetchPointWeather(
    lng: number,
    lat: number,
    catalogId: string,
    options?: { forecastHours?: number },
  ) {
    if (!deps.isWeatherEngineLayer(catalogId)) {
      clearPointWeather()
      return
    }
    // 中断上一次查询，保证单工作流约束
    if (pointWeatherAbortController) {
      pointWeatherAbortController.abort()
    }
    const controller = new AbortController()
    pointWeatherAbortController = controller
    pointWeatherLoading.value = true
    pointWeatherError.value = null
    lastPointWeatherQuery.value = { lng, lat, catalogId }
    // 覆盖时间轴当前 hour（0-based）及短时预报；至少 6 小时
    const forecastHours = Math.min(
      48,
      Math.max(6, Math.floor(options?.forecastHours ?? deps.getCurrentHour() + 1)),
    )
    try {
      const weather = await getWeatherPoint({
        layer_id: catalogId,
        latitude: lat,
        longitude: lng,
        forecast_hours: forecastHours,
        place_name: `${lat.toFixed(3)}, ${lng.toFixed(3)}`,
        provider: deps.weatherProviderQuery(catalogId),
        signal: controller.signal,
      })
      if (controller.signal.aborted) return
      pointWeather.value = weather
    } catch (error) {
      if (controller.signal.aborted) return
      pointWeather.value = null
      pointWeatherError.value =
        error instanceof Error ? error.message : 'Failed to load point weather'
    } finally {
      if (!controller.signal.aborted) {
        pointWeatherLoading.value = false
      }
      if (pointWeatherAbortController === controller) {
        pointWeatherAbortController = null
      }
    }
  }

  return {
    pointWeather,
    pointWeatherLoading,
    pointWeatherError,
    lastPointWeatherQuery,
    clearPointWeather,
    fetchPointWeather,
  }
}
