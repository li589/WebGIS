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

  return path
}
