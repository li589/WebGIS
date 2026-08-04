/**
 * Client write-auth for mutating backend endpoints (X-Api-Key).
 * 密钥来源：仅 localStorage（操作员在设置页运行时写入）。
 * 发布就绪修复（P1-1）：已移除 VITE_BACKEND_API_KEY 构建期内联路径——内联会把写密钥
 * 打进分发给所有客户端的 JS bundle，任何拿到 bundle 的人都能提取它发起写操作。
 */

import {
  clearLocalWriteApiKey,
  getLocalWriteApiKey,
  hasLocalWriteApiKey,
  setLocalWriteApiKey,
} from './settings-local'

export function getBackendWriteApiKey(): string | null {
  // P1-1：不再回落 VITE_BACKEND_API_KEY（构建期内联 = 密钥泄露进 bundle）。
  return getLocalWriteApiKey()
}

export function setBackendWriteApiKey(key: string | null): void {
  setLocalWriteApiKey(key)
}

export function clearBackendWriteApiKey(): void {
  clearLocalWriteApiKey()
}

export function hasBackendWriteApiKey(): boolean {
  // P1-1：仅看运行时 localStorage，不再看构建期内联 env。
  return hasLocalWriteApiKey()
}

/** Attach X-Api-Key for mutating requests when a write key is available. */
export function withWriteAuthHeaders(
  headers: Record<string, string> = {},
  method = 'GET',
): Record<string, string> {
  const upper = method.toUpperCase()
  if (upper === 'GET' || upper === 'HEAD' || upper === 'OPTIONS') {
    return headers
  }
  const key = getBackendWriteApiKey()
  if (!key) return headers
  return { ...headers, 'X-Api-Key': key }
}
