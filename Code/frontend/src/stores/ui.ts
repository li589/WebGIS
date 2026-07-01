import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { resolveDemoLayer } from '../app/demo-adapter'
import { demoLayerCatalog, type DemoLayer } from '../app/demo-data'
export type BasemapMode = 'admin' | 'osm' | 'hybrid'

function readStoredValue<T extends string>(key: string, fallback: T): T {
  if (typeof window === 'undefined') {
    return fallback
  }

  const value = window.localStorage.getItem(key)
  return (value as T | null) ?? fallback
}

function writeStoredValue(key: string, value: string) {
  if (typeof window === 'undefined') {
    return
  }

  window.localStorage.setItem(key, value)
}

function normalizeHour(value: number) {
  const wrappedHour = ((value % 24) + 24) % 24
  return Math.round(wrappedHour * 100) / 100
}

function formatHourLabel(hour: number) {
  const wholeHours = Math.floor(hour)
  const minutes = Math.round((hour - wholeHours) * 60)
  const normalizedMinutes = minutes === 60 ? 0 : minutes
  const normalizedHours = minutes === 60 ? (wholeHours + 1) % 24 : wholeHours

  return `${String(normalizedHours).padStart(2, '0')}:${String(normalizedMinutes).padStart(2, '0')}`
}

export const useUiStore = defineStore('ui', () => {
  const basemapMode = ref<BasemapMode>(readStoredValue<BasemapMode>('ui:basemap-mode', 'admin'))
  const activeLayerId = ref(readStoredValue<string>('ui:active-layer-id', demoLayerCatalog[0].id))
  const currentHour = ref(normalizeHour(Number(readStoredValue<string>('ui:hour', '12'))))

  const hourLabel = computed(() => formatHourLabel(currentHour.value))
  const activeLayer = computed<DemoLayer>(() => resolveDemoLayer(activeLayerId.value, currentHour.value))

  function setBasemap(mode: BasemapMode) {
    basemapMode.value = mode
    writeStoredValue('ui:basemap-mode', mode)
  }

  function setLayer(layerId: string) {
    activeLayerId.value = layerId
    writeStoredValue('ui:active-layer-id', layerId)
  }

  function setHour(nextHour: number) {
    const wrappedHour = normalizeHour(nextHour)
    currentHour.value = wrappedHour
    writeStoredValue('ui:hour', String(wrappedHour))
  }

  function stepHour(delta: number) {
    setHour(currentHour.value + delta)
  }

  return {
    basemapMode,
    activeLayerId,
    activeLayer,
    currentHour,
    hourLabel,
    setBasemap,
    setLayer,
    setHour,
    stepHour,
  }
})
