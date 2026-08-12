// @vitest-environment jsdom
//
// SystemResourceMetrics 资源面板核心行为：
// 1) 挂载时拉取后端资源并渲染 CPU/内存/磁盘
// 2) 后端不可用（API 抛错）时显示错误、不崩
// 3) 页面隐藏时跳过定时刷新（性能约束）
import { beforeEach, describe, expect, it, vi } from 'vitest'
// 经 src 内垫片引入，避免 root 外测试文件直接 bare import 无法解析 node_modules。
import { createPinia, mount, setActivePinia } from '@/test-utils'
import SystemResourceMetrics from '@/components/settings/SystemResourceMetrics.vue'
import { fetchRuntimeResources } from '@/services/settings-api'

vi.mock('@/services/settings-api', () => ({
  fetchRuntimeResources: vi.fn(),
}))

const mockFetch = vi.mocked(fetchRuntimeResources)

const BASE_RESPONSE = {
  updated_at: '2026-08-11T00:00:00Z',
  worker_count: 7,
  system: {
    cpu_percent: 22.3,
    memory_total_mb: 32461.5,
    memory_used_mb: 19370.0,
    memory_percent: 59.7,
    disk_total_mb: 2861159.0,
    disk_used_mb: 2130853.1,
    disk_percent: 74.5,
  },
  processes: [{ pid: 34408, name: 'python.exe', cpu_percent: 1.2, memory_rss_mb: 95.5 }],
}

function flushPromises(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

describe('SystemResourceMetrics 资源面板', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockFetch.mockResolvedValue(BASE_RESPONSE as never)
  })

  it('挂载后拉取后端资源并渲染指标', async () => {
    const wrapper = mount(SystemResourceMetrics)
    await flushPromises()

    expect(mockFetch).toHaveBeenCalledTimes(1)
    const text = wrapper.text()
    expect(text).toContain('前端状态')
    expect(text).toContain('后端状态')
    expect(text).toContain('7 worker 在线')
    expect(text).toContain('22.3%') // 系统 CPU
    expect(text).toContain('60%') // 内存占比（Math.round(59.7)）
    expect(text).toContain('75%') // 磁盘占比（Math.round(74.5)）
    expect(text).toContain('python.exe')
  })

  it('后端 API 失败时显示错误且不崩', async () => {
    mockFetch.mockRejectedValue(new Error('network down'))
    const wrapper = mount(SystemResourceMetrics)
    await flushPromises()

    expect(wrapper.text()).toContain('network down')
    // 组件仍挂载（不抛异常）
    expect(wrapper.find('.resource-card').exists()).toBe(true)
  })

  it('页面隐藏时定时刷新被跳过', async () => {
    // 仅 fake setInterval；保留真实 setTimeout 使 flushPromises 正常工作
    vi.useFakeTimers({ toFake: ['setInterval'] })
    const hiddenSpy = vi
      .spyOn(document, 'visibilityState', 'get')
      .mockReturnValue('hidden')
    const wrapper = mount(SystemResourceMetrics)
    await flushPromises()
    expect(mockFetch).toHaveBeenCalledTimes(1)

    // 前进 60s 触发定时器；页面隐藏 → 不发起新请求
    await vi.advanceTimersByTimeAsync(60_000)
    expect(mockFetch).toHaveBeenCalledTimes(1)

    hiddenSpy.mockRestore()
    wrapper.unmount()
    vi.useRealTimers()
  })

  it('页面可见时定时刷新正常拉取', async () => {
    vi.useFakeTimers({ toFake: ['setInterval'] })
    const wrapper = mount(SystemResourceMetrics)
    await flushPromises()
    expect(mockFetch).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(60_000)
    expect(mockFetch).toHaveBeenCalledTimes(2)

    wrapper.unmount()
    vi.useRealTimers()
  })
})
