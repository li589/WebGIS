/**
 * 动效偏好（设置 → 外观 → 动效偏好）
 *
 * - localStorage key: `cgda-reduce-motion`
 * - 生效方式：`<html class="reduce-motion">` + CSS 变量压短
 * - 启动时尽早 bootstrap，避免首屏面板入场动画在偏好写入前闪一下
 */

export const REDUCE_MOTION_STORAGE_KEY = 'cgda-reduce-motion'

export function readSystemPrefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** localStorage 优先；无记录时跟随系统 prefers-reduced-motion */
export function resolveReducedMotionPreference(): boolean {
  if (typeof window === 'undefined') return false
  const stored = window.localStorage.getItem(REDUCE_MOTION_STORAGE_KEY)
  if (stored !== null) return stored === 'true'
  return readSystemPrefersReducedMotion()
}

export function applyReducedMotionPreference(enabled: boolean): void {
  if (typeof document === 'undefined') return
  document.documentElement.classList.toggle('reduce-motion', enabled)
}

export function setReducedMotionPreference(enabled: boolean): void {
  applyReducedMotionPreference(enabled)
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(REDUCE_MOTION_STORAGE_KEY, String(enabled))
  }
}

/** 在 Vue mount 前调用，同步首屏 class */
export function bootstrapMotionPreference(): boolean {
  const enabled = resolveReducedMotionPreference()
  applyReducedMotionPreference(enabled)
  return enabled
}

export function isReducedMotionActive(): boolean {
  if (typeof document === 'undefined') return false
  return document.documentElement.classList.contains('reduce-motion')
}
