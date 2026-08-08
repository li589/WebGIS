/** Shared fetch defaults for session cookie auth. */
export const API_FETCH_CREDENTIALS: RequestCredentials = 'include'

export function applyApiFetchDefaults(init?: RequestInit): RequestInit {
  return {
    ...init,
    credentials: init?.credentials ?? API_FETCH_CREDENTIALS,
  }
}
