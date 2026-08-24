// @vitest-environment jsdom
//
// W3：图层条目拖拽手柄化回归。
// 此前整条 <li> draggable + user-select:none——鼠标在名称上拖动即拖走整个条目、文字不可选。
// 现约束：draggable 仅存在于 .drag-handle-wrap；图层名/组标题放开文本选择；
// 手柄 dragstart 仍触发既有 onDragStart/onGroupDragStart 事件。
import { describe, expect, it } from 'vitest'

import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { mount } from '@/test-utils'
import LayerSidebarActive from '@/components/layer-sidebar/LayerSidebarActive.vue'
import type { ActiveTocRow } from '@/components/layer-sidebar/useSidebarDragReorder'
import type { ActiveLayerDisplay } from '@/stores/layers/types'

// vitest 由 Code/frontend 启动（vite root），cwd 即 root
const styles = readFileSync(
  join(process.cwd(), 'src/components/layer-sidebar/LayerSidebar.styles.css'),
  'utf-8',
)

function makeLayer(overrides: Partial<ActiveLayerDisplay> = {}): ActiveLayerDisplay {
  return {
    instanceId: 'inst-1',
    catalogId: 'catalog-1',
    name: '柯本气候分类',
    runGroupId: 'grp-1',
    visible: true,
    ...overrides,
  } as ActiveLayerDisplay
}

const layer = makeLayer()

const rows: ActiveTocRow[] = [
  { kind: 'group', groupId: 'grp-1', key: 'g-grp-1' },
  { kind: 'layer', layer, key: 'inst-1', indented: true },
]

const mountSidebarProps = {
  activeLayersDisplay: [layer],
  activeTocRows: rows,
  selectedInstanceId: 'inst-1',
  dragOverInstanceId: null,
  dragOverGroupId: null,
  runGroupOf: (groupId: string) =>
    groupId === 'grp-1'
      ? ({
          groupId: 'grp-1',
          title: '运行组',
          status: 'ready',
          memberInstanceIds: ['inst-1'],
        } as never)
      : null,
  groupStatusLabel: () => '就绪',
  hasColorSymbology: () => false,
  getColorRampStyle: () => ({}),
  getSymbologyUnit: () => '',
  getSymbologyVmin: () => '',
  getSymbologyVmax: () => '',
  availabilityClass: () => 'ok',
  getCategoryName: () => '辅助数据',
  supportsOnlineTemporal: () => false,
}

function mountSidebar() {
  return mount(LayerSidebarActive, {
    props: mountSidebarProps,
  })
}

describe('LayerSidebarActive 拖拽手柄化', () => {
  it('图层条目与组头本身不可拖拽，仅手柄容器 draggable', () => {
    const wrapper = mountSidebar()

    const item = wrapper.find('.layer-item')
    expect(item.exists()).toBe(true)
    expect(item.attributes('draggable')).toBeUndefined()

    const groupHeader = wrapper.find('.layer-group-header')
    expect(groupHeader.exists()).toBe(true)
    expect(groupHeader.attributes('draggable')).toBeUndefined()

    const handles = wrapper.findAll('.drag-handle-wrap')
    expect(handles.length).toBe(2)
    for (const handle of handles) {
      expect(handle.attributes('draggable')).toBe('true')
    }
  })

  it('手柄 dragstart 触发排序/组拖拽事件（条目主体不触发）', async () => {
    const wrapper = mountSidebar()

    const itemHandle = wrapper.find('.layer-item .drag-handle-wrap')
    await itemHandle.trigger('dragstart')
    expect(wrapper.emitted('onDragStart')).toEqual([['inst-1']])

    const groupHandle = wrapper.find('.layer-group-header .drag-handle-wrap')
    await groupHandle.trigger('dragstart')
    const groupEvents = wrapper.emitted('onGroupDragStart')
    expect(groupEvents?.[0]?.[0]).toBe('grp-1')
  })

  it('图层名与组标题放开文本选择（不继承 user-select:none）', () => {
    const wrapper = mountSidebar()

    const name = wrapper.find('.layer-name')
    expect(name.text()).toBe('柯本气候分类')
    const title = wrapper.find('.group-title')
    expect(title.exists()).toBe(true)
  })

  it('样式表不再对条目主体设置 user-select:none，且手柄与名称选择策略正确', () => {
    const block = (selector: string): string => {
      const match = styles.match(new RegExp(`${selector.replace('.', '\\.')}\\s*{([^{]*)}`))
      return match?.[1] ?? ''
    }

    expect(block('.layer-item')).not.toContain('user-select')
    expect(block('.layer-group-header')).not.toContain('user-select')
    expect(block('.drag-handle-wrap')).toContain('user-select: none')
    expect(block('.layer-name')).toContain('user-select: text')
    expect(block('.group-title')).toContain('user-select: text')
  })
})

describe('LayerSidebarActive 生命周期徽标（图层平台子系统 P1）', () => {
  it('getLifecycleBadge 返回状态时渲染徽标', () => {
    const wrapper = mount(LayerSidebarActive, {
      props: {
        ...(mountSidebarProps as Record<string, unknown>),
        getLifecycleBadge: (catalogId: string) =>
          catalogId === 'catalog-1'
            ? { state: 'updating', label: '更新中', message: '图层资产正在检查或更新。' }
            : null,
      },
    })
    const badge = wrapper.find('.lifecycle-badge')
    expect(badge.exists()).toBe(true)
    expect(badge.classes()).toContain('lifecycle-badge-updating')
    expect(badge.text()).toBe('更新中')
  })

  it('getLifecycleBadge 未传或返回 null 时不渲染徽标', () => {
    const withoutProp = mountSidebar()
    expect(withoutProp.find('.lifecycle-badge').exists()).toBe(false)

    const withNull = mount(LayerSidebarActive, {
      props: {
        ...(mountSidebarProps as Record<string, unknown>),
        getLifecycleBadge: () => null,
      },
    })
    expect(withNull.find('.lifecycle-badge').exists()).toBe(false)
  })
})
