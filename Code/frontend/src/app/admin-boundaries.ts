/**
 * Built-in administrative boundary datasets (lazy-loaded).
 *
 * Natural Earth 10m admin-1 (states/provinces) + admin-0 (countries fallback).
 * Static files under /data/boundaries/ (see Tools/build_world_admin_boundaries.py).
 */

export const ADMIN_BOUNDARY_ASSETS = {
  worldAdmin1: '/data/boundaries/world-admin-1.geojson',
  worldAdmin0: '/data/boundaries/world-admin-0.geojson',
} as const

let worldAdmin1Cache: GeoJSON.FeatureCollection | null = null
let worldAdmin0Cache: GeoJSON.FeatureCollection | null = null
let worldAdmin1Promise: Promise<GeoJSON.FeatureCollection> | null = null
let worldAdmin0Promise: Promise<GeoJSON.FeatureCollection> | null = null

async function fetchGeoJson(url: string): Promise<GeoJSON.FeatureCollection> {
  const resp = await fetch(url)
  if (!resp.ok) {
    throw new Error(`行政区边界数据加载失败（${resp.status}）`)
  }
  const data = (await resp.json()) as GeoJSON.FeatureCollection
  if (data.type !== 'FeatureCollection' || !Array.isArray(data.features)) {
    throw new Error('行政区边界数据格式无效')
  }
  return data
}

export async function loadWorldAdmin1Boundaries(): Promise<GeoJSON.FeatureCollection> {
  if (worldAdmin1Cache) return worldAdmin1Cache
  if (!worldAdmin1Promise) {
    worldAdmin1Promise = fetchGeoJson(ADMIN_BOUNDARY_ASSETS.worldAdmin1).then((data) => {
      worldAdmin1Cache = data
      return data
    })
  }
  return worldAdmin1Promise
}

export async function loadWorldAdmin0Boundaries(): Promise<GeoJSON.FeatureCollection> {
  if (worldAdmin0Cache) return worldAdmin0Cache
  if (!worldAdmin0Promise) {
    worldAdmin0Promise = fetchGeoJson(ADMIN_BOUNDARY_ASSETS.worldAdmin0).then((data) => {
      worldAdmin0Cache = data
      return data
    })
  }
  return worldAdmin0Promise
}

/** Map overlay：全球省/州级边界（Natural Earth admin-1） */
export async function loadAdminBoundaryOverlay(): Promise<GeoJSON.FeatureCollection> {
  return loadWorldAdmin1Boundaries()
}
