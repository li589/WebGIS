/** Backend API path prefixes — not valid SPA routes; must not be used as post-login redirects. */
const BACKEND_PATH_PREFIXES = [
  '/config',
  '/auth',
  '/runtime',
  '/workflow-runs',
  '/workflow-definitions',
  '/workflow-node-templates',
  '/workflow-timers',
  '/cleanup',
  '/layers',
  '/weather',
  '/artifacts',
  '/gee',
  '/system',
  '/provider',
  '/frontend',
  '/unified-tiles',
  '/overlay-tiles',
  '/overlay-preview',
  '/overlay-bounds',
  '/overlay-value',
  '/overlays',
  '/import',
  '/export',
  '/health',
  '/docs',
  '/redoc',
  '/openapi.json',
] as const

/** SPA routes that exist besides `/` (login is rejected to avoid loops). */
const SPA_PATHS = new Set(['/'])

export function isBackendApiPath(pathOnly: string): boolean {
  if (!pathOnly || pathOnly === '/') return false
  return BACKEND_PATH_PREFIXES.some(
    (prefix) => pathOnly === prefix || pathOnly.startsWith(`${prefix}/`),
  )
}

/** Prevent open-redirect via login `?redirect=` query. */
export function safeRedirect(raw: string | undefined): string {
  if (!raw || typeof raw !== 'string') return '/'

  let path = raw.trim()
  if (!path.startsWith('/') || path.startsWith('//')) return '/'

  // Reject encoded slash tricks before decode.
  if (/%2f/i.test(path)) return '/'

  try {
    path = decodeURIComponent(path)
  } catch {
    return '/'
  }

  if (!path.startsWith('/') || path.startsWith('//')) return '/'
  if (path === '/login' || path.startsWith('/login?') || path.startsWith('/login/')) {
    return '/'
  }

  const [pathOnly, query = ''] = path.split('?', 2)
  if (isBackendApiPath(pathOnly)) return '/'
  if (!SPA_PATHS.has(pathOnly)) return '/'

  return query ? `${pathOnly}?${query}` : pathOnly
}
