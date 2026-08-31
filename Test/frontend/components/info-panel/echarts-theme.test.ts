// @vitest-environment jsdom
//
// ECharts 主题适配：token 解析（无 CSS var 时 fallback）、按模式注册、
// 主题名跟随 theme store 模式切换。
import { beforeEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from '@/test-utils'

import {
  ECHARTS_THEME_DARK,
  ECHARTS_THEME_LIGHT,
  buildEchartsTheme,
  ensureEchartsThemeRegistered,
  useEchartsThemeName,
} from '@/components/info-panel/echarts-theme'
import { useThemeStore } from '@/stores/theme'

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('buildEchartsTheme', () => {
  it('调色板 6 色且轴/tooltip 均解析出字面量色值', () => {
    const theme = buildEchartsTheme() as {
      color: string[]
      valueAxis: { axisLabel: { color: string } }
      tooltip: { backgroundColor: string }
      legend: { inactiveColor: string }
    }
    expect(theme.color).toHaveLength(6)
    expect(theme.color[0]).toBe('#5ad5ff')
    expect(theme.valueAxis.axisLabel.color).toBeTruthy()
    expect(theme.tooltip.backgroundColor).toBeTruthy()
    expect(theme.legend.inactiveColor).toBeTruthy()
  })
})

describe('ensureEchartsThemeRegistered', () => {
  it('按模式注册并返回主题名，重复调用不抛错', () => {
    expect(ensureEchartsThemeRegistered('dark')).toBe(ECHARTS_THEME_DARK)
    expect(ensureEchartsThemeRegistered('light')).toBe(ECHARTS_THEME_LIGHT)
    expect(ensureEchartsThemeRegistered('dark')).toBe(ECHARTS_THEME_DARK)
  })
})

describe('useEchartsThemeName', () => {
  it('主题名跟随 theme store 模式切换', async () => {
    const themeStore = useThemeStore()
    themeStore.setTheme('dark')
    await nextTick()
    const name = useEchartsThemeName()
    expect(name.value).toBe(ECHARTS_THEME_DARK)

    themeStore.setTheme('light')
    await nextTick()
    expect(name.value).toBe(ECHARTS_THEME_LIGHT)
  })
})
