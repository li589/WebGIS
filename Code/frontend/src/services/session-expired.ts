import { safeRedirect, isBackendApiPath } from '../app/safe-redirect'
import { useAuthStore } from '../stores/auth'

let redirecting = false

/** Clear local session without calling logout API (avoids 401 loops). */
export function clearLocalSession(): void {
  useAuthStore().clearSession()
}

export function handleSessionExpired(redirectPath?: string): void {
  if (redirecting) return
  redirecting = true
  clearLocalSession()

  const fallback =
    typeof window !== 'undefined' ? `${window.location.pathname}${window.location.search}` : '/'
  let candidate = redirectPath ?? fallback
  const candidatePath = candidate.split('?')[0] ?? candidate
  if (isBackendApiPath(candidatePath) || candidatePath === '/login') {
    candidate = fallback === '/login' || fallback.startsWith('/login?') ? '/' : fallback
  }
  const redirect = safeRedirect(candidate)

  void import('../app/router')
    .then(({ router }) => router.replace({ name: 'login', query: { redirect } }))
    .finally(() => {
      redirecting = false
    })
}

export function isAuthBootstrapPath(path: string): boolean {
  const normalized = path.split('?')[0] ?? path
  return (
    normalized === '/auth/login' ||
    normalized === '/auth/config' ||
    normalized === '/auth/me' ||
    normalized === '/auth/logout'
  )
}
