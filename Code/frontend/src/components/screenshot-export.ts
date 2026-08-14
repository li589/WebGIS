/**
 * Screenshot capture helpers — map WebGL + DOM overlays via html2canvas.
 *
 * html2canvas cannot read WebGL reliably and mishandles CSS transform /
 * backdrop-filter / flex margin-left: auto. We capture the map canvas FIRST,
 * then let html2canvas clone the DOM, pin overlay elements and absolute-position
 * toolbar main controls in the clone, hide map canvases in the clone, and composite
 * the map snapshot under the UI canvas in three clean layers:
 * Base Color -> Map Snapshot -> UI Canvas.
 */

export type ScreenshotMode = 'shell' | 'bare' | 'clean' | 'pure'
export type ScreenshotFormat = 'png' | 'pdf'

/**
 * 将 CSS 自定义属性（如 var(--surface-1)）解析为字面量颜色值。
 * Canvas 2D Context 的 fillStyle 不支持 CSS 变量，必须传入实际颜色。
 */
function resolveCssColor(varName: string, fallback = '#0b1a2a'): string {
  if (typeof document === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(varName).trim()
  return value || fallback
}

export const MAP_CANVAS_SELECTORS = [
  '.maplibregl-canvas-container',
  '.maplibregl-canvas',
  '.maplibregl-map',
  '.wind-particle-webgl-canvas',
  '.scalar-field-webgl-canvas',
  '.wind-particle-canvas',
  '.wind-contour-canvas',
  '.wind-barb-canvas',
  '.scalar-contour-canvas',
] as const

export const CLEAN_IGNORE_SELECTORS = [
  '.overlay',
  '.map-overlay',
  '.map-note',
  '.tile-load-error',
  '.map-loading',
  '.map-skeleton',
  '.maplibregl-ctrl-bottom-right',
  '.maplibregl-ctrl-bottom-left',
] as const

export const PURE_IGNORE_SELECTORS = [
  ...CLEAN_IGNORE_SELECTORS,
  '.map-fog',
  '.time-sheen',
  '.time-band',
  '.weather-overlay',
  '.grid-overlay',
  '.basemap-transition-mask',
] as const

/** Container panel cards whose computed paint is copied to the clone. (Inner flex items are omitted to prevent duplication). */
export const STYLE_BAKE_SELECTORS = [
  '.toolbar',
  '.panel-dock__frame',
  '.panel-anchor',
  '.info-panel',
  '.layer-sidebar',
] as const

/** Elements that use transform / centered absolute layout and break html2canvas. */
export const PIN_OVERLAY_SELECTORS = ['.overlay'] as const
export const PIN_PANEL_SELECTORS = ['.panel-dock__frame', '.panel-anchor'] as const

export type MapSnapshot = {
  dataUrl: string
  dx: number
  dy: number
  dw: number
  dh: number
}

export function matchesAnySelector(el: HTMLElement, selectors: readonly string[]): boolean {
  return selectors.some((selector) => {
    try {
      return el.matches(selector) || !!el.closest(selector)
    } catch {
      return false
    }
  })
}

export function resolveCaptureElement(
  mode: ScreenshotMode,
  els: {
    dashboardEl: HTMLElement | null
    mapShellEl: HTMLElement | null
    mapStageEl: HTMLElement | null
  },
): HTMLElement | null {
  if (!els.mapStageEl) return null
  if (mode === 'shell') {
    return els.dashboardEl ?? els.mapShellEl ?? els.mapStageEl
  }
  if (mode === 'bare' || mode === 'clean') {
    return els.mapShellEl ?? els.mapStageEl
  }
  return els.mapStageEl
}

/**
 * Pin transform-based / centered overlays to absolute boxes **in the clone only**.
 * This avoids mutating the live DOM and prevents layout jank.
 */
function pinElementToOriginInClone(el: HTMLElement): void {
  const left = parseFloat(el.getAttribute('data-capture-left') || '0')
  const top = parseFloat(el.getAttribute('data-capture-top') || '0')
  const width = parseFloat(el.getAttribute('data-capture-width') || '0')
  const height = parseFloat(el.getAttribute('data-capture-height') || '0')

  if (width < 1 || height < 1) return

  el.style.setProperty('position', 'absolute', 'important')
  el.style.setProperty('left', `${left}px`, 'important')
  el.style.setProperty('top', `${top}px`, 'important')
  el.style.setProperty('right', 'auto', 'important')
  el.style.setProperty('bottom', 'auto', 'important')
  el.style.setProperty('inset', 'auto', 'important')
  el.style.setProperty('transform', 'none', 'important')
  el.style.setProperty('width', `${width}px`, 'important')
  el.style.setProperty('height', `${height}px`, 'important')
  el.style.setProperty('margin', '0', 'important')
}

/**
 * Stamp layout measurements from the live DOM onto data attributes.
 * These are read by pinElementToOriginInClone in the onclone callback.
 * Returns a cleanup function to remove the data attributes.
 */
export function stampLayoutMeasurements(root: HTMLElement): () => void {
  const rootRect = root.getBoundingClientRect()
  const stamped: HTMLElement[] = []

  root.querySelectorAll(PIN_OVERLAY_SELECTORS.join(',')).forEach((node) => {
    const el = node as HTMLElement
    const rect = el.getBoundingClientRect()
    if (rect.width < 1 || rect.height < 1) return
    el.setAttribute('data-capture-left', String(rect.left - rootRect.left))
    el.setAttribute('data-capture-top', String(rect.top - rootRect.top))
    el.setAttribute('data-capture-width', String(rect.width))
    el.setAttribute('data-capture-height', String(rect.height))
    stamped.push(el)
  })

  root.querySelectorAll(PIN_PANEL_SELECTORS.join(',')).forEach((node) => {
    const el = node as HTMLElement
    const parent = (el.offsetParent as HTMLElement | null) ?? root
    const parentRect = parent.getBoundingClientRect()
    const rect = el.getBoundingClientRect()
    if (rect.width < 1 || rect.height < 1) return
    el.setAttribute('data-capture-left', String(rect.left - parentRect.left))
    el.setAttribute('data-capture-top', String(rect.top - parentRect.top))
    el.setAttribute('data-capture-width', String(rect.width))
    el.setAttribute('data-capture-height', String(rect.height))
    stamped.push(el)
  })

  return () => {
    for (const el of stamped) {
      el.removeAttribute('data-capture-left')
      el.removeAttribute('data-capture-top')
      el.removeAttribute('data-capture-width')
      el.removeAttribute('data-capture-height')
    }
  }
}

/** Legacy alias kept for backward compat — stamps measurements. */
export function pinLayoutsForCapture(root: HTMLElement): () => void {
  return stampLayoutMeasurements(root)
}

/**
 * html2canvas cannot parse CSS Color Level 4 / color-mix.
 * Prefer browser-resolved rgb/rgba from getComputedStyle; strip unsafe values.
 */
const UNSUPPORTED_CSS_COLOR_RE = /\b(?:color-mix|color|lab|lch|oklab|oklch|hwb)\s*\(/i

export function sanitizeCssColorForHtml2Canvas(value: string | null | undefined): string {
  if (!value) return ''
  const trimmed = value.trim()
  if (!trimmed || trimmed === 'none' || trimmed === 'transparent') return trimmed
  if (UNSUPPORTED_CSS_COLOR_RE.test(trimmed)) {
    return ''
  }
  return trimmed
}

function copyPaintFromComputed(style: CSSStyleDeclaration): Array<[string, string]> {
  const safeColor = sanitizeCssColorForHtml2Canvas(style.color)
  const safeBg = sanitizeCssColorForHtml2Canvas(style.backgroundColor)
  const props: Array<[string, string]> = [
    ['box-shadow', style.boxShadow],
    ['border', style.border],
    ['border-radius', style.borderRadius],
    ['color', safeColor],
    ['opacity', style.opacity],
    ['outline', style.outline],
  ]
  // Flatten glassmorphism — html2canvas ignores backdrop-filter.
  props.push(['backdrop-filter', 'none'])
  props.push(['-webkit-backdrop-filter', 'none'])
  props.push(['filter', style.filter === 'none' ? 'none' : style.filter])

  // Provide a clean translucent background for UI panels.
  const isClear =
    !safeBg ||
    safeBg === 'transparent' ||
    safeBg === 'var(--surface-sunken)' ||
    safeBg === 'var(--surface-sunken)'
  if (isClear && style.backdropFilter && style.backdropFilter !== 'none') {
    props.push(['background-color', 'var(--surface-1)'])
    props.push(['background-image', 'none'])
  } else if (safeBg) {
    props.push(['background-color', safeBg])
  }
  return props
}

function scrubStyleDeclaration(style: CSSStyleDeclaration): void {
  for (let i = style.length - 1; i >= 0; i -= 1) {
    const prop = style.item(i)
    if (!prop) continue
    const value = style.getPropertyValue(prop)
    if (value && UNSUPPORTED_CSS_COLOR_RE.test(value)) {
      style.removeProperty(prop)
    }
  }
}

function scrubCssRules(rules: CSSRuleList): void {
  for (let i = rules.length - 1; i >= 0; i -= 1) {
    const rule = rules.item(i)
    if (!rule) continue
    if (rule instanceof CSSStyleRule) {
      scrubStyleDeclaration(rule.style)
      continue
    }
    // @media / @supports / @layer groupings
    const grouped = rule as CSSGroupingRule
    if (typeof grouped.cssRules !== 'undefined') {
      try {
        scrubCssRules(grouped.cssRules)
      } catch {
        // ignore unreadable nested rules
      }
    }
  }
}

/**
 * Neutralize unsupported color functions in clone stylesheets + inline styles.
 * html2canvas reads raw CSS text (including `color-mix(...)`) and throws.
 */
export function scrubUnsupportedCssColorsInClone(root: HTMLElement | Document): void {
  const COLOR_PROPS = [
    'color',
    'background-color',
    'border-color',
    'border-top-color',
    'border-right-color',
    'border-bottom-color',
    'border-left-color',
    'outline-color',
    'fill',
    'stroke',
    'box-shadow',
    'text-shadow',
    'background',
    'border',
    'outline',
  ] as const

  const isElement = (node: unknown): node is HTMLElement =>
    !!node &&
    typeof node === 'object' &&
    'style' in (node as object) &&
    typeof (node as HTMLElement).style?.getPropertyValue === 'function'

  const visit = (el: HTMLElement) => {
    for (const prop of COLOR_PROPS) {
      const inline = el.style.getPropertyValue(prop)
      if (inline && UNSUPPORTED_CSS_COLOR_RE.test(inline)) {
        el.style.removeProperty(prop)
      }
    }
    // Catch any other inline property carrying color-mix / color()
    scrubStyleDeclaration(el.style)
  }

  if (isElement(root)) visit(root)
  const nodes =
    typeof (root as Document).querySelectorAll === 'function'
      ? (root as Document | HTMLElement).querySelectorAll('*')
      : []
  nodes.forEach((node) => {
    if (isElement(node)) visit(node)
  })

  const doc =
    typeof Document !== 'undefined' && root instanceof Document
      ? root
      : isElement(root)
        ? root.ownerDocument
        : null
  if (!doc) return

  // Rewrite <style> text — CSSOM scrub alone is unreliable with Vue scoped sheets.
  doc.querySelectorAll?.('style').forEach((node) => {
    const el = node as HTMLStyleElement
    const css = el.textContent || ''
    if (!UNSUPPORTED_CSS_COLOR_RE.test(css)) return
    el.textContent = stripUnsupportedColorFunctionsFromCss(css)
  })

  const sheets = doc.styleSheets
  if (!sheets) return
  for (const sheet of Array.from(sheets)) {
    try {
      if (sheet.cssRules) scrubCssRules(sheet.cssRules)
    } catch {
      // Cross-origin / unreadable sheets — ignore
    }
  }
}

/** Replace color-mix()/color()/oklch() tokens with transparent (paren-balanced). */
export function stripUnsupportedColorFunctionsFromCss(css: string): string {
  const names = ['color-mix', 'oklch', 'oklab', 'lab', 'lch', 'hwb', 'color']
  let out = css
  for (const name of names) {
    const lower = out.toLowerCase()
    const token = `${name}(`
    let i = 0
    let built = ''
    while (i < out.length) {
      const idx = lower.indexOf(token, i)
      if (idx === -1) {
        built += out.slice(i)
        break
      }
      // Don't treat color-mix as color(
      if (name === 'color' && lower.slice(idx, idx + 'color-mix('.length) === 'color-mix(') {
        built += out.slice(i, idx + 1)
        i = idx + 1
        continue
      }
      built += out.slice(i, idx)
      let depth = 0
      let j = idx + token.length - 1
      for (; j < out.length; j += 1) {
        const ch = out[j]
        if (ch === '(') depth += 1
        else if (ch === ')') {
          depth -= 1
          if (depth === 0) {
            j += 1
            break
          }
        }
      }
      built += 'transparent'
      i = j
    }
    out = built
  }
  return out
}

/**
 * Build a list of paint snapshots from the **live** DOM (not the clone).
 */
export function snapshotLivePaint(root: HTMLElement): Map<string, Array<[string, string]>> {
  const map = new Map<string, Array<[string, string]>>()
  const nodes = root.querySelectorAll(STYLE_BAKE_SELECTORS.join(','))
  nodes.forEach((node, index) => {
    const el = node as HTMLElement
    const path = `${el.className}|${index}|${el.tagName}`
    map.set(path, copyPaintFromComputed(window.getComputedStyle(el)))
  })
  return map
}

export function applyPaintSnapshotsToClone(
  clonedRoot: HTMLElement,
  snapshots: Map<string, Array<[string, string]>>,
): void {
  const nodes = clonedRoot.querySelectorAll(STYLE_BAKE_SELECTORS.join(','))
  nodes.forEach((node, index) => {
    const el = node as HTMLElement
    const path = `${el.className}|${index}|${el.tagName}`
    const props = snapshots.get(path)
    if (!props) return
    for (const [key, value] of props) {
      if (value) el.style.setProperty(key, value, 'important')
    }
  })
}

export function prepareCloneForCapture(
  clonedDoc: Document,
  options: {
    mode: ScreenshotMode
    paintSnapshots: Map<string, Array<[string, string]>>
    realToolbar: HTMLElement | null
  },
): void {
  // 1. Force outer container and map wrapper backgrounds to fully transparent so html2canvas output is transparent
  const transparentSelectors = [
    'html',
    'body',
    '.dashboard',
    '.map-shell',
    '.map-stage',
    '.map-host',
    '.map-container',
    '.maplibregl-map',
    '.maplibregl-canvas-container',
    '.overlay',
    '.map-overlay',
    '#map',
  ]
  transparentSelectors.forEach((sel) => {
    clonedDoc.querySelectorAll(sel).forEach((node) => {
      const el = node as HTMLElement
      el.style.setProperty('background', 'transparent', 'important')
      el.style.setProperty('background-color', 'transparent', 'important')
      el.style.setProperty('background-image', 'none', 'important')
    })
  })

  const clonedRoot =
    (clonedDoc.querySelector('.dashboard') as HTMLElement | null) ||
    (clonedDoc.querySelector('.map-shell') as HTMLElement | null) ||
    (clonedDoc.querySelector('.map-stage') as HTMLElement | null)
  if (clonedRoot) {
    applyPaintSnapshotsToClone(clonedRoot, options.paintSnapshots)
    clonedRoot.style.setProperty('background', 'transparent', 'important')
    clonedRoot.style.setProperty('background-color', 'transparent', 'important')
    clonedRoot.style.setProperty('background-image', 'none', 'important')
  }

  // Strip CSS Color Level 4 functions that crash html2canvas's parser.
  scrubUnsupportedCssColorsInClone(clonedDoc)

  if (options.mode === 'pure') {
    const clonedStage = clonedDoc.querySelector('.map-stage') as HTMLElement | null
    if (clonedStage) {
      clonedStage.style.border = 'none'
      clonedStage.style.borderRadius = '0'
      clonedStage.style.boxShadow = 'none'
    }
  }

  // 2. Pin overlay positions in the CLONE (not live DOM) using stamped data attributes.
  const pinRoot = clonedRoot ?? clonedDoc.body
  pinRoot.querySelectorAll(PIN_OVERLAY_SELECTORS.join(',')).forEach((node) => {
    pinElementToOriginInClone(node as HTMLElement)
  })
  pinRoot.querySelectorAll(PIN_PANEL_SELECTORS.join(',')).forEach((node) => {
    pinElementToOriginInClone(node as HTMLElement)
  })

  // 3. Keep toolbar flex row intact and pin toolbar-main for html2canvas alignment
  const realToolbar = options.realToolbar
  const clonedToolbar = clonedDoc.querySelector('.toolbar') as HTMLElement | null
  if (clonedToolbar) {
    clonedToolbar.style.setProperty('display', 'flex', 'important')
    clonedToolbar.style.setProperty('flex-direction', 'row', 'important')
    clonedToolbar.style.setProperty('justify-content', 'space-between', 'important')
    clonedToolbar.style.setProperty('align-items', 'center', 'important')
    clonedToolbar.style.setProperty('position', 'relative', 'important')
    if (realToolbar) {
      const toolbarWidth = realToolbar.getBoundingClientRect?.()?.width ?? realToolbar.clientWidth
      if (toolbarWidth > 0) {
        clonedToolbar.style.setProperty('width', `${toolbarWidth}px`, 'important')
      }
    }
    clonedToolbar.style.setProperty('box-sizing', 'border-box', 'important')

    const realMain = realToolbar?.querySelector?.('.toolbar-main') as HTMLElement | null
    const clonedMain = clonedDoc.querySelector('.toolbar-main') as HTMLElement | null
    if (clonedMain) {
      clonedMain.style.setProperty('margin-left', 'auto', 'important')
      clonedMain.style.setProperty('display', 'flex', 'important')
      clonedMain.style.setProperty('flex-direction', 'column', 'important')
      clonedMain.style.setProperty('align-items', 'flex-end', 'important')
      clonedMain.style.setProperty('flex', 'none', 'important')

      if (realMain && realToolbar) {
        const realMainRect = realMain.getBoundingClientRect()
        const realToolbarRect = realToolbar.getBoundingClientRect()
        if (realMainRect.width > 0 && realToolbarRect.width > 0) {
          const rightOffset = Math.max(8, realToolbarRect.right - realMainRect.right)
          const topOffset = Math.max(0, realMainRect.top - realToolbarRect.top)
          clonedMain.style.setProperty('position', 'absolute', 'important')
          clonedMain.style.setProperty('right', `${rightOffset}px`, 'important')
          clonedMain.style.setProperty('top', `${topOffset}px`, 'important')
          clonedMain.style.setProperty('margin', '0', 'important')
        }
      }
    }
  }

  // 4. Hide map WebGL & 2D canvas elements so html2canvas does not capture them
  clonedDoc.querySelectorAll(MAP_CANVAS_SELECTORS.join(',')).forEach((el) => {
    ;(el as HTMLElement).style.setProperty('visibility', 'hidden', 'important')
    ;(el as HTMLElement).style.setProperty('opacity', '0', 'important')
  })
}

export function buildMapSnapshotLayout(
  mapCanvas: HTMLElement,
  captureEl: HTMLElement,
  scale: number,
  dataUrl: string,
): MapSnapshot {
  const rect = mapCanvas.getBoundingClientRect()
  const parentRect = captureEl.getBoundingClientRect()
  return {
    dataUrl,
    dx: (rect.left - parentRect.left) * scale,
    dy: (rect.top - parentRect.top) * scale,
    dw: rect.width * scale,
    dh: rect.height * scale,
  }
}

/**
 * Composite map snapshot underneath UI controls in three forward layers:
 * 1. Base background fill (resolved from --surface-1)
 * 2. Map Snapshot (Basemap + weather layers + scalar fields + vector lines + particles)
 * 3. UI Canvas (transparent HTML controls, panels, toolbar) on top!
 */
export async function compositeMapUnderUi(
  uiCanvas: HTMLCanvasElement,
  mapSnapshot: MapSnapshot | null,
  fillColor?: string,
): Promise<HTMLCanvasElement> {
  const composed = document.createElement('canvas')
  composed.width = uiCanvas.width
  composed.height = uiCanvas.height
  const ctx = composed.getContext('2d')
  if (!ctx) return uiCanvas

  // Layer 1: Fill solid background (resolve CSS variable to literal color)
  ctx.fillStyle = fillColor || resolveCssColor('--surface-1', '#0b1a2a')
  ctx.fillRect(0, 0, composed.width, composed.height)

  // Layer 2: Draw map snapshot (basemap + layers)
  if (mapSnapshot) {
    try {
      const mapImage = await loadImage(mapSnapshot.dataUrl)
      ctx.drawImage(mapImage, mapSnapshot.dx, mapSnapshot.dy, mapSnapshot.dw, mapSnapshot.dh)
    } catch (err) {
      console.warn('[ScreenshotExport] Failed to load map snapshot image:', err)
    }
  }

  // Layer 3: Draw transparent UI controls/panels canvas on top
  ctx.drawImage(uiCanvas, 0, 0)

  return composed
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('Failed to load map snapshot image'))
    img.src = src
  })
}

export function downloadBlob(blob: Blob, filename: string): void {
  const blobUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.download = filename
  link.href = blobUrl
  link.rel = 'noopener'
  link.style.display = 'none'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.setTimeout(() => URL.revokeObjectURL(blobUrl), 1500)
}

export function canvasToPngBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (!blob) {
        reject(new Error('Canvas blob generation failed'))
        return
      }
      resolve(blob)
    }, 'image/png')
  })
}
