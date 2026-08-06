import { describe, expect, it } from 'vitest'

import {
  buildMapSnapshotLayout,
  matchesAnySelector,
  pinLayoutsForCapture,
  prepareCloneForCapture,
  resolveCaptureElement,
  sanitizeCssColorForHtml2Canvas,
  stripUnsupportedColorFunctionsFromCss,
  type ScreenshotFormat,
  type ScreenshotMode,
} from '@/components/screenshot-export'

function fakeEl(partial: Record<string, unknown> = {}): HTMLElement {
  const style: Record<string, string> = {}
  const el = {
    className: '',
    tagName: 'DIV',
    style: new Proxy(style, {
      get(target, prop: string) {
        if (prop === 'setProperty') {
          return (key: string, value: string) => {
            target[key] = value
            // mirror camelCase common reads
            if (key === 'justify-content') target.justifyContent = value
            if (key === 'align-items') target.alignItems = value
            if (key === 'flex-direction') target.flexDirection = value
            if (key === 'margin-left') target.marginLeft = value
            if (key === 'box-sizing') target.boxSizing = value
          }
        }
        return target[prop]
      },
      set(target, prop: string, value: string) {
        target[prop] = value
        return true
      },
    }),
    getBoundingClientRect: () => ({
      left: 0,
      top: 0,
      width: 100,
      height: 40,
      right: 100,
      bottom: 40,
    }),
    matches: () => false,
    closest: () => null,
    querySelectorAll: () => [],
    querySelector: () => null,
    appendChild: () => undefined,
    ...partial,
  }
  return el as unknown as HTMLElement
}

