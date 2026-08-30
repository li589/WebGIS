/**
 * Shared map inspect point for Agent client_context (and other consumers).
 * Written by useMapInspect; read by AgentChatPanel.
 */
import { ref, readonly } from 'vue'

const mapPointRef = ref<{ lng: number; lat: number } | null>(null)

export function setAgentMapPoint(point: { lng: number; lat: number } | null) {
  if (
    point &&
    Number.isFinite(point.lng) &&
    Number.isFinite(point.lat) &&
    point.lng >= -180 &&
    point.lng <= 180 &&
    point.lat >= -90 &&
    point.lat <= 90
  ) {
    mapPointRef.value = {
      lng: Number(point.lng.toFixed(6)),
      lat: Number(point.lat.toFixed(6)),
    }
    return
  }
  mapPointRef.value = null
}

export const agentMapPoint = readonly(mapPointRef)
