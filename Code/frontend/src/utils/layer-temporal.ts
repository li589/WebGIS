/**
 * 从 ActiveLayer / 天气层构建 LayerTemporalSpec，并解析相对 T_ref 的生效切片。
 */
import type { ActiveLayer } from '../stores/layers/types'
import {
  defaultFollowPolicy,
  latestSlice,
  parseTimeStep,
  resolveSliceForInstant,
  sliceStartAsDateHour,
  timeListToSlices,
  timeStepToLegacyGranularity,
  type LayerTemporalSpec,
  type ResolvedSlice,
  type TimeStep,
} from './temporal-interval'

export function temporalSpecFromActiveLayer(
  layer: ActiveLayer | null | undefined,
): LayerTemporalSpec | null {
  if (!layer?.importedRaster) return null
  const raster = layer.importedRaster
  const step =
    (typeof raster.nativeStep === 'string'
      ? parseTimeStep(raster.nativeStep)
      : raster.nativeStep) ??
    (raster.timeList?.some((t) => /^\d{8}_\d{8}$/.test(t))
      ? ({ value: 8, unit: 'day' } as TimeStep)
      : raster.timeList?.length
        ? ({ value: 1, unit: 'day' } as TimeStep)
        : null)
  if (!step) return null
  const slices = raster.timeSlices?.length
    ? raster.timeSlices
    : timeListToSlices(raster.timeList ?? [])
  if (!slices.length) return null
  return {
    nativeStep: step,
    slices,
    followPolicy: raster.followPolicy ?? defaultFollowPolicy(step),
  }
}

export function resolveLayerEffectiveTime(
  layer: ActiveLayer | null | undefined,
  tRef: Date,
): ResolvedSlice | null {
  const spec = temporalSpecFromActiveLayer(layer)
  if (!spec) return null
  return resolveSliceForInstant(spec, tRef)
}

export function snapTargetFromLayer(layer: ActiveLayer | null | undefined): {
  date: Date
  hour: number
  label: string
  granularity: 'hour' | 'day' | 'month' | 'year' | 'static'
} | null {
  const spec = temporalSpecFromActiveLayer(layer)
  if (!spec) return null
  const latest = latestSlice(spec)
  if (!latest) return null
  const dh = sliceStartAsDateHour(latest)
  if (!dh) return null
  return {
    date: dh.date,
    hour: dh.hour,
    label: latest.label ?? String(latest.t0),
    granularity: timeStepToLegacyGranularity(spec.nativeStep),
  }
}

export function referenceInstantFromTimeline(date: Date, hour: number): Date {
  const d = new Date(date)
  const h = Math.floor(hour)
  const m = Math.round((hour - h) * 60)
  d.setHours(h, m, 0, 0)
  return d
}
