/**
 * Canvas 主题色解析工具
 *
 * HTML Canvas 2D Context 的 fillStyle / strokeStyle 不支持 CSS 自定义属性
 * （如 var(--accent)），必须传入字面量颜色值。本模块从 getComputedStyle
 * 读取实际颜色值并提供缓存，在主题切换时自动失效。
 */

/** 缓存：CSS 变量名 → 字面量颜色值 */
let _cache: Record<string, string> = {}
let _cacheTheme = ''

/** 读取 :root 上的 CSS 变量值，失败时返回 fallback */
function readCssVar(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

/** 检查主题是否变化，变化则清空缓存 */
function checkThemeInvalidation() {
  const currentTheme =
    typeof document !== 'undefined'
      ? document.documentElement.getAttribute('data-theme') || 'dark'
      : 'dark'
  if (currentTheme !== _cacheTheme) {
    _cache = {}
    _cacheTheme = currentTheme
  }
}

/**
 * 解析 CSS 变量名为字面量颜色值。
 * 结果会被缓存，直到主题切换（data-theme 属性变化）时自动失效。
 *
 * @param varName CSS 变量名，不含 var()，如 '--accent'
 * @param fallback 解析失败时的回退值
 */
export function resolveCanvasColor(varName: string, fallback = '#0b1a2a'): string {
  checkThemeInvalidation()
  if (_cache[varName]) return _cache[varName]
  const value = readCssVar(varName, fallback)
  _cache[varName] = value
  return value
}

/**
 * 批量解析多个 CSS 变量。
 *
 * @param vars 键值对：逻辑名 → CSS 变量名
 * @param fallbacks 键值对：逻辑名 → 回退值（可选）
 */
export function resolveCanvasColors(
  vars: Record<string, string>,
  fallbacks: Record<string, string> = {},
): Record<string, string> {
  checkThemeInvalidation()
  const result: Record<string, string> = {}
  for (const [key, varName] of Object.entries(vars)) {
    if (_cache[varName]) {
      result[key] = _cache[varName]
    } else {
      const value = readCssVar(varName, fallbacks[key] || '#0b1a2a')
      _cache[varName] = value
      result[key] = value
    }
  }
  return result
}

/** 手动清空缓存（在主题切换回调中调用） */
export function invalidateCanvasThemeCache(): void {
  _cache = {}
  _cacheTheme = ''
}

// ── 预定义颜色组 ─────────────────────────────────────────────────────────────

/** 画布网格和辅助线颜色组 */
export function getGridColors() {
  return resolveCanvasColors(
    {
      minor: '--accent-surface',
      major: '--accent-border',
      guide: '--accent',
    },
    { minor: 'rgba(90, 213, 255, 0.06)', major: 'rgba(90, 213, 255, 0.12)', guide: '#5ad5ff' },
  )
}

/**
 * LiteGraph 画布清屏色（须为不透明字面量；默认 #222 导致浅色主题工作区「卡住」不切换）。
 * 结果会被缓存，直到主题切换时自动失效。
 */
export function getCanvasClearColor(): string {
  checkThemeInvalidation()
  const cacheKey = '__canvas_clear_color__'
  if (_cache[cacheKey]) return _cache[cacheKey]
  const theme =
    typeof document !== 'undefined'
      ? document.documentElement.getAttribute('data-theme') || 'dark'
      : 'dark'
  // 浅色用不透明冷灰蓝；深色贴近 surface-base
  const fallback = theme === 'light' ? '#dce6f0' : '#020814'
  const raw = readCssVar('--surface-base', fallback)
  // rgba 透明清屏会导致残影；尽量落到不透明 hex/rgb
  const result = raw.startsWith('rgba') ? fallback : raw || fallback
  _cache[cacheKey] = result
  return result
}

/** Minimap 颜色组 */
export function getMinimapColors() {
  return resolveCanvasColors(
    {
      bg: '--surface-1',
      pythonProvider: '--success',
      weather: '--warning',
      gee: '--accent',
      default: '--accent-strong',
      viewport: '--warning-border',
    },
    {
      bg: '#0b1a2a',
      pythonProvider: '#0a7a4e',
      weather: '#a55a08',
      gee: '#5ad5ff',
      default: '#3a9fc4',
      viewport: 'rgba(165, 90, 8, 0.3)',
    },
  )
}

/** LiteGraph 节点颜色组 */
export function getLiteGraphColors() {
  return resolveCanvasColors(
    {
      nodeBg: '--surface-2',
      nodeBox: '--accent',
      nodeTitle: '--text-primary',
      nodeText: '--text-secondary',
      selectedTitle: '--warning',
      boxOutline: '--accent',
      link: '--accent',
      connectingLink: '--warning',
      eventLink: '--success',
      linkHover: '--accent-warm',
    },
    {
      nodeBg: '#152538',
      nodeBox: '#5ad5ff',
      nodeTitle: '#e8f0fa',
      nodeText: '#a0b8c8',
      selectedTitle: '#e8a020',
      boxOutline: '#5ad5ff',
      link: '#5ad5ff',
      connectingLink: '#e8a020',
      eventLink: '#0a7a4e',
      linkHover: '#c97a14',
    },
  )
}

/** 端口颜色组（用于 getPortColor） */
export function getPortColors() {
  return resolveCanvasColors(
    {
      data: '--accent',
      dataMat: '--warning',
      dataRaster: '--accent',
      dataGeojson: '--success',
      bbox: '--danger',
      default: '--text-faint',
    },
    {
      data: '#5ad5ff',
      dataMat: '#e8a020',
      dataRaster: '#5ad5ff',
      dataGeojson: '#0a7a4e',
      bbox: '#b8311a',
      default: '#8a9db0',
    },
  )
}
