<script setup lang="ts">
/**
 * AppearanceSettings — 外观设置面板
 *
 * 包含主题模式切换（深色/浅色/跟随系统）、地图显示设置（分布淡底/氛围遮罩）、
 * 以及动效偏好。
 */
import { ref } from 'vue'
import { useThemeStore, type ThemePreference } from '../../stores/theme'
import {
  isMapDistributionChromeEnabled,
  setMapDistributionChromeEnabled,
} from '../../services/settings-local'
import SegmentedControl from '../ui/SegmentedControl.vue'

const themeStore = useThemeStore()

const themeOptions = [
  { value: 'dark', label: '深色' },
  { value: 'light', label: '浅色' },
  { value: 'system', label: '跟随系统' },
]

const mapDistributionChrome = ref(isMapDistributionChromeEnabled())

function onMapDistributionChromeChange(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  mapDistributionChrome.value = checked
  setMapDistributionChromeEnabled(checked)
}

function onThemeChange(value: string | number) {
  themeStore.setTheme(value as ThemePreference)
}

const prefersReducedMotion = ref(
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches,
)

function onReducedMotionChange(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  prefersReducedMotion.value = checked
  if (typeof document !== 'undefined') {
    document.documentElement.classList.toggle('reduce-motion', checked)
  }
  if (typeof window !== 'undefined') {
    window.localStorage.setItem('cgda-reduce-motion', String(checked))
  }
}

// 初始化：localStorage 优先，无记录时跟随系统偏好
if (typeof window !== 'undefined') {
  const stored = window.localStorage.getItem('cgda-reduce-motion')
  if (stored !== null) {
    // 用户曾手动设置过，以此为准
    prefersReducedMotion.value = stored === 'true'
  }
  // 同步 class 到 <html>（无论来源是 localStorage 还是系统偏好）
  if (typeof document !== 'undefined') {
    document.documentElement.classList.toggle('reduce-motion', prefersReducedMotion.value)
  }
}
</script>

<template>
  <div class="appearance-settings">
    <!-- 主题模式 -->
    <section class="settings-section">
      <h3 class="section-title">主题模式</h3>
      <p class="section-hint">切换深色或浅色外观。选择「跟随系统」将根据操作系统的偏好自动切换。</p>
      <div class="theme-selector">
        <SegmentedControl
          :model-value="themeStore.preference"
          :options="themeOptions"
          size="md"
          @change="onThemeChange"
        />
      </div>
    </section>

    <!-- 地图显示 -->
    <section class="settings-section">
      <h3 class="section-title">地图显示</h3>
      <p class="section-hint">
        控制底图上方的分布淡底与氛围遮罩。需要有可见数据图层且缩放到较大范围时，
        才会呈现数据分布观感。无可见数据图层时氛围遮罩始终关闭。
      </p>
      <label class="toggle-row">
        <input
          type="checkbox"
          :checked="mapDistributionChrome"
          @change="onMapDistributionChromeChange"
        />
        <span>地图分布淡底 / 氛围遮罩</span>
      </label>
    </section>

    <!-- 动效偏好 -->
    <section class="settings-section">
      <h3 class="section-title">动效偏好</h3>
      <p class="section-hint">
        开启后将减少界面中的过渡动画和粒子效果，适合低性能设备或对动效敏感的用户。
      </p>
      <label class="toggle-row">
        <input type="checkbox" :checked="prefersReducedMotion" @change="onReducedMotionChange" />
        <span>减少动效</span>
      </label>
    </section>
  </div>
</template>

<style scoped>
.appearance-settings {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.settings-section {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.section-title {
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
  margin: 0;
}

.section-hint {
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
  margin: 0;
  line-height: 1.5;
}

.theme-selector {
  margin-top: 0.5rem;
}

.toggle-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
  font-size: var(--font-size-body);
  color: var(--text-primary);
}

.toggle-row input[type='checkbox'] {
  width: 16px;
  height: 16px;
  cursor: pointer;
  accent-color: var(--accent);
}
</style>
