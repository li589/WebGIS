/**
 * Weather model id helpers shared by settings / tile-manager / coverage probes.
 * Bootstrap must stay a concrete domain (never best_match/auto) so local Open-Meteo works.
 */
export const WEATHER_MODEL_BOOTSTRAP = 'ecmwf_ifs025'

/** Normalize UI / API model ids; map ensemble aliases to the local bootstrap domain. */
export function normalizeWeatherModel(raw?: string | null): string {
  const trimmed = (raw || '').trim()
  if (!trimmed || trimmed === 'best_match' || trimmed === 'auto') {
    return WEATHER_MODEL_BOOTSTRAP
  }
  return trimmed
}
