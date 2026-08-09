import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '../stores/auth'
import { safeRedirect } from './safe-redirect'
import { EXTRA_ROUTES, NOT_FOUND_ROUTE, SPA_ROUTES } from './route-paths'

export { safeRedirect }

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
      component: () => import('../views/DashboardView.vue'),
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
  return true
})
