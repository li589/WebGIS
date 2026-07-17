<script setup lang="ts">
/**
 * LoadingOverlay.vue
 *
 * 全局加载等待动效组件 — 等高线波纹风格。
 *
 * 设计理念：
 * - 多层同心圆从中心向外扩散，模拟地理等高线/水波纹效果
 * - 颜色从青色（#5ad5ff）渐变到橙色（#ffb84d），契合系统引擎配色
 * - 5 层波纹错开 0.3s 延迟，形成连续扩散的视觉
 * - 半透明背景 + 轻微模糊，不阻断用户对底层界面的感知
 *
 * 使用方式：
 * - 通过 useUiLoadingStore 的 isVisible/message 控制
 * - 在 App.vue 中全局挂载，无需手动调用
 */
import { computed } from 'vue'
import { useUiLoadingStore } from '../stores/ui-loading'
import { storeToRefs } from 'pinia'

const uiLoading = useUiLoadingStore()
const { isVisible, message } = storeToRefs(uiLoading)

// 5 层波纹环，每层延迟 0.3s
const rings = computed(() => [
  { delay: '0s', duration: '1.8s' },
  { delay: '0.3s', duration: '1.8s' },
  { delay: '0.6s', duration: '1.8s' },
  { delay: '0.9s', duration: '1.8s' },
  { delay: '1.2s', duration: '1.8s' },
])

// 等高线标签（装饰性，显示海拔数值模拟等高线地图）
const contourLabels = computed(() => [
  { text: '100m', angle: -30, radius: 38 },
  { text: '200m', angle: 45, radius: 52 },
  { text: '300m', angle: 120, radius: 66 },
  { text: '400m', angle: 200, radius: 80 },
])
</script>

<template>
  <Transition name="loading-fade">
    <div
      v-if="isVisible"
      class="loading-overlay"
      role="alert"
      aria-live="polite"
      aria-busy="true"
    >
      <div class="loading-content">
        <!-- 等高线波纹动效主体 -->
        <div class="contour-loader">
          <!-- 中心点 -->
          <div class="contour-center" aria-hidden="true"></div>

          <!-- 扩散波纹环 -->
          <div
            v-for="(ring, i) in rings"
            :key="i"
            class="contour-ring"
            :style="{ animationDelay: ring.delay, animationDuration: ring.duration }"
            aria-hidden="true"
          ></div>

          <!-- 装饰性等高线标签（旋转跟随） -->
          <svg
            class="contour-labels"
            viewBox="-100 -100 200 200"
            aria-hidden="true"
          >
            <text
              v-for="(label, i) in contourLabels"
              :key="i"
              :x="label.radius * Math.cos((label.angle * Math.PI) / 180)"
              :y="label.radius * Math.sin((label.angle * Math.PI) / 180)"
              class="contour-label-text"
              text-anchor="middle"
              dominant-baseline="middle"
            >{{ label.text }}</text>
          </svg>
        </div>

        <!-- 加载提示文字 -->
        <div v-if="message" class="loading-message">{{ message }}</div>
        <div v-else class="loading-message loading-message-default">加载中</div>

        <!-- 底部渐变进度条（装饰性，非真实进度） -->
        <div class="loading-progress-bar" aria-hidden="true">
          <div class="loading-progress-glow"></div>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.loading-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(8, 15, 28, 0.55);
  backdrop-filter: blur(3px);
  -webkit-backdrop-filter: blur(3px);
}

.loading-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1.2rem;
  padding: 2rem 2.5rem;
  border-radius: 1rem;
  background: rgba(12, 24, 42, 0.6);
  border: 1px solid rgba(90, 213, 255, 0.15);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}

/* ── 等高线波纹动效 ────────────────────────────────────────── */
.contour-loader {
  position: relative;
  width: 160px;
  height: 160px;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 中心固定圆点 */
.contour-center {
  position: absolute;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: radial-gradient(circle, #ffd38a 0%, #ffb84d 60%, rgba(255, 184, 77, 0) 100%);
  box-shadow: 0 0 12px rgba(255, 184, 77, 0.6);
  z-index: 2;
}

/* 扩散波纹环 */
.contour-ring {
  position: absolute;
  width: 160px;
  height: 160px;
  border: 1.5px solid rgba(90, 213, 255, 0.5);
  border-radius: 50%;
  opacity: 0;
  animation-name: contour-expand;
  animation-timing-function: cubic-bezier(0.25, 0.46, 0.45, 0.94);
  animation-iteration-count: infinite;
}

@keyframes contour-expand {
  0% {
    transform: scale(0.15);
    opacity: 0;
    border-color: rgba(90, 213, 255, 0.9);
    border-width: 2px;
  }
  15% {
    opacity: 1;
  }
  50% {
    border-color: rgba(136, 223, 255, 0.5);
  }
  100% {
    transform: scale(1);
    opacity: 0;
    border-color: rgba(255, 184, 77, 0.15);
    border-width: 1px;
  }
}

/* 装饰性等高线标签 SVG */
.contour-labels {
  position: absolute;
  width: 160px;
  height: 160px;
  pointer-events: none;
  animation: contour-rotate 12s linear infinite;
}

@keyframes contour-rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.contour-label-text {
  fill: rgba(90, 213, 255, 0.35);
  font-size: 8px;
  font-family: 'Consolas', 'Monaco', monospace;
  font-weight: 500;
  user-select: none;
}

/* ── 加载提示文字 ──────────────────────────────────────────── */
.loading-message {
  color: #b8d4e8;
  font-size: 0.82rem;
  font-weight: 500;
  letter-spacing: 0.04em;
  text-align: center;
  min-height: 1.2em;
}

.loading-message-default {
  color: #8aa8bf;
}

/* 文字省略号呼吸动画 */
.loading-message::after {
  content: '';
  display: inline-block;
  width: 1.5em;
  text-align: left;
  animation: loading-dots 1.4s steps(4, end) infinite;
}

@keyframes loading-dots {
  0% { content: ''; }
  25% { content: '.'; }
  50% { content: '..'; }
  75% { content: '...'; }
  100% { content: ''; }
}

/* ── 底部装饰性进度条 ──────────────────────────────────────── */
.loading-progress-bar {
  position: relative;
  width: 140px;
  height: 2px;
  background: rgba(90, 213, 255, 0.1);
  border-radius: 1px;
  overflow: hidden;
}

.loading-progress-glow {
  position: absolute;
  top: 0;
  left: 0;
  width: 40%;
  height: 100%;
  background: linear-gradient(90deg,
    rgba(90, 213, 255, 0) 0%,
    rgba(90, 213, 255, 0.8) 50%,
    rgba(255, 184, 77, 0) 100%
  );
  border-radius: 1px;
  animation: progress-slide 1.6s ease-in-out infinite;
}

@keyframes progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(350%); }
}

/* ── 淡入淡出过渡 ──────────────────────────────────────────── */
.loading-fade-enter-active,
.loading-fade-leave-active {
  transition: opacity 0.25s ease;
}

.loading-fade-enter-from,
.loading-fade-leave-to {
  opacity: 0;
}
</style>
