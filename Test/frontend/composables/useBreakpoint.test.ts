import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { BREAKPOINTS } from '@/composables/useBreakpoint'

describe('useBreakpoint', () => {
  it('BREAKPOINTS 常量与 tokens.css --bp-* 对齐', () => {
    expect(BREAKPOINTS.sm).toBe(640)
    expect(BREAKPOINTS.md).toBe(768)
    expect(BREAKPOINTS.lg).toBe(1024)
    expect(BREAKPOINTS.xl).toBe(1280)
  })
})

describe('useBreakpoint matchMedia 集成', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  /**
   * useBreakpoint 内部通过 onMounted/onUnmounted 注册监听器，
   * 在无组件上下文时 lifecycle hooks 不会触发，但 matchCurrent()
   * 会在 composable 初始化时立即执行。通过 stub window.matchMedia
   * 验证初始断点计算逻辑。
   */
  it('桌面宽度返回 isDesktop=true', async () => {
    // 提供 window 环境并模拟 1024px 宽度
    vi.stubGlobal('window', {
      matchMedia: (query: string) => ({
        matches: query.includes('min-width: 1024px') && !query.includes('max-width'),
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    })

    const { useBreakpoint } = await import('@/composables/useBreakpoint')
    const bp = useBreakpoint()

    // matchCurrent() 应返回 'lg'（1024px 匹配 lg 断点）
    expect(bp.isDesktop.value).toBe(true)
    expect(bp.isMobile.value).toBe(false)
  })

  it('移动宽度返回 isMobile=true', async () => {
    // 提供 window 环境并模拟移动宽度
    vi.stubGlobal('window', {
      matchMedia: (query: string) => ({
        matches: query.includes('max-width: 639px'),
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    })

    const { useBreakpoint } = await import('@/composables/useBreakpoint')
    const bp = useBreakpoint()

    // matchCurrent() 应返回 'base'（max-width: 639px 匹配 base 断点）
    expect(bp.isMobile.value).toBe(true)
    expect(bp.isDesktop.value).toBe(false)
  })
})
