<script setup lang="ts">
/**
 * App.vue — 应用根组件
 *
 * 挂载全局 RouterView 和 LoadingOverlay（等高线波纹加载动效）。
 * LoadingOverlay 由 useUiLoadingStore 驱动，无需手动控制。
 */
import LoadingOverlay from './components/LoadingOverlay.vue'
</script>

<template>
  <div class="page-shell">
    <RouterView />
    <LoadingOverlay />
  </div>
</template>
