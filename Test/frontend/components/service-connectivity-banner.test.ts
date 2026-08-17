// @vitest-environment jsdom
//
// W8：断联横幅判定去抖回归。
// 此前单次探测失败立即 offline=true——后端高负载时瞬时慢响应即误报断联。
// 现约束：AbortController 8s 超时；连续 3 次失败才亮横幅；任一次成功立即复位；
// document.hidden 时暂停轮询。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { mount } from '@/test-utils'
import ServiceConnectivityBanner from '@/components/ServiceConnectivityBanner.vue'

const fetchMock = vi.fn()

function okResponse(): Response {
  return { ok: true } as unknown as Response
}

function failResponse(): Response {
  return { ok: false, status: 503 } as unknown as Response
}

function banner(wrapper: ReturnType<typeof mount>): boolean {
  return wrapper.find('.connectivity-banner').exists()
}

beforeEach(() => {
  vi.useFakeTimers()
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('ServiceConnectivityBanner 断联判定', () => {
  it('单次失败不亮横幅，连续 3 次失败才判定断联', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('network'))
    fetchMock.mockRejectedValueOnce(new TypeError('network'))
    fetchMock.mockRejectedValueOnce(new TypeError('network'))
    fetchMock.mockRejectedValue(new TypeError('network'))

    const wrapper = mount(ServiceConnectivityBanner)
    await vi.advanceTimersByTimeAsync(10)

    expect(banner(wrapper)).toBe(false)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(30_000)
    expect(banner(wrapper)).toBe(false)
    expect(fetchMock).toHaveBeenCalledTimes(2)

    await vi.advanceTimersByTimeAsync(30_000)
    expect(banner(wrapper)).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(3)
    wrapper.unmount()
  })

  it('任一次成功立即复位并清空失败计数', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('network'))
    fetchMock.mockRejectedValueOnce(new TypeError('network'))
    fetchMock.mockResolvedValueOnce(okResponse())
    fetchMock.mockRejectedValue(new TypeError('network'))

    const wrapper = mount(ServiceConnectivityBanner)
    await vi.advanceTimersByTimeAsync(10)
    await vi.advanceTimersByTimeAsync(30_000)
    expect(banner(wrapper)).toBe(false)

    // 第 3 次探测成功：计数清零
    await vi.advanceTimersByTimeAsync(30_000)
    expect(banner(wrapper)).toBe(false)

    // 成功后再次失败 1 次不应立刻断联（计数已清零）
    await vi.advanceTimersByTimeAsync(30_000)
    expect(fetchMock).toHaveBeenCalledTimes(4)
    expect(banner(wrapper)).toBe(false)
    wrapper.unmount()
  })

  it('非 2xx 响应同样计为失败', async () => {
    fetchMock.mockResolvedValue(failResponse())
    const wrapper = mount(ServiceConnectivityBanner)
    await vi.advanceTimersByTimeAsync(10)
    await vi.advanceTimersByTimeAsync(30_000)
    await vi.advanceTimersByTimeAsync(30_000)
    expect(banner(wrapper)).toBe(true)
    wrapper.unmount()
  })

  it('探测超过 8s 未响应按失败计（AbortController 超时）', async () => {
    fetchMock.mockImplementation(
      (_url: RequestInfo | URL, init?: RequestInit) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () =>
            reject(init.signal?.reason ?? new DOMException('Aborted', 'AbortError')),
          )
        }),
    )

    const wrapper = mount(ServiceConnectivityBanner)
    await vi.advanceTimersByTimeAsync(10)
    // 挂起的探测在 8s 超时后按失败计
    await vi.advanceTimersByTimeAsync(9_000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(banner(wrapper)).toBe(false)

    // 两次 8s 超时后达到阈值
    await vi.advanceTimersByTimeAsync(30_000 + 9_000)
    await vi.advanceTimersByTimeAsync(30_000 + 9_000)
    expect(banner(wrapper)).toBe(true)
    wrapper.unmount()
  })

  it('页面隐藏时暂停轮询，重新可见后恢复', async () => {
    fetchMock.mockResolvedValue(okResponse())
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)

    const wrapper = mount(ServiceConnectivityBanner)
    await vi.advanceTimersByTimeAsync(10)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(120_000)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(10)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(banner(wrapper)).toBe(false)
    wrapper.unmount()
  })
})
