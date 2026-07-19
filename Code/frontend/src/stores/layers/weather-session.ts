/**
 * Weather session helpers extracted from the layers god store.
 * Catalog authority remains backend `/layers`; static whitelist is safe fallback only.
 */
import { isWeatherLayerDescriptor } from '../../services/layer-capabilities'
import type { RuntimeLayerDescriptor } from '../../services/runtime-api'
import { LAYER_LIBRARY, WEATHER_ENGINE_CATALOG_IDS } from './catalog'

export function isWeatherEngineCatalogId(
  catalogId: string,
  descriptor: RuntimeLayerDescriptor | null | undefined,
): boolean {
  if (descriptor) {
    return isWeatherLayerDescriptor(descriptor)
  }
  const staticItem = LAYER_LIBRARY.find((item) => item.catalogId === catalogId)
  if (staticItem?.category === '气象场') {
    return true
  }
  return WEATHER_ENGINE_CATALOG_IDS.has(catalogId)
}
