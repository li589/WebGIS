/**
 * hex → Token 映射表（UI 装饰色专用）
 *
 * 单一真源：供审计脚本（audit-ui-tokens.mjs）、ESLint 自定义规则、
 * 和手动迁移共同引用。数据可视化语义色不在此表中（见豁免清单）。
 *
 * 使用方式：
 *   import { TOKEN_MAP, lookupToken } from '@/styles/token-map'
 *   const token = lookupToken('#5ad5ff') // → 'var(--accent)'
 */

// ═══ 豁免清单：数据可视化 / 第三方库文件（不迁移） ═══
export const EXEMPT_PATHS = [
  'src/components/map/weather-render.ts',
  'src/components/map/layer-symbology.ts',
  'src/components/map/wind-particle-webgl-shaders.ts',
  'src/components/map/scalar-field-webgl-shaders.ts',
  'src/components/map/wind-particle-webgl-texture.ts',
  'src/components/map/scalar-field-webgl-texture.ts',
  'src/components/map/scalar-field-webgl-renderer.ts',
  'src/components/map/scalar-field-webgl-controller.ts',
  'src/components/map/wind-particle-canvas.ts',
  'src/components/map/weather-overlay-renderers.ts',
  'src/components/map/measure-canvas.ts',
  'src/components/map/measure-module.ts',
  'src/components/map/map-chrome-controls.ts',
  'src/components/map/map-stage-view-model.ts',
  'src/components/map/admin-boundary-module.ts',
  'src/components/map/imported-layer-module.ts',
  'src/components/workflow/litegraph-ui-overrides.css',
  'src/components/workflow/litegraph-setup.ts',
  'src/components/info-panel/useLayerSymbology.ts',
  'src/stores/layers/catalog.ts',
  'src/stores/layers/catalog-builders.ts',
  'src/stores/layers/catalog-runtime.ts',
  'src/stores/layers/layer-accent.ts',
  'src/stores/layers/display-projection.ts',
  'src/stores/layers/active-layers.ts',
  'src/styles/tokens.css',
] as const

// ═══ hex → token 映射 ═══
// 格式：[normalizedHex, tokenName, semanticRole]
// normalizedHex 为小写无 # 前缀的 6 位 hex
export interface TokenMapping {
  /** 小写无 # 的 hex（如 '5ad5ff'） */
  hex: string
  /** CSS 自定义属性名（如 '--accent'） */
  token: string
  /** 语义角色说明 */
  role: string
}

export const TOKEN_MAP: TokenMapping[] = [
  // ── 文本色 ──
  { hex: 'f0faff', token: '--text-strong', role: '最亮文本/标题' },
  { hex: 'd8e6f5', token: '--text-primary', role: '正文/默认' },
  { hex: 'dfeefe', token: '--text-primary', role: '正文（近似）' },
  { hex: 'd5e5f5', token: '--text-primary', role: '正文（近似）' },
  { hex: 'd9ebfb', token: '--text-primary', role: '正文（近似）' },
  { hex: '9fb6cc', token: '--text-secondary', role: '辅助文本' },
  { hex: '8aa8bf', token: '--text-muted', role: '第三层文本' },
  { hex: '8cb5d9', token: '--text-muted', role: '第三层文本（近似）' },
  { hex: '6e8ba0', token: '--text-faint', role: '极淡文本' },
  { hex: '5a7080', token: '--text-disabled', role: '禁用态文本' },

  // ── 品牌 / 强调 ──
  { hex: '5ad5ff', token: '--accent', role: '主品牌色（亮青）' },
  { hex: '88dfff', token: '--accent-strong', role: '强调色（更亮）' },
  { hex: 'ffc878', token: '--accent-warm', role: '暖强调（橙）' },
  { hex: '2f7eff', token: '--accent-blue-deep', role: 'brand-mark 渐变深色端' },

  // ── 工作流端口语义色 ──
  { hex: 'ff8fb1', token: '--port-time', role: '时间范围端口' },
  { hex: 'ffd5a8', token: '--port-numeric', role: '数值端口' },
  { hex: 'ffe08a', token: '--port-text', role: '文本端口' },
  { hex: 'c084fc', token: '--recent-accent', role: '最近使用分类组强调色' },

  // ── 语义色 ──
  { hex: '9ff8cf', token: '--success', role: '成功' },
  { hex: 'ffb070', token: '--warning', role: '警告' },
  { hex: 'ff8c64', token: '--danger', role: '危险/错误' },

  // ── 表面层 ──
  { hex: '020814', token: '--surface-base', role: '最底背景' },
  { hex: '040c17', token: '--surface-sunken', role: '低/凹陷容器' },
  { hex: '08111f', token: '--surface-1', role: '浮层底' },
  { hex: '0d1727', token: '--surface-2', role: '面板壳/对话框' },
  { hex: '121e30', token: '--surface-3', role: '最高/Tooltip' },
  { hex: '142842', token: '--surface-hover', role: '交互态/Hover' },

  // ── 浅色主题色 ──
  { hex: '0a1626', token: '--text-strong', role: '浅色主题最亮文本' },
  { hex: '1a2b42', token: '--text-primary', role: '浅色主题正文' },
  { hex: '4a6076', token: '--text-secondary', role: '浅色主题辅助' },
  { hex: '6b8094', token: '--text-muted', role: '浅色主题第三层' },
  { hex: '0a8fc4', token: '--accent', role: '浅色主题品牌色' },
  { hex: '00709e', token: '--accent-strong', role: '浅色主题强调' },
  { hex: 'c97a14', token: '--accent-warm', role: '浅色主题暖强调' },
  { hex: 'eef2f7', token: '--surface-base', role: '浅色主题背景' },
]

