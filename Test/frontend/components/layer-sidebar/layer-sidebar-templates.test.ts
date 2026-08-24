// @vitest-environment jsdom
//
// 图层平台子系统 P2-1：课题组模板区组件测试。
// 渲染分支（空列表不渲染 / 卡片字段 / pending 态禁用）+ run-template 事件。
import { describe, expect, it } from 'vitest'

import { mount } from '@/test-utils'
import LayerSidebarTemplates from '@/components/layer-sidebar/LayerSidebarTemplates.vue'
import type { WorkflowTemplateSummary } from '@/services/runtime-api'

function makeTpl(overrides: Partial<WorkflowTemplateSummary> = {}): WorkflowTemplateSummary {
  return {
    workflow_id: 'lab.test',
    name: '测试模板',
    description: '用于验证的模板',
    engine: 'python_provider',
    linked_layer_id: 'aridity-cn',
    auto_display: true,
    resource_profile: 'standard',
    ...overrides,
  } as WorkflowTemplateSummary
}

describe('LayerSidebarTemplates 课题组模板区（P2-1）', () => {
  it('空模板列表不渲染', () => {
    const wrapper = mount(LayerSidebarTemplates, {
      props: { templates: [], submittingIds: new Set() },
    })
    expect(wrapper.find('.template-section').exists()).toBe(false)
  })

  it('渲染模板卡片：名称/引擎徽标/关联图层/运行按钮', () => {
    const wrapper = mount(LayerSidebarTemplates, {
      props: { templates: [makeTpl()], submittingIds: new Set() },
    })
    const card = wrapper.find('[data-testid="lab-template-lab.test"]')
    expect(card.exists()).toBe(true)
    expect(wrapper.find('.template-card-name').text()).toBe('测试模板')
    expect(wrapper.find('.template-card-engine').text()).toBe('算法引擎')
    expect(wrapper.find('.template-card-linked').text()).toContain('aridity-cn')
    const btn = wrapper.find('.template-run-btn')
    expect(btn.text()).toContain('运行')
    expect(btn.attributes('disabled')).toBeUndefined()
  })

  it('无关联图层显示「仅运行」', () => {
    const wrapper = mount(LayerSidebarTemplates, {
      props: { templates: [makeTpl({ linked_layer_id: null })], submittingIds: new Set() },
    })
    expect(wrapper.find('.template-card-linked.none').text()).toBe('仅运行')
  })

  it('点击运行按钮 emit runTemplate(workflow_id)', async () => {
    const wrapper = mount(LayerSidebarTemplates, {
      props: { templates: [makeTpl()], submittingIds: new Set() },
    })
    await wrapper.find('.template-run-btn').trigger('click')
    expect(wrapper.emitted('runTemplate')).toEqual([['lab.test']])
  })

  it('提交中的模板按钮禁用且文案变化', async () => {
    const wrapper = mount(LayerSidebarTemplates, {
      props: { templates: [makeTpl()], submittingIds: new Set(['lab.test']) },
    })
    const btn = wrapper.find('.template-run-btn')
    expect(btn.attributes('disabled')).toBeDefined()
    expect(btn.text()).toContain('提交中')
    await btn.trigger('click')
    expect(wrapper.emitted('runTemplate')).toBeUndefined()
  })
})
