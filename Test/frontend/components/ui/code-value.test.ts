// @vitest-environment jsdom
//
// CodeValue：超长配置值展示组件。
// 短值不显示展开态；超长值单行省略 → 点击展开 → 复制到剪贴板。
import { describe, expect, it, vi } from 'vitest'
import { mount } from '@/test-utils'
import CodeValue from '@/components/ui/CodeValue.vue'

const LONG = 'D:/very/long/deployment/path/to/some/data/root/directory/that/exceeds/threshold'

describe('CodeValue', () => {
  it('renders short value without expand affordance', () => {
    const wrapper = mount(CodeValue, { props: { value: 'D:/geo' } })
    const text = wrapper.find('.cv-text')
    expect(text.text()).toBe('D:/geo')
    expect(text.attributes('role')).toBeUndefined()
  })

  it('renders placeholder for empty value and hides copy button', () => {
    const wrapper = mount(CodeValue, { props: { value: '', placeholder: '（未设置）' } })
    expect(wrapper.find('.cv-text').text()).toBe('（未设置）')
    expect(wrapper.find('.cv-act').exists()).toBe(false)
  })

  it('expands long value on click and collapses back', async () => {
    const wrapper = mount(CodeValue, { props: { value: LONG } })
    const text = wrapper.find('.cv-text')
    expect(text.classes()).toContain('cv-text--clip')
    await text.trigger('click')
    expect(wrapper.find('.code-value--open').exists()).toBe(true)
    const collapse = wrapper.findAll('button').find((b) => b.text() === '收起')
    expect(collapse).toBeTruthy()
    await collapse!.trigger('click')
    expect(wrapper.find('.code-value--open').exists()).toBe(false)
  })

  it('copies value via clipboard API and shows confirmed state', async () => {
    const writeText = vi.fn(async () => undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    const wrapper = mount(CodeValue, { props: { value: LONG } })
    const copyBtn = wrapper.find('.cv-act')
    await copyBtn.trigger('click')
    expect(writeText).toHaveBeenCalledWith(LONG)
  })
})
