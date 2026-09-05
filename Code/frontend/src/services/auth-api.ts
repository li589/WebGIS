import type { components } from '../types/api-contracts'
import { requestJson, resolveApiUrl } from './_http'

export type AuthConfig = components['schemas']['AuthConfigResponse']
export type UserRole = 'admin' | 'standard' | 'demo'
export type AuthToken = components['schemas']['TokenPublic']
export type AuthTokenCreated = components['schemas']['TokenCreatedResponse']

/** 登录页氛围色（仅 LoginView；与应用内主题无关） */
export type LoginPalette = 'cyan' | 'green' | 'warm' | 'violet' | 'slate'

/** Product theme branding + default ACL metadata (matches ThemePublic). */
export type ThemePublic = {
  id: number
  slug: string
  name_zh: string
  full_name_zh: string
  name_en: string
  abbr: string
  description?: string
  logo_url?: string | null
  default_permission_mode?: string
  is_primary?: boolean
  login_palette?: LoginPalette | string
}

export type ThemePublicBrand = {
  id: number
  slug: string
  name_zh: string
  full_name_zh: string
  name_en: string
  abbr: string
  description?: string
  logo_url?: string | null
  login_palette?: LoginPalette | string
}

export type AuthUser = {
  id: number
  username: string
  role: UserRole
  enabled: boolean
  permission_mode?: string
  theme_id?: number | null
  theme?: ThemePublic | null
}

export type ThemePermissionRecord = {
  id: number
  theme_id: number
  resource_type: string
  resource_id: string
  permission: string
  created_at: string
  updated_at: string
}

export function fetchAuthConfig(): Promise<AuthConfig> {
  return requestJson<AuthConfig>('/auth/config', { silent: true })
}

export function fetchAuthMe(): Promise<AuthUser> {
  return requestJson<AuthUser>('/auth/me', { silent: true })
}

export function loginRequest(username: string, password: string): Promise<AuthUser> {
  return requestJson<AuthUser>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
}

export function logoutRequest(): Promise<void> {
  return requestJson<void>('/auth/logout', { method: 'POST', allowEmpty: true })
}

export function listUsers(): Promise<AuthUser[]> {
  return requestJson<AuthUser[]>('/auth/users', { sensitiveGet: true })
}

export function createUser(body: {
  username: string
  password: string
  role: UserRole
  theme_id?: number | null
}): Promise<AuthUser> {
  return requestJson<AuthUser>('/auth/users', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function updateUser(
  userId: number,
  body: {
    password?: string
    role?: UserRole
    enabled?: boolean
    /** Omit to leave unchanged; never send null (backend 422). */
    theme_id?: number
  },
): Promise<AuthUser> {
  return requestJson<AuthUser>(`/auth/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export function deleteUser(userId: number): Promise<void> {
  return requestJson<void>(`/auth/users/${userId}`, {
    method: 'DELETE',
    allowEmpty: true,
  })
}

export function listAuthTokens(): Promise<AuthToken[]> {
  return requestJson<AuthToken[]>('/auth/tokens', { sensitiveGet: true })
}

export function createAuthToken(body: {
  label?: string
  user_id?: number
}): Promise<AuthTokenCreated> {
  return requestJson<AuthTokenCreated>('/auth/tokens', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function revokeAuthToken(tokenId: number): Promise<void> {
  return requestJson<void>(`/auth/tokens/${tokenId}`, {
    method: 'DELETE',
    allowEmpty: true,
  })
}

// --- Phase B: Resource permissions ---

export type PermissionRecord = components['schemas']['PermissionRecord']
export type PermissionItemInput = components['schemas']['PermissionItemInput']
export type ResourceType = PermissionItemInput['resource_type']
export type PermissionValue = PermissionItemInput['permission']
export type PermissionMode = 'open' | 'whitelist'

export function listUserPermissions(userId: number): Promise<PermissionRecord[]> {
  return requestJson<PermissionRecord[]>(`/auth/users/${userId}/permissions`, {
    sensitiveGet: true,
  })
}

export function setUserPermissions(
  userId: number,
  permissions: PermissionItemInput[],
): Promise<PermissionRecord[]> {
  return requestJson<PermissionRecord[]>(`/auth/users/${userId}/permissions`, {
    method: 'PUT',
    body: JSON.stringify({ permissions }),
  })
}

export function deletePermission(userId: number, permissionId: number): Promise<void> {
  return requestJson<void>(`/auth/users/${userId}/permissions/${permissionId}`, {
    method: 'DELETE',
    allowEmpty: true,
  })
}

export function updatePermissionMode(
  userId: number,
  mode: PermissionMode,
): Promise<{ user_id: number; permission_mode: string }> {
  return requestJson<{ user_id: number; permission_mode: string }>(
    `/auth/users/${userId}/permission-mode`,
    {
      method: 'PATCH',
      body: JSON.stringify({ mode }),
    },
  )
}

// --- Themes ---

export function fetchPrimaryThemePublic(): Promise<ThemePublicBrand> {
  return requestJson<ThemePublicBrand>('/auth/themes/primary/public', { silent: true })
}

export function fetchThemesPublic(): Promise<ThemePublicBrand[]> {
  return requestJson<ThemePublicBrand[]>('/auth/themes/public', { silent: true })
}

export function listThemes(): Promise<ThemePublic[]> {
  return requestJson<ThemePublic[]>('/auth/themes', { sensitiveGet: true })
}

export function createTheme(body: {
  slug: string
  name_zh: string
  full_name_zh: string
  name_en: string
  abbr: string
  description?: string
  default_permission_mode?: PermissionMode
  is_primary?: boolean
  login_palette?: LoginPalette | null
}): Promise<ThemePublic> {
  return requestJson<ThemePublic>('/auth/themes', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function updateTheme(
  themeId: number,
  body: {
    name_zh?: string
    full_name_zh?: string
    name_en?: string
    abbr?: string
    description?: string
    default_permission_mode?: PermissionMode
    is_primary?: boolean
    login_palette?: LoginPalette | null
  },
): Promise<ThemePublic> {
  return requestJson<ThemePublic>(`/auth/themes/${themeId}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export function deleteTheme(themeId: number): Promise<void> {
  return requestJson<void>(`/auth/themes/${themeId}`, {
    method: 'DELETE',
    allowEmpty: true,
  })
}

export function listThemePermissions(themeId: number): Promise<ThemePermissionRecord[]> {
  return requestJson<ThemePermissionRecord[]>(`/auth/themes/${themeId}/permissions`, {
    sensitiveGet: true,
  })
}

export function setThemePermissions(
  themeId: number,
  permissions: PermissionItemInput[],
): Promise<ThemePermissionRecord[]> {
  return requestJson<ThemePermissionRecord[]>(`/auth/themes/${themeId}/permissions`, {
    method: 'PUT',
    body: JSON.stringify({ permissions }),
  })
}

export async function uploadThemeLogo(themeId: number, file: File): Promise<ThemePublic> {
  const form = new FormData()
  form.append('file', file)
  const { applyApiFetchDefaults } = await import('./http-credentials')
  const resp = await fetch(
    resolveApiUrl(`/auth/themes/${themeId}/logo`),
    applyApiFetchDefaults({ method: 'POST', body: form }),
  )
  if (!resp.ok) {
    const text = await resp.text()
    throw new Error(text || `Upload failed (${resp.status})`)
  }
  return resp.json() as Promise<ThemePublic>
}
