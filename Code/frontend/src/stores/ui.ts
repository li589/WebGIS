import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export type MapMode = '2d' | '3d'

export const useUiStore = defineStore('ui', () => {
  const mapMode = ref<MapMode>('2d')
  const activeDataset = ref('风场')
  const currentHour = ref(12)

  const hourLabel = computed(() => `${String(currentHour.value).padStart(2, '0')}:00`)

  function setMode(mode: MapMode) {
    mapMode.value = mode
  }

  function setDataset(dataset: string) {
    activeDataset.value = dataset
  }

  function stepHour(delta: number) {
    const nextValue = currentHour.value + delta

    if (nextValue < 0) {
      currentHour.value = 23
      return
    }

    if (nextValue > 23) {
      currentHour.value = 0
      return
    }

    currentHour.value = nextValue
  }

  return {
    mapMode,
    activeDataset,
    currentHour,
    hourLabel,
    setMode,
    setDataset,
    stepHour,
  }
})
