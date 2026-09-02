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
  getGlobeBackgroundMode,
  getGlobeDaylightMode,
  is3DViewExperimentalEnabled,
  isMapDistributionChromeEnabled,
  isShowAnalysisResultOnMapEnabled,
  set3DViewExperimentalEnabled,
  setGlobeBackgroundMode,
  setGlobeDaylightMode,
  setMapDistributionChromeEnabled,
  setShowAnalysisResultOnMapEnabled,
  type GlobeBackgroundMode,
  type GlobeDaylightMode,
} from '../../services/settings-local'
import {
  resolveReducedMotionPreference,
  setReducedMotionPreference,
} from '../../services/motion-preference'
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

const showAnalysisResultOnMap = ref(isShowAnalysisResultOnMapEnabled())

function onShowAnalysisResultOnMapChange(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  showAnalysisResultOnMap.value = checked
  setShowAnalysisResultOnMapEnabled(checked)
}

const enable3DView = ref(is3DViewExperimentalEnabled())

function onEnable3DViewChange(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  enable3DView.value = checked
  set3DViewExperimentalEnabled(checked)
}

const globeBackground = ref<GlobeBackgroundMode>(getGlobeBackgroundMode())

const globeBackgroundOptions = [
  { value: 'auto', label: '跟随主题' },
  { value: 'starfield', label: '星图' },
  { value: 'minimal', label: '极简' },
]

function onGlobeBackgroundChange(value: string | number) {
  globeBackground.value = value as GlobeBackgroundMode
  setGlobeBackgroundMode(globeBackground.value)
}

const globeDaylight = ref<GlobeDaylightMode>(getGlobeDaylightMode())

const globeDaylightOptions = [
  { value: 'standard', label: '标准' },
  { value: 'natural', label: '自然' },
  { value: 'off', label: '无' },
]

function onGlobeDaylightChange(value: string | number) {
  globeDaylight.value = value as GlobeDaylightMode
  setGlobeDaylightMode(globeDaylight.value)
}

function onThemeChange(value: string | number) {
  themeStore.setTheme(value as ThemePreference)
}

const prefersReducedMotion = ref(resolveReducedMotionPreference())

function onReducedMotionChange(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  prefersReducedMotion.value = checked
  setReducedMotionPreference(checked)
}
</script>

<template>
  <div class="appearance-settings">
    <!-- 主题模式 -->
    <section class="settings-section">
      <h3 class="section-title">主题模式</h3>
      <p class="section-hint">
        切换深色或浅色外观。选择「跟随系统」将根据操作系统的偏好自动切换。系统已内置完整主题；若安装了
        Dark Reader 等浏览器扩展，请对本站关闭（页面已声明
        darkreader-lock，避免叠加深色滤镜导致浅色发褐）。
      </p>
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
      <label class="toggle-row">
        <input
          type="checkbox"
          :checked="showAnalysisResultOnMap"
          @change="onShowAnalysisResultOnMapChange"
        />
        <span>成功后在地图显示分析结果图层（默认开）</span>
      </label>
      <label class="toggle-row">
        <input type="checkbox" :checked="enable3DView" @change="onEnable3DViewChange" />
        <span>启用3D视图（实验测试）</span>
      </label>
      <p class="section-hint hint-3d">
        开启后，顶栏切换到 3D 模式时地图将以地球投影显示全部图层，不再显示「尚未实现」遮罩提示。
        实验功能：部分叠加层在球面投影下的表现尚未充分验证，遇到异常可关闭本项并切回 2D。
      </p>

      <!-- 3D 场景偏好（仅在启用 3D 视图时展示） -->
      <div v-if="enable3DView" class="globe-scene-options">
        <div class="scene-option">
          <span class="scene-option-label">3D 背景</span>
          <SegmentedControl
            :model-value="globeBackground"
            :options="globeBackgroundOptions"
            size="xs"
            @change="onGlobeBackgroundChange"
          />
        </div>
        <p class="section-hint">
          3D 模式下地球背后的深空背景。「跟随主题」在深色界面显示星图/银河，浅色界面淡化为柔和微尘。
        </p>
        <div class="scene-option">
          <span class="scene-option-label">3D 光影</span>
          <SegmentedControl
            :model-value="globeDaylight"
            :options="globeDaylightOptions"
            size="xs"
            @change="onGlobeDaylightChange"
          />
        </div>
        <p class="section-hint">
          3D
          光影：「标准」压亮底图瓦片（左上立体感），不画昼夜遮罩；「自然」按时间轴硬边暗/亮半球（v1
          无晨昏羽化/动画）；「无」取消一切亮暗效果。
        </p>
      </div>
    </section>

    <!-- 动效偏好 -->
    <section class="settings-section">
      <h3 class="section-title">动效偏好</h3>
      <p class="section-hint">
        开启「减少动效」后将缩短按钮、对话框、面板入场与拖拽反馈等过渡；全局加载指示（启动地球 /
        顶栏进度条）仍保留轻量运动以免看起来像卡死。适合低性能设备或对动效敏感的用户。未手动设置时跟随系统「减少动画」偏好。
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

.hint-3d {
  margin-top: -0.25rem;
}

.globe-scene-options {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-top: 0.25rem;
  padding: 0.75rem 0.875rem;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface-sunken);
}

.scene-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.scene-option-label {
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
  white-space: nowrap;
}
</style>
