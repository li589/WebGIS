/**
 * auth-api.ts 契约测试：每个端点包装器的 path / method / body / options 断言。
 * 关键安全语义：敏感读必须带 sensitiveGet；登出/删除类必须 allowEmpty。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const requestJsonMock = vi.fn()

vi.mock('@/services/_http', () => ({
  requestJson: (...args: unknown[]) => requestJsonMock(...args),
}))

import {
  createAuthToken,
  createUser,
  deletePermission,
  deleteUser,
  fetchAuthConfig,
  fetchAuthMe,
  listAuthTokens,
  listUserPermissions,
  listUsers,
  loginRequest,
  logoutRequest,
  revokeAuthToken,
  setUserPermissions,
  updatePermissionMode,
  updateUser,
} from '@/services/auth-api'

describe('auth-api', () => {
  beforeEach(() => {
    requestJsonMock.mockReset()
    requestJsonMock.mockResolvedValue(undefined)
  })

  it.each([
    ['fetchAuthConfig', fetchAuthConfig, '/auth/config', { silent: true }],
    ['fetchAuthMe', fetchAuthMe, '/auth/me', { silent: true }],
    ['listUsers', listUsers, '/auth/users', { sensitiveGet: true }],
    ['listAuthTokens', listAuthTokens, '/auth/tokens', { sensitiveGet: true }],
  ] as const)('%s GETs %s', async (_name, fn, path, options) => {
    await fn()
    expect(requestJsonMock).toHaveBeenCalledWith(path, options)
  })

  it('loginRequest POSTs credentials', async () => {
    await loginRequest('alice', 'secret')
    expect(requestJsonMock).toHaveBeenCalledWith('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username: 'alice', password: 'secret' }),
    })
  })

  it('logoutRequest POSTs with allowEmpty', async () => {
    await logoutRequest()
    expect(requestJsonMock).toHaveBeenCalledWith('/auth/logout', {
      method: 'POST',
      allowEmpty: true,
    })
  })

  it('createUser POSTs user payload', async () => {
    await createUser({ username: 'bob', password: 'pw', role: 'standard' })
    expect(requestJsonMock).toHaveBeenCalledWith('/auth/users', {
      method: 'POST',
      body: JSON.stringify({ username: 'bob', password: 'pw', role: 'standard' }),
    })
  })

  it('updateUser PATCHes by numeric id', async () => {
    await updateUser(7, { role: 'admin' })
    expect(requestJsonMock).toHaveBeenCalledWith('/auth/users/7', {
      method: 'PATCH',
      body: JSON.stringify({ role: 'admin' }),
    })
  })

  it('deleteUser DELETEs with allowEmpty', async () => {
    await deleteUser(7)
    expect(requestJsonMock).toHaveBeenCalledWith('/auth/users/7', {
      method: 'DELETE',
      allowEmpty: true,
    })
  })

  it('createAuthToken POSTs token body', async () => {
    await createAuthToken({ label: 'ci' })
    expect(requestJsonMock).toHaveBeenCalledWith('/auth/tokens', {
      method: 'POST',
      body: JSON.stringify({ label: 'ci' }),
    })
  })

  it('revokeAuthToken DELETEs with allowEmpty', async () => {
    await revokeAuthToken(42)
    expect(requestJsonMock).toHaveBeenCalledWith('/auth/tokens/42', {
      method: 'DELETE',
      allowEmpty: true,
    })
  })

  it('listUserPermissions GETs with sensitiveGet', async () => {
    await listUserPermissions(7)
    expect(requestJsonMock).toHaveBeenCalledWith('/auth/users/7/permissions', {
      sensitiveGet: true,
    })
  })

  it('setUserPermissions PUTs permissions envelope', async () => {
    const permissions = [
      { resource_type: 'layer', resource_id: 'ndvi', permission: 'read' },
    ] as never
    await setUserPermissions(7, permissions)
    expect(requestJsonMock).toHaveBeenCalledWith('/auth/users/7/permissions', {
      method: 'PUT',
      body: JSON.stringify({ permissions }),
    })
  })

  it('deletePermission DELETEs with allowEmpty', async () => {
    await deletePermission(7, 99)
    expect(requestJsonMock).toHaveBeenCalledWith('/auth/users/7/permissions/99', {
      method: 'DELETE',
      allowEmpty: true,
    })
  })

  it('updatePermissionMode PATCHes mode', async () => {
    await updatePermissionMode(7, 'whitelist')
    expect(requestJsonMock).toHaveBeenCalledWith('/auth/users/7/permission-mode', {
      method: 'PATCH',
      body: JSON.stringify({ mode: 'whitelist' }),
    })
  })

  it('propagates requestJson rejection', async () => {
    requestJsonMock.mockRejectedValueOnce(new Error('boom'))
    await expect(fetchAuthMe()).rejects.toThrow('boom')
  })
})
