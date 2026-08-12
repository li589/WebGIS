/**
 * useBreakpoint — 响应式断点 composable
 *
 * 提供 JS 侧的视口断点感知能力，与 tokens.css 中 --bp-* 断点值对齐。
 * CSS @media 查询不支持 CSS 变量（规范限制），因此此处硬编码断点值
 * 并通过注释约束与 tokens.css 保持同步。
 *
 * 须与 tokens.css --bp-sm/md/lg/xl 保持同步：
 *   --bp-sm: 640px  --bp-md: 768px  --bp-lg: 1024px  --bp-xl: 1280px
 */

import { onMounted, onUnmounted, ref, computed } from 'vue'

export const BREAKPOINTS = {
  sm: 640,
  md: 768,
  lg: 1024,
  xl: 1280,
} as const

export type BreakpointKey = keyof typeof BREAKPOINTS

type Breakpoint = BreakpointKey | 'base'

const QUERIES: Record<Breakpoint, string> = {
  base: '(max-width: 639px)',
  sm: '(min-width: 640px) and (max-width: 767px)',
  md: '(min-width: 768px) and (max-width: 1023px)',
  lg: '(min-width: 1024px) and (max-width: 1279px)',
  xl: '(min-width: 1280px)',
}

function matchCurrent(): Breakpoint {
  if (typeof window === 'undefined') return 'lg'
  for (const key of Object.keys(QUERIES) as Breakpoint[]) {
    if (window.matchMedia(QUERIES[key]).matches) return key
  }
  return 'lg'
}

export function useBreakpoint() {
  const current = ref<Breakpoint>(matchCurrent())

  const isMobile = computed(() => current.value === 'base' || current.value === 'sm')
  const isTablet = computed(() => current.value === 'md')
  const isDesktop = computed(() => current.value === 'lg' || current.value === 'xl')

  function smaller(bp: BreakpointKey): boolean {
    const order: Breakpoint[] = ['base', 'sm', 'md', 'lg', 'xl']
    return order.indexOf(current.value) < order.indexOf(bp)
  }

  function greater(bp: BreakpointKey): boolean {
    const order: Breakpoint[] = ['base', 'sm', 'md', 'lg', 'xl']
    return order.indexOf(current.value) > order.indexOf(bp)
  }

  function smallerOrEqual(bp: BreakpointKey): boolean {
    return !greater(bp)
  }

  function greaterOrEqual(bp: BreakpointKey): boolean {
    return !smaller(bp)
  }

  const mqls: MediaQueryList[] = []
  const handlers: Array<() => void> = []

  onMounted(() => {
    if (typeof window === 'undefined') return
    for (const key of Object.keys(QUERIES) as Breakpoint[]) {
      const mql = window.matchMedia(QUERIES[key])
      const handler = (e: MediaQueryListEvent) => {
        if (e.matches) current.value = key
      }
      mql.addEventListener('change', handler)
      mqls.push(mql)
      handlers.push(() => mql.removeEventListener('change', handler))
    }
    // 首次挂载时同步当前值
    current.value = matchCurrent()
  })

  onUnmounted(() => {
    handlers.forEach((fn) => fn())
    mqls.length = 0
    handlers.length = 0
  })

  return {
    current,
    isMobile,
    isTablet,
    isDesktop,
    smaller,
    greater,
    smallerOrEqual,
    greaterOrEqual,
  }
}
