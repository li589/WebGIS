// @vitest-environment jsdom
//
// 登录页（LoginView）品牌锁版与密码可见性切换回归：
//   1) 品牌锁版：SGFS 缩写位于图标正下方，中文名与英文名两行居中堆叠；
//   2) 提示性文案已移除（"登录以访问地图分析…"、底部 Cookie 安全提示）；
//   3) 密码眼睛按钮：明文/密文切换 + aria-pressed/aria-label 联动。
import { beforeEach, describe, expect, it } from 'vitest'

import { createMemoryHistory, createPinia, createRouter, mount, setActivePinia } from '@/test-utils'
import LoginView from '@/views/LoginView.vue'

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
  return wrapper
}

beforeEach(() => {
  setActivePinia(createPinia())
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
    const names = wrapper.find('.brand-names')
    expect(names.exists()).toBe(true)
    expect(names.find('h1').text()).toBe('星地融合土壤数据平台')
    expect(names.find('.brand-name-en').text()).toBe('Satellite-Ground Fusion Soil Data Platform')
    const h1 = names.find('h1').element
    const en = names.find('.brand-name-en').element
    expect(h1.compareDocumentPosition(en) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0)
  })

  it('不再渲染提示性文案（访问提示与底部安全提示）', async () => {
    const wrapper = await mountView()
    const text = wrapper.text()
    expect(text).not.toContain('登录以访问地图')
    expect(text).not.toContain('会话通过安全 Cookie')
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
