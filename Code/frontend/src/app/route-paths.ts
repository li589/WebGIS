/**
 * SPA 路由定义（单一真源）。
 *
 * router.ts 与 safe-redirect.ts 共用本模块，避免「新增路由后忘记同步登录
 * 重定向白名单」导致的回归：白名单路径集由本模块动态推导，路由与白名单
 * 必然一致（auth-router.test.ts 有运行时一致性断言兜底）。
 */

export const SPA_ROUTES = [
  { path: '/', name: 'dashboard' },
  { path: '/deployment', name: 'deployment-config' },
] as const

export const LOGIN_ROUTE = { path: '/login', name: 'login' } as const
export const NOT_FOUND_ROUTE = { path: '/:pathMatch(.*)*', name: 'not-found' } as const

/** 可作为登录后重定向目标的 SPA 路径集合（不含 /login 与通配 404 路由）。 */
export const SPA_PATHS: ReadonlySet<string> = new Set(SPA_ROUTES.map((r) => r.path))

/** 除 SPA_ROUTES 外 router 实际注册的其余路由（login / not-found）。 */
export const EXTRA_ROUTES = [LOGIN_ROUTE, NOT_FOUND_ROUTE] as const
