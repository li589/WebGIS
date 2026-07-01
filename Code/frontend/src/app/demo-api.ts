import {
  adaptBackendDemoSnapshot,
  adaptBackendDemoSnapshots,
  type BackendDemoSnapshot,
  type BackendDemoSnapshotsResponse,
} from './demo-adapter'

function getApiBaseUrl() {
  return import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? 'http://127.0.0.1:8000'
}

export async function fetchDemoSnapshot(layerId: string, hour: number) {
  const response = await fetch(`${getApiBaseUrl()}/demo/layers/${layerId}/snapshot?hour=${hour}`)
  if (!response.ok) {
    throw new Error(`Failed to fetch demo snapshot: ${response.status}`)
  }

  const payload = (await response.json()) as BackendDemoSnapshot
  return adaptBackendDemoSnapshot(payload)
}

export async function fetchDemoSnapshots(hour: number) {
  const response = await fetch(`${getApiBaseUrl()}/demo/layers/snapshots?hour=${hour}`)
  if (!response.ok) {
    throw new Error(`Failed to fetch demo snapshots: ${response.status}`)
  }

  const payload = (await response.json()) as BackendDemoSnapshotsResponse
  return adaptBackendDemoSnapshots(payload)
}
