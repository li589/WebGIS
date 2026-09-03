<script setup lang="ts">
/**
 * AppearanceSettings — 外观设置面板
 *
 * 包含主题模式切换（深色/浅色/跟随系统）、地图显示设置（分布淡底/氛围遮罩）、
 * 以及动效偏好。
 */
import { onUnmounted, ref } from 'vue'
import { useThemeStore, type ThemePreference } from '../../stores/theme'
import {
  getGlobeBackgroundMode,
  getGlobeDaylightMode,
  getGlobeRenderEngine,
  is3DViewExperimentalEnabled,
  isMapDistributionChromeEnabled,
  isShowAnalysisResultOnMapEnabled,
  set3DViewExperimentalEnabled,
  setGlobeBackgroundMode,
  setGlobeDaylightMode,
  setGlobeRenderEngine,
  setMapDistributionChromeEnabled,
  setShowAnalysisResultOnMapEnabled,
  subscribeGlobeScene,
  type GlobeBackgroundMode,
  type GlobeDaylightMode,
  type GlobeRenderEngine,
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

const globeRenderEngine = ref<GlobeRenderEngine>(getGlobeRenderEngine())

const globeRenderEngineOptions = [
  { value: 'maplibre', label: 'MapLibre（默认）' },
  { value: 'cesium', label: 'Cesium（实验）' },
]

const mapLibreSceneOnly = ref(globeRenderEngine.value === 'maplibre')

function onGlobeRenderEngineChange(value: string | number) {
  globeRenderEngine.value = value as GlobeRenderEngine
  mapLibreSceneOnly.value = globeRenderEngine.value === 'maplibre'
  setGlobeRenderEngine(globeRenderEngine.value)
}

const globeBackground = ref<GlobeBackgroundMode>(getGlobeBackgroundMode())

const globeBackgroundOptions = [
  { value: 'auto', label: '跟随主题' },
  { value: 'starfield', label: '星图' },
  { value: 'solar_system', label: '太阳系' },
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

const unsubGlobeScene = subscribeGlobeScene(() => {
  globeRenderEngine.value = getGlobeRenderEngine()
  mapLibreSceneOnly.value = globeRenderEngine.value === 'maplibre'
  globeBackground.value = getGlobeBackgroundMode()
  globeDaylight.value = getGlobeDaylightMode()
})
onUnmounted(() => {
  unsubGlobeScene()
})

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
          <span class="scene-option-label">3D 渲染模式</span>
          <SegmentedControl
            :model-value="globeRenderEngine"
            :options="globeRenderEngineOptions"
            size="xs"
            @change="onGlobeRenderEngineChange"
          />
        </div>
        <p class="section-hint">
          MapLibre 为默认主链（地球投影 + 现有天气叠加）。Cesium 为实验引擎：底图、overlay 栅格瓦片与「自然」光影已接；天气 GeoJSON / 风场粒子尚未接入。
        </p>
        <div class="scene-option" :class="{ 'scene-option--disabled': !mapLibreSceneOnly }">
          <span class="scene-option-label">3D 背景</span>
          <SegmentedControl
            :model-value="globeBackground"
            :options="globeBackgroundOptions"
            size="xs"
            :disabled="!mapLibreSceneOnly"
            @change="onGlobeBackgroundChange"
          />
        </div>
        <p class="section-hint">
          3D 模式下地球背后的深空背景。「跟随主题」在深色界面显示星图/银河，浅色界面淡化为柔和微尘。
          「太阳系」随视角旋转星空，并按时间轴显示太阳盘（晨昏线仍由「3D 光影」控制）。
          <template v-if="!mapLibreSceneOnly">当前仅 MapLibre 模式生效。</template>
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
          3D 光影：「标准」压亮底图瓦片（MapLibre）/ 明亮地球（Cesium）；「自然」按时间轴夜半球；「无」关闭亮暗效果。
          Cesium 模式下「自然」驱动引擎光照时钟，与时间轴小时联动。
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

.scene-option--disabled {
  opacity: 0.55;
}
</style>
