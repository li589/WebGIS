import { demoLayerCatalog, type DemoLayer, type DemoLayerCatalogItem } from './demo-data'

interface DemoAvailabilityProfile {
  state: 'empty' | 'partial' | 'ready'
  label: string
  description: string
  missingFields: string[]
}

interface DemoRawHotspotRecord {
  id: string
  name: string
  lng: number
  lat: number
  [key: string]: string | number
}

interface DemoRawPayload {
  [key: string]: string | number | DemoRawHotspotRecord[] | undefined
  hotspots?: DemoRawHotspotRecord[]
}

export interface BackendDemoFieldAliasMap {
  metric_value: string[]
  hotspot_value: string[]
  observation_time: string[]
  status_label: string[]
}

export interface BackendDemoSnapshot {
  layer_id: string
  display_name: string
  category: string
  metric_label: string
  metric_unit: string
  metric_precision: number
  update_label: string
  source_label: string
  accent_color: string
  accent_glow: string
  chip_tone: string
  data_state_mode: 'demo' | 'placeholder' | 'mixed'
  data_state_label: string
  empty_state_label: string
  availability_state: DemoAvailabilityProfile['state']
  trend_label: string
  summary: string
  status_label: string
  confidence_label: string
  requested_hour: number
  field_aliases: BackendDemoFieldAliasMap
  raw_payload: DemoRawPayload
}

export interface BackendDemoSnapshotsResponse {
  requested_hour: number
  items: BackendDemoSnapshot[]
}

function normalizeHour(hour: number) {
  return ((hour % 24) + 24) % 24
}

function bandMatches(hour: number, band: DemoLayerCatalogItem['timeBands'][number]) {
  if (band.startHour <= band.endHour) {
    return hour >= band.startHour && hour < band.endHour
  }

  return hour >= band.startHour || hour < band.endHour
}

function formatMetricValue(value: number, unit: string, precision: number) {
  return `${value.toFixed(precision)} ${unit}`.trim()
}

function formatHotspotValue(value: number, unit: string, precision: number) {
  return `${value.toFixed(precision)} ${unit}`.trim()
}

