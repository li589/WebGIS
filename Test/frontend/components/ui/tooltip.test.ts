// @vitest-environment jsdom
import { mount } from '@/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import Tooltip from '@/components/ui/Tooltip.vue'

describe('Tooltip', () => {
  afterEach(() => {
    document.body.innerHTML = ''
    vi.useRealTimers()
  })

  it('Teleport 到 body，使用 fixed 定位与顶置样式', async () => {
    vi.useFakeTimers()
    const wrapper = mount(Tooltip, {
      props: { text: '图层库', delayMs: 0 },
      slots: { default: '<button type="button">+</button>' },
      attachTo: document.body,
    })

    await wrapper.find('.tooltip-trigger').trigger('mouseenter')
    vi.runAllTimers()
    await nextTick()
    await nextTick()

    const box = document.body.querySelector('.tooltip-box') as HTMLElement | null
    expect(box).toBeTruthy()
    expect(box!.textContent?.trim()).toBe('图层库')
    // 内联 top/left 由定位逻辑写入；节点挂在 body（Teleport）
    expect(box!.style.top).toMatch(/px$/)
    expect(box!.style.left).toMatch(/px$/)
    expect(document.body.contains(box!)).toBe(true)

    wrapper.unmount()
  })
})
