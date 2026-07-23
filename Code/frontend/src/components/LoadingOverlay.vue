<script setup lang="ts">
/**
 * 全局加载动效：
 * - hero：全屏地球 + 卫星轨道（启动 / 大面板）
 * - compact：顶栏细进度条（普通 API 等）
 */
import { storeToRefs } from 'pinia'
import { useUiLoadingStore } from '../stores/ui-loading'

const uiLoading = useUiLoadingStore()
const { isVisible, message, mode } = storeToRefs(uiLoading)
</script>

<template>
  <Teleport to="body">
    <!-- 全屏地球 + 卫星 -->
    <Transition name="loading-fade">
      <div
        v-if="isVisible && mode === 'hero'"
        class="loading-overlay hero"
        role="alert"
        aria-live="polite"
        aria-busy="true"
      >
        <div class="hero-card">
          <div class="orbit-stage" aria-hidden="true">
            <div class="stars"></div>
            <div class="orbit-ring"></div>
            <div class="orbit-ring ring-2"></div>
            <div class="earth">
              <div class="earth-glow"></div>
              <div class="earth-sphere">
                <div class="lat lat-a"></div>
                <div class="lat lat-b"></div>
                <div class="lat lat-c"></div>
                <div class="meridian"></div>
                <div class="land land-a"></div>
                <div class="land land-b"></div>
              </div>
            </div>
            <div class="sat-orbit">
              <div class="satellite">
                <span class="sat-body"></span>
                <span class="sat-wing left"></span>
                <span class="sat-wing right"></span>
                <span class="sat-beam"></span>
              </div>
            </div>
          </div>
          <div class="loading-message">{{ message || '加载中' }}</div>
          <div class="loading-progress-bar" aria-hidden="true">
            <div class="loading-progress-glow"></div>
          </div>
        </div>
      </div>
    </Transition>

    <!-- 轻量顶栏 -->
    <Transition name="loading-fade">
      <div
        v-if="isVisible && mode === 'compact'"
        class="loading-compact"
        role="status"
        aria-live="polite"
        aria-busy="true"
      >
        <div class="compact-track" aria-hidden="true">
          <div class="compact-glow"></div>
        </div>
        <span class="compact-msg">{{ message || '加载中' }}</span>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.loading-overlay.hero {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(4, 10, 20, 0.72);
  backdrop-filter: blur(5px);
  -webkit-backdrop-filter: blur(5px);
}

.hero-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1.1rem;
  padding: 1.6rem 2rem 1.4rem;
  border-radius: 1rem;
  background: rgba(8, 18, 34, 0.78);
  border: 1px solid rgba(90, 213, 255, 0.18);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.45);
}

.orbit-stage {
  position: relative;
  width: 168px;
  height: 168px;
  display: grid;
  place-items: center;
}

.stars {
  position: absolute;
  inset: 12%;
  border-radius: 50%;
  background:
    radial-gradient(1px 1px at 20% 30%, rgba(255, 255, 255, 0.7), transparent),
    radial-gradient(1px 1px at 70% 22%, rgba(255, 255, 255, 0.55), transparent),
    radial-gradient(1.5px 1.5px at 40% 70%, rgba(180, 230, 255, 0.65), transparent),
    radial-gradient(1px 1px at 82% 62%, rgba(255, 255, 255, 0.5), transparent);
  opacity: 0.7;
  animation: twinkle 2.8s ease-in-out infinite;
}

.orbit-ring {
  position: absolute;
  width: 132px;
  height: 132px;
  border: 1px dashed rgba(90, 213, 255, 0.28);
  border-radius: 50%;
  transform: rotateX(58deg) scale(1.05);
}

.orbit-ring.ring-2 {
  width: 150px;
  height: 150px;
  border-color: rgba(255, 184, 77, 0.16);
  transform: rotateX(58deg) rotateZ(25deg) scale(1.02);
}

.earth {
  position: relative;
  width: 78px;
  height: 78px;
  z-index: 2;
}

.earth-glow {
  position: absolute;
  inset: -10px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(90, 213, 255, 0.28) 0%, transparent 68%);
  animation: pulse-glow 2.4s ease-in-out infinite;
}

.earth-sphere {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  overflow: hidden;
  background: radial-gradient(
    circle at 32% 28%,
    #7fd4ff 0%,
    #2a7fbf 38%,
    #0d3a62 78%,
    #071e36 100%
  );
  box-shadow:
    inset -10px -6px 18px rgba(0, 0, 0, 0.35),
    0 0 18px rgba(90, 213, 255, 0.25);
  animation: earth-spin 12s linear infinite;
}

.lat {
  position: absolute;
  left: 8%;
  right: 8%;
  height: 1px;
  background: rgba(200, 236, 255, 0.28);
  border-radius: 1px;
}

.lat-a {
  top: 28%;
}
.lat-b {
  top: 50%;
  background: rgba(200, 236, 255, 0.38);
}
.lat-c {
  top: 72%;
}

.meridian {
  position: absolute;
  top: 6%;
  bottom: 6%;
  left: 50%;
  width: 1px;
  background: rgba(200, 236, 255, 0.3);
  transform: translateX(-50%);
}

