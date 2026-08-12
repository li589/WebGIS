<script setup lang="ts">
/**
 * App.vue — 应用根组件
 *
 * 挂载 RouterView + LoadingOverlay（hero 全屏地球卫星 / compact 顶栏）。
 * 由 useUiLoadingStore 驱动；组件内等待请用 InlineLoader。
 * 激活 useThemeStore 以确保 data-theme 属性正确设置。
 */
import LoadingOverlay from './components/LoadingOverlay.vue'
import AppErrorBoundary from './components/AppErrorBoundary.vue'
import ServiceConnectivityBanner from './components/ServiceConnectivityBanner.vue'
import { useThemeStore } from './stores/theme'

// 激活主题 store：初始化时读取 localStorage/系统偏好并设置 data-theme
const themeStore = useThemeStore()
// 暴露到 window 供调试使用
if (typeof window !== 'undefined') {
  ;(window as any).__themeStore = themeStore
}
</script>

<template>
  <div class="page-shell">
    <ServiceConnectivityBanner />
    <AppErrorBoundary>
      <RouterView />
    </AppErrorBoundary>
    <LoadingOverlay />
  </div>
</template>
