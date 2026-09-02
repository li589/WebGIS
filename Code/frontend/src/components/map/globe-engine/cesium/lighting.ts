/**
 * Cesium 日夜光影：用本地时间轴小时 + 日期设置 clock，驱动 globe.enableLighting。
 */
import type { GlobeDaylightMode } from '../../../../services/settings-local'

type CesiumModule = typeof import('cesium')
type CesiumViewer = import('cesium').Viewer

/** 把「本地日小时 + 日历日」写成 JulianDate（与晨昏线模型同输入）。 */
export function julianDateFromLocalHour(
  Cesium: CesiumModule,
  hour: number,
  date?: Date | null,
): import('cesium').JulianDate {
  const base = date instanceof Date && !Number.isNaN(date.getTime()) ? new Date(date) : new Date()
  const h = ((hour % 24) + 24) % 24
  const whole = Math.floor(h)
  const minutes = Math.round((h - whole) * 60)
  base.setHours(whole, minutes, 0, 0)
  return Cesium.JulianDate.fromDate(base)
}

export function applyCesiumDaylight(
  Cesium: CesiumModule,
  viewer: CesiumViewer,
  mode: GlobeDaylightMode,
  hour: number,
  date?: Date | null,
): void {
  const natural = mode === 'natural'
  const globe = viewer.scene.globe
  globe.enableLighting = natural
  // 部分 Cesium 版本才有动态大气光；缺失时静默跳过
  const g = globe as unknown as {
    dynamicAtmosphereLighting?: boolean
    atmosphereLightIntensity?: number
  }
  if (typeof g.dynamicAtmosphereLighting === 'boolean') {
    g.dynamicAtmosphereLighting = natural
  }
  if (typeof g.atmosphereLightIntensity === 'number') {
    g.atmosphereLightIntensity = natural ? 10 : 0
  }
  if (!natural && Cesium.SunLight) {
    viewer.scene.light = new Cesium.SunLight()
  }
  viewer.clock.shouldAnimate = false
  viewer.clock.currentTime = julianDateFromLocalHour(Cesium, hour, date)
}
