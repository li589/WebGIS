import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '../stores/auth'
import { safeRedirect } from './safe-redirect'
import { EXTRA_ROUTES, NOT_FOUND_ROUTE, SPA_ROUTES } from './route-paths'

export { safeRedirect }

/** SPA 业务路由 → 视图组件（懒加载）。未列出的路由名回退 Dashboard。 */
const ROUTE_VIEWS: Record<string, () => Promise<typeof import('../views/DashboardView.vue')>> = {
  dashboard: () => import('../views/DashboardView.vue'),
  'deployment-config': () => import('../views/DeploymentConfigView.vue'),
}

/** 路由级 meta（当前仅 requiresAdmin：UX 层守卫，后端 API 才是安全边界）。 */
const ROUTE_META: Record<string, { requiresAdmin?: boolean }> = {
  'deployment-config': { requiresAdmin: true },
}

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: EXTRA_ROUTES[0].path, // /login
      name: EXTRA_ROUTES[0].name,
      component: () => import('../views/LoginView.vue'),
      meta: { public: true },
    },
    // SPA 业务路由由 route-paths.ts 单一真源驱动：新增页面只需登记 SPA_ROUTES，
    // safeRedirect 白名单（SPA_PATHS）随之同步，避免登录重定向白名单漏配。
    ...SPA_ROUTES.map((route) => ({
      path: route.path,
      name: route.name,
      component: ROUTE_VIEWS[route.name] ?? (() => import('../views/DashboardView.vue')),
      meta: ROUTE_META[route.name],
    })),
    {
      path: NOT_FOUND_ROUTE.path, // /:pathMatch(.*)*
      name: NOT_FOUND_ROUTE.name,
      component: () => import('../views/NotFoundView.vue'),
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.bootstrapped) {
    await auth.bootstrap()
  }
  if (to.name === 'login') {
    if (auth.isAuthenticated) return { path: '/' }
    return true
  }
  if (auth.authRequired && !auth.isAuthenticated) {
    const redirect = typeof to.fullPath === 'string' ? safeRedirect(to.fullPath) : '/'
    return { name: 'login', query: { redirect } }
  }
  // admin 专属页（如 /deployment）：UX 层拦截非 admin；后端 API 鉴权为安全边界。
  if (to.meta.requiresAdmin && auth.bootstrapped && !auth.isAdmin) {
    return { path: '/' }
  }
  return true
})
