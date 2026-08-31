/**
 * ECharts 主题适配
 *
 * ECharts 主题不接受 CSS 变量（var(--token)），必须传字面量色值。
 * 本模块从 getComputedStyle 读取设计 token 实际值构建主题对象，
 * 按当前主题模式注册为 'cgda-dark' / 'cgda-light'。
 * 主题切换时以新 token 重注册，消费组件用主题名作为 :key 重挂载图表完成刷新。
 */
import { computed, watch } from 'vue'
import { registerTheme } from 'echarts/core'
import { useThemeStore } from '../../stores/theme'

export const ECHARTS_THEME_DARK = 'cgda-dark'
export const ECHARTS_THEME_LIGHT = 'cgda-light'

function readCssVar(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

/** 系列调色板：品牌色 + 语义色，深浅主题各自解析 */
const PALETTE_TOKENS: Array<[string, string]> = [
  ['--accent', '#5ad5ff'],
  ['--success', '#9ff8cf'],
  ['--accent-warm', '#ffc878'],
  ['--accent-blue-deep', '#2f7eff'],
  ['--warning', '#ffb070'],
  ['--danger', '#ff8c64'],
]

/** 构建 ECharts 主题对象；主题切换后再次调用会解析到新 token 值 */
export function buildEchartsTheme(): Record<string, unknown> {
  const textPrimary = readCssVar('--text-primary', '#d8e6f5')
  const textSecondary = readCssVar('--text-secondary', '#9fb6cc')
  const textFaint = readCssVar('--text-faint', '#6e8ba0')
  const axisBorder = readCssVar('--border-default', 'rgba(136,192,255,0.16)')
  const splitLine = readCssVar('--border-subtle', 'rgba(136,192,255,0.08)')
  const tooltipBg = readCssVar('--surface-3', 'rgba(18,30,48,0.96)')

  const axisCommon = {
    axisLine: { lineStyle: { color: axisBorder } },
    axisTick: { lineStyle: { color: axisBorder } },
    axisLabel: { color: textSecondary },
    splitLine: { show: true, lineStyle: { color: splitLine } },
    nameTextStyle: { color: textSecondary },
  }

  return {
    color: PALETTE_TOKENS.map(([name, fallback]) => readCssVar(name, fallback)),
    backgroundColor: 'transparent',
    textStyle: { color: textPrimary },
    title: {
      textStyle: { color: textPrimary },
      subtextStyle: { color: textSecondary },
    },
    legend: {
      textStyle: { color: textSecondary },
      inactiveColor: textFaint,
    },
    categoryAxis: axisCommon,
    valueAxis: axisCommon,
    timeAxis: axisCommon,
    logAxis: axisCommon,
    tooltip: {
      backgroundColor: tooltipBg,
      borderColor: axisBorder,
      textStyle: { color: textPrimary },
    },
    dataZoom: {
      textStyle: { color: textSecondary },
      borderColor: axisBorder,
    },
  }
}

/** 已注册主题名集合（主题切换时置失效后重注册） */
const registered = new Set<string>()

/** 确保当前模式的主题已注册，返回主题名 */
export function ensureEchartsThemeRegistered(mode: 'dark' | 'light'): string {
  const name = mode === 'light' ? ECHARTS_THEME_LIGHT : ECHARTS_THEME_DARK
  if (!registered.has(name)) {
    registerTheme(name, buildEchartsTheme())
    registered.add(name)
  }
  return name
}

/**
 * 组合式：返回当前 ECharts 主题名（响应式）。
 * 首次调用与主题切换时按当前 DOM token 注册/重注册主题。
 */
export function useEchartsThemeName() {
  const themeStore = useThemeStore()
  const themeName = computed(() =>
    themeStore.mode === 'light' ? ECHARTS_THEME_LIGHT : ECHARTS_THEME_DARK,
  )
  // pre-flush：确保重注册先于组件 :key 变化触发的重挂载
  watch(themeName, (name) => {
    registered.delete(name)
    ensureEchartsThemeRegistered(name === ECHARTS_THEME_LIGHT ? 'light' : 'dark')
  })
  ensureEchartsThemeRegistered(themeStore.mode)
  return themeName
}
