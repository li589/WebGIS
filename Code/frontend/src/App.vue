<script setup lang="ts">
/**
 * App.vue — 应用根组件
 *
 * 挂载 RouterView + LoadingOverlay（hero 全屏地球卫星 / compact 顶栏）。
 * 由 useUiLoadingStore 驱动；组件内等待请用 InlineLoader。
 */
import LoadingOverlay from './components/LoadingOverlay.vue'
</script>

<template>
  <div class="page-shell">
    <RouterView />
    <LoadingOverlay />
  </div>
</template>