// ═══ rgba → token 映射 ═══
// 格式：[normalizedRgba, tokenName, semanticRole]
export interface RgbaMapping {
  /** 标准化 rgba 字符串（如 'rgba(8,17,31,0.86)'） */
  rgba: string
  token: string
  role: string
}

export const RGBA_MAP: RgbaMapping[] = [
  // ── 表面层 rgba ──
  { rgba: 'rgba(4,12,23,0.5)', token: '--surface-sunken', role: '凹陷容器' },
  { rgba: 'rgba(8,17,31,0.86)', token: '--surface-1', role: '浮层底' },
  { rgba: 'rgba(8,17,31,0.92)', token: '--surface-1', role: '浮层底（高透明）' },
  { rgba: 'rgba(8,17,31,0.96)', token: '--surface-1', role: '浮层底（接近不透明）' },
  { rgba: 'rgba(13,23,39,0.92)', token: '--surface-2', role: '面板壳' },
  { rgba: 'rgba(13,23,39,0.96)', token: '--surface-2', role: '面板壳（高透明）' },
  { rgba: 'rgba(18,30,48,0.96)', token: '--surface-3', role: '最高层' },
  { rgba: 'rgba(20,40,66,0.98)', token: '--surface-hover', role: 'Hover 态' },
  { rgba: 'rgba(4,12,23,0.6)', token: '--surface-raised', role: '兼容旧名 raised' },
  { rgba: 'rgba(12,22,38,0.65)', token: '--surface-1', role: '浮层底（近似）' },

  // ── 边框 rgba ──
  { rgba: 'rgba(136,192,255,0.08)', token: '--border-subtle', role: '极淡边框' },
  { rgba: 'rgba(136,192,255,0.16)', token: '--border-default', role: '默认边框' },
  { rgba: 'rgba(90,213,255,0.36)', token: '--border-strong', role: '重/聚焦边框' },
  { rgba: 'rgba(90,213,255,0.28)', token: '--border-accent', role: '强调边框' },

  // ── Accent rgba ──
  { rgba: 'rgba(90,213,255,0.12)', token: '--accent-surface', role: '强调表面' },
  { rgba: 'rgba(90,213,255,0.3)', token: '--accent-border', role: '强调边框' },
  { rgba: 'rgba(90,213,255,0.1)', token: '--accent-focus-ring', role: '焦点环' },

  // ── 语义色 rgba ──
  { rgba: 'rgba(159,248,207,0.12)', token: '--success-surface', role: '成功表面' },
  { rgba: 'rgba(159,248,207,0.3)', token: '--success-border', role: '成功边框' },
  { rgba: 'rgba(255,176,112,0.12)', token: '--warning-surface', role: '警告表面' },
  { rgba: 'rgba(255,176,112,0.3)', token: '--warning-border', role: '警告边框' },
  { rgba: 'rgba(255,140,100,0.12)', token: '--danger-surface', role: '危险表面' },
  { rgba: 'rgba(255,140,100,0.3)', token: '--danger-border', role: '危险边框' },

  // ── 品牌深色 / 暖强调 / 徽章 rgba ──
  { rgba: 'rgba(47,126,255,0.28)', token: '--accent-blue-deep-glow', role: '品牌辉光阴影' },
  { rgba: 'rgba(255,200,120,0.12)', token: '--accent-warm-surface', role: '暖强调表面' },
  { rgba: 'rgba(255,200,120,0.35)', token: '--accent-warm-border', role: '暖强调边框' },
  { rgba: 'rgba(8,20,36,0.9)', token: '--badge-ring', role: '徽章外环' },
]

// ═══ 查找工具函数 ═══

/** 将 hex 字符串标准化为小写无 # 的 6 位格式 */
export function normalizeHex(input: string): string | null {
  const cleaned = input.replace(/^#/, '').toLowerCase()
  if (/^[0-9a-f]{6}$/.test(cleaned)) return cleaned
  if (/^[0-9a-f]{3}$/.test(cleaned)) {
    return cleaned
      .split('')
      .map((c) => c + c)
      .join('')
  }
  if (/^[0-9a-f]{8}$/.test(cleaned)) return cleaned.slice(0, 6) // 去掉 alpha
  return null
}

/** 将 rgba() 字符串标准化 */
export function normalizeRgba(input: string): string | null {
  const match = input.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)/i)
  if (!match) return null
  const [, r, g, b, a] = match
  if (a !== undefined) {
    return `rgba(${r},${g},${b},${a})`
  }
  return `rgba(${r},${g},${b},1)`
}

/** 根据 hex 值查找对应 token */
export function lookupToken(hexOrRgba: string): string | null {
  // 尝试 hex 查找
  const hex = normalizeHex(hexOrRgba)
  if (hex) {
    const found = TOKEN_MAP.find((m) => m.hex === hex)
    if (found) return `var(${found.token})`
  }

  // 尝试 rgba 查找
  const rgba = normalizeRgba(hexOrRgba)
  if (rgba) {
    const found = RGBA_MAP.find((m) => m.rgba === rgba)
    if (found) return `var(${found.token})`
  }

  return null
}

/** 判断文件路径是否在豁免清单中 */
export function isExempt(filePath: string): boolean {
  return EXEMPT_PATHS.some((p) => filePath.replace(/\\/g, '/').endsWith(p))
}
