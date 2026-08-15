<script setup lang="ts">
/**
 * SGFS 品牌 Logo — 卫星轨道 + 星地波束 + 土壤水滴 + 分层土壤。
 * 彩色版本与 public/favicon.svg 同源；工具栏 / 登录页共用。
 */
withDefaults(
  defineProps<{
    size?: number
  }>(),
  { size: 48 },
)
</script>

<template>
  <svg
    class="brand-mark"
    :width="size"
    :height="size"
    viewBox="0 0 64 64"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    role="img"
    aria-label="SGFS"
  >
    <defs>
      <linearGradient id="bmBg" x1="8" y1="6" x2="56" y2="58" gradientUnits="userSpaceOnUse">
        <stop stop-color="#071422" />
        <stop offset="1" stop-color="#0b1f33" />
      </linearGradient>
      <linearGradient id="bmOrbit" x1="10" y1="12" x2="52" y2="30" gradientUnits="userSpaceOnUse">
        <stop stop-color="#9ef0ff" />
        <stop offset="1" stop-color="#5ad5ff" />
      </linearGradient>
      <linearGradient id="bmDrop" x1="28" y1="28" x2="36" y2="46" gradientUnits="userSpaceOnUse">
        <stop stop-color="#b8f4ff" />
        <stop offset="1" stop-color="#2f8fe8" />
      </linearGradient>
      <linearGradient id="bmBeam" x1="18" y1="20" x2="30" y2="34" gradientUnits="userSpaceOnUse">
        <stop stop-color="#5ad5ff" stop-opacity="0.85" />
        <stop offset="1" stop-color="#5ad5ff" stop-opacity="0.1" />
      </linearGradient>
    </defs>

    <rect width="64" height="64" rx="14" fill="url(#bmBg)" />
    <rect x="1" y="1" width="62" height="62" rx="13" stroke="#5ad5ff" stroke-opacity="0.18" />

    <path
      d="M9 30 A23 23 0 0 1 55 30"
      stroke="url(#bmOrbit)"
      stroke-width="2.2"
      stroke-linecap="round"
    />

    <circle cx="15" cy="16.5" r="3" fill="#9ef0ff" />
    <circle cx="15" cy="16.5" r="5.8" stroke="#5ad5ff" stroke-opacity="0.35" />
    <rect x="7.5" y="12.8" width="4.4" height="1.7" rx="0.8" fill="#5ad5ff" fill-opacity="0.75" />
    <rect x="18.1" y="12.8" width="4.4" height="1.7" rx="0.8" fill="#5ad5ff" fill-opacity="0.75" />
    <rect x="12.4" y="7" width="1.7" height="4.4" rx="0.8" fill="#5ad5ff" fill-opacity="0.55" />
    <rect x="12.4" y="21.6" width="1.7" height="4.4" rx="0.8" fill="#5ad5ff" fill-opacity="0.55" />

    <path d="M19 22 L27 32" stroke="url(#bmBeam)" stroke-width="1.6" stroke-linecap="round" />
    <path
      d="M23 20 L30 29"
      stroke="url(#bmBeam)"
      stroke-width="1.1"
      stroke-linecap="round"
      opacity="0.7"
    />
    <path
      d="M16 26 L23 33"
      stroke="url(#bmBeam)"
      stroke-width="1.1"
      stroke-linecap="round"
      opacity="0.55"
    />

    <path
      d="M34 29.5 C38.2 35.4 40.4 38.4 40.4 41.4 A6.4 6.4 0 1 1 27.6 41.4 C27.6 38.4 29.8 35.4 34 29.5 Z"
      fill="url(#bmDrop)"
    />
    <path
      d="M31.2 41.2 A2.9 2.9 0 0 0 33.6 44.2"
      stroke="#e8fbff"
      stroke-opacity="0.85"
      stroke-width="1.3"
      stroke-linecap="round"
      fill="none"
    />

    <path d="M10 47 Q32 39.5 54 47" stroke="#d9a05b" stroke-width="3" stroke-linecap="round" />
    <path d="M8 52.5 Q32 45 56 52.5" stroke="#b07a3e" stroke-width="3.4" stroke-linecap="round" />
    <path d="M6 58 Q32 50.5 58 58" stroke="#7a4e26" stroke-width="3.8" stroke-linecap="round" />

    <circle cx="51.5" cy="46" r="1.6" fill="#ffc46b" />
  </svg>
</template>

<style scoped>
.brand-mark {
  display: block;
  flex-shrink: 0;
}
</style>