.land {
  position: absolute;
  background: rgba(120, 210, 150, 0.45);
  border-radius: 40% 60% 55% 45%;
  filter: blur(0.2px);
}

.land-a {
  width: 28px;
  height: 18px;
  top: 30%;
  left: 22%;
  transform: rotate(-18deg);
}

.land-b {
  width: 18px;
  height: 22px;
  top: 48%;
  left: 52%;
  transform: rotate(24deg);
  background: rgba(150, 220, 130, 0.4);
}

.sat-orbit {
  position: absolute;
  inset: 0;
  animation: sat-orbit 3.6s linear infinite;
  transform-style: preserve-3d;
}

.satellite {
  position: absolute;
  top: 10px;
  left: 50%;
  width: 18px;
  height: 10px;
  margin-left: -9px;
  transform: rotateX(58deg);
}

.sat-body {
  position: absolute;
  left: 6px;
  top: 2px;
  width: 6px;
  height: 6px;
  border-radius: 1px;
  background: linear-gradient(135deg, #fff6e0, #ffb84d);
  box-shadow: 0 0 8px rgba(255, 184, 77, 0.7);
}

.sat-wing {
  position: absolute;
  top: 3px;
  width: 6px;
  height: 4px;
  background: rgba(90, 213, 255, 0.85);
  box-shadow: 0 0 6px rgba(90, 213, 255, 0.5);
}

.sat-wing.left {
  left: 0;
}
.sat-wing.right {
  right: 0;
}

.sat-beam {
  position: absolute;
  left: 8px;
  top: 8px;
  width: 2px;
  height: 14px;
  background: linear-gradient(180deg, rgba(255, 184, 77, 0.7), transparent);
  transform-origin: top center;
  animation: beam-pulse 1.2s ease-in-out infinite;
}

.loading-message {
  color: #c5dceb;
  font-size: 0.8rem;
  font-weight: 500;
  letter-spacing: 0.04em;
  text-align: center;
  min-height: 1.2em;
}

.loading-message::after {
  content: '';
  display: inline-block;
  width: 1.5em;
  text-align: left;
  animation: loading-dots 1.4s steps(4, end) infinite;
}

.loading-progress-bar {
  position: relative;
  width: 148px;
  height: 2px;
  background: rgba(90, 213, 255, 0.12);
  border-radius: 1px;
  overflow: hidden;
}

.loading-progress-glow {
  position: absolute;
  inset: 0 auto 0 0;
  width: 40%;
  background: linear-gradient(
    90deg,
    rgba(90, 213, 255, 0) 0%,
    rgba(90, 213, 255, 0.85) 50%,
    rgba(255, 184, 77, 0) 100%
  );
  animation: progress-slide 1.6s ease-in-out infinite;
}

/* compact 顶栏 */
.loading-compact {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 9998;
  pointer-events: none;
  display: flex;
  flex-direction: column;
  align-items: stretch;
}

.compact-track {
  height: 2px;
  background: rgba(90, 213, 255, 0.12);
  overflow: hidden;
}

.compact-glow {
  height: 100%;
  width: 28%;
  background: linear-gradient(
    90deg,
    transparent,
    rgba(90, 213, 255, 0.95),
    rgba(255, 184, 77, 0.8),
    transparent
  );
  animation: progress-slide 1.1s ease-in-out infinite;
}

.compact-msg {
  align-self: center;
  margin-top: 0.35rem;
  padding: 0.18rem 0.55rem;
  border-radius: 999px;
  background: rgba(8, 18, 34, 0.82);
  border: 1px solid rgba(90, 213, 255, 0.2);
  color: #a8c4d8;
  font-size: 0.58rem;
  letter-spacing: 0.03em;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.28);
}

.compact-msg::after {
  content: '';
  display: inline-block;
  width: 1.2em;
  animation: loading-dots 1.4s steps(4, end) infinite;
}

@keyframes earth-spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

@keyframes sat-orbit {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

@keyframes pulse-glow {
  0%,
  100% {
    opacity: 0.55;
    transform: scale(1);
  }
  50% {
    opacity: 1;
    transform: scale(1.06);
  }
}

@keyframes beam-pulse {
  0%,
  100% {
    opacity: 0.35;
  }
  50% {
    opacity: 0.95;
  }
}

@keyframes twinkle {
  0%,
  100% {
    opacity: 0.45;
  }
  50% {
    opacity: 0.85;
  }
}

@keyframes progress-slide {
  0% {
    transform: translateX(-120%);
  }
  100% {
    transform: translateX(380%);
  }
}

@keyframes loading-dots {
  0% {
    content: '';
  }
  25% {
    content: '.';
  }
  50% {
    content: '..';
  }
  75% {
    content: '...';
  }
  100% {
    content: '';
  }
}

.loading-fade-enter-active,
.loading-fade-leave-active {
  transition: opacity 0.22s ease;
}

.loading-fade-enter-from,
.loading-fade-leave-to {
  opacity: 0;
}
</style>