function formatObservationTimeLabel(hour: number) {
  const wholeHours = Math.floor(hour)
  const minutes = Math.round((hour - wholeHours) * 60)
  return `${String(wholeHours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
}

function createAvailabilityProfile(state: DemoAvailabilityProfile['state']): DemoAvailabilityProfile {
  if (state === 'ready') {
    return {
      state,
      label: '完整数据',
      description: '核心指标、热点值和时间字段都已齐备。',
      missingFields: [],
    }
  }

  if (state === 'partial') {
    return {
      state,
      label: '半数据',
      description: '部分字段已返回，可用于框架联调但仍需补齐缺项。',
      missingFields: ['metric', 'status', 'time', 'hotspots'],
    }
  }

  return {
    state,
    label: '空数据',
    description: '当前仅保留协议占位，等待真实数据接入。',
    missingFields: [],
  }
}

function pickAliasValue<T extends string | number>(
  record: Record<string, string | number | undefined>,
  aliases: string[],
): T | undefined {
  for (const alias of aliases) {
    const value = record[alias]
    if (value !== undefined) {
      return value as T
    }
  }

  return undefined
}

function createDemoRawPayload(
  layer: DemoLayerCatalogItem,
  timeBand: DemoLayerCatalogItem['timeBands'][number],
  hour: number,
  normalizedPhase: number,
): DemoRawPayload {
  const metricAlias = layer.fieldAliases.metricValue[Math.floor(hour) % layer.fieldAliases.metricValue.length]
  const statusAlias = layer.fieldAliases.statusLabel[Math.floor(hour + 1) % layer.fieldAliases.statusLabel.length]
  const observationAlias =
    layer.fieldAliases.observationTime[Math.floor(hour + 2) % layer.fieldAliases.observationTime.length]
  const hotspotAlias = layer.fieldAliases.hotspotValue[Math.floor(hour + 3) % layer.fieldAliases.hotspotValue.length]

  if (timeBand.availabilityState === 'empty') {
    return {
      [observationAlias]: formatObservationTimeLabel(hour),
      [statusAlias]: 'missing',
      hotspots: [],
    }
  }

  const rawPayload: DemoRawPayload = {
    [metricAlias]: Number(
      (timeBand.metricBase + normalizedPhase * (layer.metricPrecision === 0 ? 1 : 0.35)).toFixed(
        layer.metricPrecision,
      ),
    ),
    [statusAlias]: timeBand.statusLabel,
    [observationAlias]: formatObservationTimeLabel(hour),
  }

  const hotspotRecords = layer.hotspotTemplates.map((hotspot, index) => {
    const baseRecord: DemoRawHotspotRecord = {
      id: hotspot.id,
      name: hotspot.name,
      lng: hotspot.lng,
      lat: hotspot.lat,
    }

    const nextValue =
      hotspot.baseValue + timeBand.hotspotDrift + normalizedPhase * hotspot.amplitude * (0.55 + index * 0.12)

    if (!(timeBand.availabilityState === 'partial' && index === layer.hotspotTemplates.length - 1)) {
      baseRecord[hotspotAlias] = Number(nextValue.toFixed(layer.metricPrecision))
    }

    return baseRecord
  })

  rawPayload.hotspots = hotspotRecords
  return rawPayload
}

function adaptDemoPayload(
  layer: DemoLayerCatalogItem,
  payload: DemoRawPayload,
  availability: DemoAvailabilityProfile,
  fallbackBand: DemoLayerCatalogItem['timeBands'][number],
): Pick<DemoLayer, 'metricValue' | 'statusLabel' | 'observationTimeLabel' | 'hotspots' | 'missingFieldsLabel'> {
  const rawMetricValue = pickAliasValue<number>(
    payload as Record<string, string | number | undefined>,
    layer.fieldAliases.metricValue,
  )
  const rawStatusLabel = pickAliasValue<string>(
    payload as Record<string, string | number | undefined>,
    layer.fieldAliases.statusLabel,
  )
  const rawObservationTime = pickAliasValue<string>(
    payload as Record<string, string | number | undefined>,
    layer.fieldAliases.observationTime,
  )

  const adaptedHotspots = (payload.hotspots ?? [])
    .map((hotspot) => {
      const hotspotValue = pickAliasValue<number | string>(hotspot, layer.fieldAliases.hotspotValue)
      if (hotspotValue === undefined) {
        availability.missingFields.push(`hotspot:${hotspot.name}`)
        return null
      }

      const numericValue = typeof hotspotValue === 'number' ? hotspotValue : Number(hotspotValue)

      return {
        id: hotspot.id,
        name: hotspot.name,
        lng: hotspot.lng,
        lat: hotspot.lat,
        value: formatHotspotValue(
          Number.isFinite(numericValue) ? numericValue : 0,
          layer.metricUnit,
          layer.metricPrecision,
        ),
      }
    })
    .filter((hotspot): hotspot is DemoLayer['hotspots'][number] => hotspot !== null)

  if (rawMetricValue === undefined) {
    availability.missingFields.push('metric')
  }
  if (rawStatusLabel === undefined) {
    availability.missingFields.push('status')
  }
  if (rawObservationTime === undefined) {
    availability.missingFields.push('time')
  }
  if (adaptedHotspots.length === 0) {
    availability.missingFields.push('hotspots')
  }

  return {
    metricValue:
      rawMetricValue === undefined
        ? '--'
        : formatMetricValue(Number(rawMetricValue), layer.metricUnit, layer.metricPrecision),
    statusLabel: rawStatusLabel ?? fallbackBand.statusLabel,
    observationTimeLabel: rawObservationTime ?? '--',
    hotspots: adaptedHotspots,
    missingFieldsLabel:
      availability.missingFields.length > 0 ? availability.missingFields.join(' / ') : '无缺失字段',
  }
}

function adaptBackendPayload(
  snapshot: BackendDemoSnapshot,
  availability: DemoAvailabilityProfile,
): Pick<DemoLayer, 'metricValue' | 'statusLabel' | 'observationTimeLabel' | 'hotspots' | 'missingFieldsLabel'> {
  const rawMetricValue = pickAliasValue<number>(
    snapshot.raw_payload as Record<string, string | number | undefined>,
    snapshot.field_aliases.metric_value,
  )
  const rawStatusLabel = pickAliasValue<string>(
    snapshot.raw_payload as Record<string, string | number | undefined>,
    snapshot.field_aliases.status_label,
  )
  const rawObservationTime = pickAliasValue<string>(
    snapshot.raw_payload as Record<string, string | number | undefined>,
    snapshot.field_aliases.observation_time,
  )

  const adaptedHotspots = (snapshot.raw_payload.hotspots ?? [])
    .map((hotspot) => {
      const hotspotValue = pickAliasValue<number | string>(hotspot, snapshot.field_aliases.hotspot_value)
      if (hotspotValue === undefined) {
        availability.missingFields.push(`hotspot:${hotspot.name}`)
        return null
      }

      const numericValue = typeof hotspotValue === 'number' ? hotspotValue : Number(hotspotValue)

      return {
        id: hotspot.id,
        name: hotspot.name,
        lng: hotspot.lng,
        lat: hotspot.lat,
        value: formatHotspotValue(
          Number.isFinite(numericValue) ? numericValue : 0,
          snapshot.metric_unit,
          snapshot.metric_precision,
        ),
      }
    })
    .filter((hotspot): hotspot is DemoLayer['hotspots'][number] => hotspot !== null)

  if (rawMetricValue === undefined) {
    availability.missingFields.push('metric')
  }
  if (rawStatusLabel === undefined) {
    availability.missingFields.push('status')
  }
  if (rawObservationTime === undefined) {
    availability.missingFields.push('time')
  }
  if (adaptedHotspots.length === 0) {
    availability.missingFields.push('hotspots')
  }

  return {
    metricValue:
      rawMetricValue === undefined
        ? '--'
        : formatMetricValue(Number(rawMetricValue), snapshot.metric_unit, snapshot.metric_precision),
    statusLabel: rawStatusLabel ?? snapshot.status_label,
    observationTimeLabel: rawObservationTime ?? '--',
    hotspots: adaptedHotspots,
    missingFieldsLabel:
      availability.missingFields.length > 0 ? availability.missingFields.join(' / ') : '无缺失字段',
  }
}

function resolveBand(layer: DemoLayerCatalogItem, hour: number) {
  const normalizedHour = normalizeHour(hour)
  return layer.timeBands.find((band) => bandMatches(normalizedHour, band)) ?? layer.timeBands[0]
}

export function resolveDemoLayer(layerId: string, hour: number): DemoLayer {
  const layer = demoLayerCatalog.find((item) => item.id === layerId) ?? demoLayerCatalog[0]
  const timeBand = resolveBand(layer, hour)
  const normalizedHour = normalizeHour(hour)
  const normalizedPhase = Math.sin((normalizedHour / 24) * Math.PI * 2 - Math.PI / 2)
  const availability = createAvailabilityProfile(timeBand.availabilityState)
  const rawPayload = createDemoRawPayload(layer, timeBand, normalizedHour, normalizedPhase)
  const adaptedPayload = adaptDemoPayload(layer, rawPayload, availability, timeBand)

  return {
    id: layer.id,
    name: layer.name,
    category: layer.category,
    summary: timeBand.summary,
    metricLabel: layer.metricLabel,
    metricValue: adaptedPayload.metricValue,
    trendLabel: timeBand.trendLabel,
    statusLabel: adaptedPayload.statusLabel,
    updateLabel: layer.updateLabel,
    sourceLabel: layer.sourceLabel,
    confidenceLabel: timeBand.confidenceLabel,
    accentColor: layer.accentColor,
    accentGlow: layer.accentGlow,
    chipTone: layer.chipTone,
    dataStateLabel: layer.dataState.label,
    availabilityState: availability.state,
    availabilityLabel: availability.label,
    availabilityDescription: availability.description,
    missingFieldsLabel: adaptedPayload.missingFieldsLabel,
    emptyStateLabel: layer.dataState.emptyLabel,
    fieldAliasLabel: layer.fieldAliases.metricValue.join(' / '),
    observationFieldLabel: layer.fieldAliases.observationTime.join(' / '),
    observationTimeLabel: adaptedPayload.observationTimeLabel,
    hotspots: adaptedPayload.hotspots,
  }
}

export function resolveDemoLayers(hour: number) {
  return demoLayerCatalog.map((layer) => resolveDemoLayer(layer.id, hour))
}

export function adaptBackendDemoSnapshot(snapshot: BackendDemoSnapshot): DemoLayer {
  const availability = createAvailabilityProfile(snapshot.availability_state)
  const adaptedPayload = adaptBackendPayload(snapshot, availability)

  return {
    id: snapshot.layer_id,
    name: snapshot.display_name,
    category: snapshot.category,
    summary: snapshot.summary,
    metricLabel: snapshot.metric_label,
    metricValue: adaptedPayload.metricValue,
    trendLabel: snapshot.trend_label,
    statusLabel: adaptedPayload.statusLabel,
    updateLabel: snapshot.update_label,
    sourceLabel: snapshot.source_label,
    confidenceLabel: snapshot.confidence_label,
    accentColor: snapshot.accent_color,
    accentGlow: snapshot.accent_glow,
    chipTone: snapshot.chip_tone,
    dataStateLabel: snapshot.data_state_label,
    availabilityState: availability.state,
    availabilityLabel: availability.label,
    availabilityDescription: availability.description,
    missingFieldsLabel: adaptedPayload.missingFieldsLabel,
    emptyStateLabel: snapshot.empty_state_label,
    fieldAliasLabel: snapshot.field_aliases.metric_value.join(' / '),
    observationFieldLabel: snapshot.field_aliases.observation_time.join(' / '),
    observationTimeLabel: adaptedPayload.observationTimeLabel,
    hotspots: adaptedPayload.hotspots,
  }
}

export function adaptBackendDemoSnapshots(response: BackendDemoSnapshotsResponse) {
  return response.items.map((item) => adaptBackendDemoSnapshot(item))
}
