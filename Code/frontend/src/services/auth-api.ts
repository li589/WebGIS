import type { components } from '../types/api-contracts'
import { requestJson } from './_http'

export type AuthConfig = components['schemas']['AuthConfigResponse']
export type AuthUser = components['schemas']['UserPublic']
export type UserRole = AuthUser['role']
export type AuthToken = components['schemas']['TokenPublic']
export type AuthTokenCreated = components['schemas']['TokenCreatedResponse']

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
}): Promise<AuthUser> {
  return requestJson<AuthUser>('/auth/users', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function updateUser(
  userId: number,
  body: { password?: string; role?: UserRole; enabled?: boolean },
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
