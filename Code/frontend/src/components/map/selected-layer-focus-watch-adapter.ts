import type { ActiveLayerDisplay } from '../../stores/layers/types'

export interface SelectedLayerFocusWatchInputs {
  instanceId: string | null
  hotspotsHash: string
}

export interface SelectedLayerFocusWatchDiff {
  instanceChanged: boolean
  hotspotsChanged: boolean
}

export function buildSelectedLayerFocusWatchInputs(
  selectedLayer: ActiveLayerDisplay | null | undefined,
): SelectedLayerFocusWatchInputs {
  return {
    instanceId: selectedLayer?.instanceId ?? null,
    hotspotsHash: (selectedLayer?.hotspots ?? [])
      .map((hotspot) => `${hotspot.id}:${hotspot.lng}:${hotspot.lat}:${hotspot.value}`)
      .join('|'),
  }
}

export function diffSelectedLayerFocusWatchInputs(
  next: SelectedLayerFocusWatchInputs,
  previous?: SelectedLayerFocusWatchInputs,
): SelectedLayerFocusWatchDiff {
  return {
    instanceChanged: next.instanceId !== previous?.instanceId,
    hotspotsChanged: next.hotspotsHash !== previous?.hotspotsHash,
  }
}
