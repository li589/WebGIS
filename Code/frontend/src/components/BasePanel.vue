<script setup lang="ts">
defineProps<{
  as?: string
}>()
</script>

<template>
  <component :is="as ?? 'section'" class="base-panel">
    <slot />
  </component>
</template>

<style scoped>
.base-panel {
  position: relative;
  border: 1px solid rgba(155, 180, 210, 0.18);
  border-radius: 1rem;
  background:
    linear-gradient(180deg, rgba(18, 28, 46, 0.66), rgba(8, 15, 28, 0.48)),
    radial-gradient(circle at top left, rgba(255, 255, 255, 0.1), transparent 34%),
    radial-gradient(circle at bottom right, rgba(90, 162, 255, 0.08), transparent 42%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.1),
    inset 0 -1px 0 rgba(255, 255, 255, 0.035),
    0 16px 34px rgba(1, 8, 16, 0.15);
  box-sizing: border-box;
  overflow: hidden;
  backdrop-filter: blur(14px) saturate(1.08);
  -webkit-backdrop-filter: blur(14px) saturate(1.08);
  contain: layout paint;
}

@media (prefers-reduced-motion: reduce) {
  .base-panel {
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}
</style>
