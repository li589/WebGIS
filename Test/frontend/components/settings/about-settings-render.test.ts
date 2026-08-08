// @vitest-environment jsdom
//
// 发布就绪修复（P0-11）：建立前端组件渲染回归网的首个用例。
// 此前 Test/frontend 446 个用例全为纯 TS 模块逻辑测试，无任何 .vue 挂载渲染测试，
// 模板绑定 / props / v-if 分支 / 空态无自动化覆盖。本文件以 AboutSettings（架构树无条件渲染、
// 其余区块依赖 store.aboutInfo 空态）为例，验证 @vue/test-utils + jsdom 渲染链路可用。
import { describe, expect, it } from 'vitest'
// 经 src 内垫片引入，避免 root 外测试文件直接 bare import 无法解析 node_modules。
import { createPinia, mount, setActivePinia } from '@/test-utils'
import AboutSettings from '@/components/settings/AboutSettings.vue'

describe('AboutSettings 组件渲染', () => {
  it('无 aboutInfo 时渲染架构树并显示加载占位', () => {
    setActivePinia(createPinia())
    const wrapper = mount(AboutSettings)

    // 架构树无条件渲染（v-for 绑定正常）
    const text = wrapper.text()
    expect(text).toContain('前端层')
    expect(text).toContain('后端层')
    expect(text).toContain('引擎层')
    expect(text).toContain('数据层')

    // aboutInfo 为 null → v-if 空态分支显示"加载中"
    expect(wrapper.find('.loading-hint').exists()).toBe(true)
    expect(wrapper.find('.loading-hint').text()).toContain('加载中')
  })

  it('点击架构节点切换 selected 选中态', async () => {
    setActivePinia(createPinia())
    const wrapper = mount(AboutSettings)

    const node = wrapper.find('.arch-node.level-1')
    expect(node.exists()).toBe(true)
    expect(node.classes()).not.toContain('selected')

    await node.trigger('click')
    expect(node.classes()).toContain('selected')

    // 再次点击取消选中
    await node.trigger('click')
    expect(node.classes()).not.toContain('selected')
  })
})