describe('screenshot-export helpers', () => {
  it('supports valid screenshot modes and formats', () => {
    const validModes: ScreenshotMode[] = ['shell', 'bare', 'clean', 'pure']
    const validFormats: ScreenshotFormat[] = ['png', 'pdf']

    expect(validModes).toContain('shell')
    expect(validFormats).toContain('png')
  })

  it('resolves capture element by mode', () => {
    const dashboard = fakeEl()
    const shell = fakeEl()
    const stage = fakeEl()
    const els = { dashboardEl: dashboard, mapShellEl: shell, mapStageEl: stage }

    expect(resolveCaptureElement('shell', els)).toBe(dashboard)
    expect(resolveCaptureElement('bare', els)).toBe(shell)
    expect(resolveCaptureElement('clean', els)).toBe(shell)
    expect(resolveCaptureElement('pure', els)).toBe(stage)
    expect(resolveCaptureElement('shell', { ...els, mapStageEl: null })).toBeNull()
  })

  it('matches selectors including ancestors', () => {
    const child = fakeEl({
      matches: (sel: string) => sel === '.chip',
      closest: (sel: string) => (sel === '.overlay' ? fakeEl() : null),
    })
    expect(matchesAnySelector(child, ['.overlay'])).toBe(true)
    expect(matchesAnySelector(child, ['.missing'])).toBe(false)
    expect(matchesAnySelector(child, ['.chip'])).toBe(true)
  })

  it('stamps layout measurements as data attributes and cleans up', () => {
    const attrs: Record<string, string> = {}
    const overlay = fakeEl({
      className: 'overlay overlay-bottom',
      setAttribute: (key: string, value: string) => { attrs[key] = value },
      removeAttribute: (key: string) => { delete attrs[key] },
      getAttribute: (key: string) => attrs[key] ?? null,
      getBoundingClientRect: () => ({
        left: 100,
        top: 250,
        width: 200,
        height: 40,
        right: 300,
        bottom: 290,
      }),
    })

    const root = fakeEl({
      getBoundingClientRect: () => ({
        left: 10,
        top: 20,
        width: 400,
        height: 300,
        right: 410,
        bottom: 320,
      }),
      querySelectorAll: (sel: string) => {
        if (String(sel).includes('.overlay')) return [overlay]
        return []
      },
    })

    const restore = pinLayoutsForCapture(root)
    // Data attributes stamped with position relative to root
    expect(attrs['data-capture-left']).toBe('90')
    expect(attrs['data-capture-top']).toBe('230')
    expect(attrs['data-capture-width']).toBe('200')
    expect(attrs['data-capture-height']).toBe('40')

    restore()
    // Data attributes cleaned up
    expect(attrs['data-capture-left']).toBeUndefined()
    expect(attrs['data-capture-top']).toBeUndefined()
  })

  it('builds map snapshot layout in capture coordinates', () => {
    const mapCanvas = fakeEl({
      getBoundingClientRect: () => ({
        left: 50,
        top: 80,
        width: 200,
        height: 100,
        right: 250,
        bottom: 180,
      }),
    })
    const captureEl = fakeEl({
      getBoundingClientRect: () => ({
        left: 10,
        top: 20,
        width: 400,
        height: 300,
        right: 410,
        bottom: 320,
      }),
    })

    const snap = buildMapSnapshotLayout(mapCanvas, captureEl, 2, 'data:image/png;base64,x')
    expect(snap.dx).toBe(80)
    expect(snap.dy).toBe(120)
    expect(snap.dw).toBe(400)
    expect(snap.dh).toBe(200)
  })

  it('locks toolbar flex in clone preparation', () => {
    const toolbarStyle: Record<string, string> = {}
    const mainStyle: Record<string, string> = {}
    const primaryStyle: Record<string, string> = {}

    const makeStyle = (target: Record<string, string>) =>
      new Proxy(target, {
        get(t, prop: string) {
          if (prop === 'setProperty') {
            return (key: string, value: string) => {
              t[key] = value
              if (key === 'justify-content') t.justifyContent = value
              if (key === 'align-items') t.alignItems = value
              if (key === 'margin-left') t.marginLeft = value
              if (key === 'display') t.display = value
            }
          }
          return t[prop as string]
        },
        set(t, prop: string, value: string) {
          t[prop] = value
          return true
        },
      })

    const toolbar = fakeEl({
      className: 'toolbar',
      style: makeStyle(toolbarStyle),
    })
    const main = fakeEl({
      className: 'toolbar-main',
      style: makeStyle(mainStyle),
    })
    const primary = fakeEl({
      className: 'toolbar-primary',
      style: makeStyle(primaryStyle),
    })

    const shell = fakeEl({ className: 'map-shell' })
    const clonedDoc = {
      querySelector: (sel: string) => {
        if (sel === '.dashboard') return null
        if (sel === '.map-shell') return shell
        if (sel === '.map-stage') return null
        if (sel === '.toolbar') return toolbar
        if (sel === '.toolbar-main') return main
        if (sel === '.toolbar-primary') return primary
        return null
      },
      querySelectorAll: (sel: string) => {
        if (String(sel).includes('html') || String(sel).includes('.dashboard')) return []
        if (String(sel).includes('maplibregl')) return []
        return []
      },
    } as unknown as Document

    const realToolbar = fakeEl({
      getBoundingClientRect: () => ({
        width: 640,
        height: 48,
        left: 0,
        top: 0,
        right: 640,
        bottom: 48,
      }),
    })

    prepareCloneForCapture(clonedDoc, {
      mode: 'bare',
      paintSnapshots: new Map(),
      realToolbar,
    })

    expect(toolbarStyle.display).toBe('flex')
    expect(toolbarStyle.justifyContent).toBe('space-between')
    expect(mainStyle.marginLeft).toBe('auto')
    expect(mainStyle.alignItems).toBe('flex-end')
  })

  it('sanitizes CSS color() for html2canvas', () => {
    expect(sanitizeCssColorForHtml2Canvas('rgb(1, 2, 3)')).toBe('rgb(1, 2, 3)')
    expect(sanitizeCssColorForHtml2Canvas('color(srgb 0.1 0.2 0.3)')).toBe('')
    expect(sanitizeCssColorForHtml2Canvas('oklch(0.5 0.1 30)')).toBe('')
    expect(
      sanitizeCssColorForHtml2Canvas('color-mix(in srgb, #88d8ff 35%, transparent)'),
    ).toBe('')
    expect(sanitizeCssColorForHtml2Canvas('transparent')).toBe('transparent')
  })

  it('strips color-mix from raw stylesheet text', () => {
    const input =
      '.x{border:1px solid color-mix(in srgb, #88d8ff 35%, transparent);color:#fff}'
    const out = stripUnsupportedColorFunctionsFromCss(input)
    expect(out).toContain('transparent')
    expect(out).not.toMatch(/color-mix/i)
  })
})
