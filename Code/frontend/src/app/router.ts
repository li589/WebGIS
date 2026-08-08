import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '../stores/auth'
import { safeRedirect } from './safe-redirect'

export { safeRedirect }

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      name: 'dashboard',
      component: () => import('../views/DashboardView.vue'),
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
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
