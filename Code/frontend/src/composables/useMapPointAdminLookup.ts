import { ref, watch, type Ref } from 'vue'
import { extractAdminLabelsAt } from '../services/basemap-extract'

export type MapPointAdminLookupState = 'idle' | 'loading' | 'ready' | 'miss'

export interface MapPointAdminLabel {
  state: MapPointAdminLookupState
  adminLine: string
  stateName: string | null
  countryName: string | null
}

export function formatMapPointAdminLine(
  state: MapPointAdminLookupState,
  stateName: string | null,
  countryName: string | null,
): string {
  if (state === 'loading') return '正在解析行政区…'
  if (state === 'miss') return '行政区未命中'
  const parts: string[] = []
  if (stateName) parts.push(`${stateName}（省/州）`)
  if (countryName) parts.push(`${countryName}（国家）`)
  if (parts.length === 0) return '行政区未命中'
  return parts.join(' / ')
}

export function useMapPointAdminLookup(
  selectedMapPoint: Ref<{ lng: number; lat: number } | null>,
  enabled: Ref<boolean>,
  debounceMs = 200,
) {
  const label = ref<MapPointAdminLabel>({
    state: 'idle',
    adminLine: '',
    stateName: null,
    countryName: null,
  })

  let timer: ReturnType<typeof setTimeout> | null = null
  let requestId = 0

  async function lookup(lng: number, lat: number, id: number) {
    label.value = {
      state: 'loading',
      adminLine: formatMapPointAdminLine('loading', null, null),
      stateName: null,
      countryName: null,
    }
    try {
      const { stateName, countryName } = await extractAdminLabelsAt(lng, lat)
      if (id !== requestId) return
      if (!stateName && !countryName) {
        label.value = {
          state: 'miss',
          adminLine: formatMapPointAdminLine('miss', null, null),
          stateName: null,
          countryName: null,
        }
        return
      }
      label.value = {
        state: 'ready',
        adminLine: formatMapPointAdminLine('ready', stateName, countryName),
        stateName,
        countryName,
      }
    } catch {
      if (id !== requestId) return
      label.value = {
        state: 'miss',
        adminLine: formatMapPointAdminLine('miss', null, null),
        stateName: null,
        countryName: null,
      }
    }
  }

  watch(
    [selectedMapPoint, enabled],
    ([point, on]) => {
      if (timer) clearTimeout(timer)
      requestId += 1
      if (!on || !point) {
        label.value = {
          state: 'idle',
          adminLine: '',
          stateName: null,
          countryName: null,
        }
        return
      }
      const { lng, lat } = point
      const id = requestId
      timer = setTimeout(() => {
        void lookup(lng, lat, id)
      }, debounceMs)
    },
    { immediate: true },
  )

  return { label }
}
