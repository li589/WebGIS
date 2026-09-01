// @vitest-environment jsdom
//
// 登录页（LoginView）品牌锁版与密码可见性切换回归：
//   1) 品牌锁版：SGFS 缩写位于图标正下方，中文名与英文名两行居中堆叠；
//   2) 提示性文案已移除（"登录以访问地图分析…"、底部 Cookie 安全提示）；
//   3) 密码眼睛按钮：明文/密文切换 + aria-pressed/aria-label 联动。
//   4) 多产品主题：公开主题列表驱动品牌文案与登录氛围色。
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createMemoryHistory, createPinia, createRouter, mount, setActivePinia } from '@/test-utils'
import LoginView from '@/views/LoginView.vue'
import { useAuthStore } from '@/stores/auth'

const fetchPrimaryThemePublicMock = vi.fn()
const fetchThemesPublicMock = vi.fn()

vi.mock('@/services/auth-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/auth-api')>()
  return {
    ...actual,
    fetchPrimaryThemePublic: (...args: unknown[]) => fetchPrimaryThemePublicMock(...args),
    fetchThemesPublic: (...args: unknown[]) => fetchThemesPublicMock(...args),
  }
})

const testRouter = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', component: { template: '<div />' } },
    { path: '/login', component: LoginView },
  ],
})

async function mountView() {
  const wrapper = mount(LoginView, {
    global: { plugins: [createPinia(), testRouter] },
  })
  await testRouter.isReady()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await wrapper.vm.$nextTick()
  return wrapper
}

beforeEach(() => {
  setActivePinia(createPinia())
  document.documentElement.setAttribute('data-theme', 'light')
  fetchPrimaryThemePublicMock.mockReset()
  fetchThemesPublicMock.mockReset()
  fetchPrimaryThemePublicMock.mockResolvedValue({
    id: 1,
    slug: 'sgfs',
    name_zh: '星地融合土壤数据平台',
    full_name_zh: '星地融合土壤水分监测与干旱预警数据分析与可视化系统',
    name_en: 'Satellite-Ground Fusion Soil Data Platform',
    abbr: 'SGFS',
  })
  fetchThemesPublicMock.mockResolvedValue([
    {
      id: 1,
      slug: 'sgfs',
      name_zh: '星地融合土壤数据平台',
      full_name_zh: '星地融合土壤水分监测与干旱预警数据分析与可视化系统',
      name_en: 'Satellite-Ground Fusion Soil Data Platform',
      abbr: 'SGFS',
    },
  ])
})

describe('LoginView 品牌锁版', () => {
  it('SGFS 缩写渲染于图标正下方', async () => {
    const wrapper = await mountView()
    const mark = wrapper.find('.brand-mark').element
    const abbr = wrapper.find('.brand-abbr')
    expect(abbr.text()).toBe('SGFS')
    expect(mark.compareDocumentPosition(abbr.element) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0)
  })

  it('中文名与英文名两行居中堆叠（中文名在前）', async () => {
    const wrapper = await mountView()
    await wrapper.vm.$nextTick()
    const names = wrapper.find('.brand-names')
    expect(names.exists()).toBe(true)
    expect(names.find('h1').text()).toBe('星地融合土壤数据平台')
    expect(names.find('.brand-name-en').text()).toBe('Satellite-Ground Fusion Soil Data Platform')
    const h1 = names.find('h1').element
    const en = names.find('.brand-name-en').element
    expect(h1.compareDocumentPosition(en) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0)
  })

  it('全局浅色主题下仍锁定登录页标题高对比色', async () => {
    const wrapper = await mountView()
    await wrapper.vm.$nextTick()
    const page = wrapper.find('.login-page')
    const style = page.attributes('style') || ''
    expect(style).toContain('--login-title-base')
    expect(style).toContain('#f5fcff')
  })

  it('不再渲染提示性文案（访问提示与底部安全提示）', async () => {
    const wrapper = await mountView()
    const text = wrapper.text()
    expect(text).not.toContain('登录以访问地图')
    expect(text).not.toContain('会话通过安全 Cookie')
  })
})

describe('LoginView 多产品主题', () => {
  it('多个公开主题时展示选择器并切换品牌与氛围色', async () => {
    fetchThemesPublicMock.mockResolvedValue([
      {
        id: 1,
        slug: 'sgfs',
        name_zh: '星地融合土壤数据平台',
        full_name_zh: '星地融合土壤水分监测与干旱预警数据分析与可视化系统',
        name_en: 'Satellite-Ground Fusion Soil Data Platform',
        abbr: 'SGFS',
      },
      {
        id: 2,
        slug: 'warm-soil',
        name_zh: '暖色土壤监测平台',
        full_name_zh: '暖色土壤监测与预警平台',
        name_en: 'Warm Soil Monitoring Platform',
        abbr: 'WSMP',
      },
    ])
    const wrapper = await mountView()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.theme-picker').exists()).toBe(true)

    const auth = useAuthStore()
    auth.setLoginPreviewSlug('warm-soil')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.brand-abbr').text()).toBe('WSMP')
    expect(wrapper.find('h1').text()).toBe('暖色土壤监测平台')
    expect(wrapper.find('.login-page').attributes('data-theme-slug')).toBe('warm-soil')
    const style = wrapper.find('.login-page').attributes('style') || ''
    expect(style).toContain('--login-accent')
    expect(style).toContain('#ffc878')
  })
})

describe('LoginView 密码可见性切换', () => {
  it('默认密文；点击眼睛按钮切换明文并联动 aria 状态，再点击恢复', async () => {
    const wrapper = await mountView()
    const input = wrapper.find('input[autocomplete="current-password"]')
    const toggle = wrapper.find('.password-toggle')

    expect(input.attributes('type')).toBe('password')
    expect(toggle.attributes('aria-pressed')).toBe('false')
    expect(toggle.attributes('aria-label')).toBe('显示密码')

    await toggle.trigger('click')
    expect(input.attributes('type')).toBe('text')
    expect(toggle.attributes('aria-pressed')).toBe('true')
    expect(toggle.attributes('aria-label')).toBe('隐藏密码')

    await toggle.trigger('click')
    expect(input.attributes('type')).toBe('password')
    expect(toggle.attributes('aria-pressed')).toBe('false')
    expect(toggle.attributes('aria-label')).toBe('显示密码')
  })
})
