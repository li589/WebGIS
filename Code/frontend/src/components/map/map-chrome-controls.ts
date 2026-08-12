/**
 * 地图外框控件：缩放 / 旋转指南针 / 定位 + 比例尺
 * 样式与逻辑集中在此文件，便于单独修改。
 */
import maplibregl from 'maplibre-gl'
import type { IControl, Map as MapLibreMap } from 'maplibre-gl'

export interface MapChromeNavigationOptions {
  onLocate?: (map: MapLibreMap) => void | Promise<void>
  /** 拖拽旋转灵敏度；1 = 指针绕指南针角度与航向 1:1 */
  rotateSensitivity?: number
}

export interface AddMapChromeControlsOptions extends MapChromeNavigationOptions {
  scaleUnit?: 'metric' | 'imperial' | 'nautical'
  navigationPosition?: 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right'
  scalePosition?: 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right'
}

const STYLE_ELEMENT_ID = 'cgda-map-chrome-controls-style-v2'
const DRAG_ANGLE_THRESHOLD_DEG = 2.5

const CHROME_CONTROL_CSS = `
.maplibregl-ctrl-bottom-right {
  right: 0.8rem;
  bottom: 0.8rem;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.28rem;
}
.maplibregl-ctrl-bottom-left {
  left: 0.60rem;
  bottom: 0.8rem;
  margin: 0;
}
.map-custom-nav-ctrl {
  display: flex;
  flex-direction: column;
  border-radius: 0.75rem;
  overflow: hidden;
  box-shadow: 0 10px 28px rgba(3, 10, 20, 0.22);
  transition: background-color 0.25s ease, border-color 0.25s ease, box-shadow 0.25s ease;
  background: var(--surface-1);
  border: 1px solid var(--border-default);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  color: var(--text-primary);
}
.map-custom-nav-ctrl.map-nav-ctrl--dark,
.map-stage-dark .map-custom-nav-ctrl {
  background: var(--surface-1);
  border-color: var(--border-default);
  color: var(--text-primary);
}
.map-custom-nav-ctrl.map-nav-ctrl--light,
.map-stage-light .map-custom-nav-ctrl {
  background: var(--text-strong);
  border-color: var(--surface-sunken);
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.15);
  color: var(--surface-2);
}
.map-custom-nav-ctrl .map-nav-btn {
  width: 2.15rem;
  height: 2.15rem;
  padding: 0;
  border: none;
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  position: relative;
  color: inherit;
  transition: background-color 0.18s ease, color 0.18s ease;
}
.map-custom-nav-ctrl .map-nav-btn + .map-nav-btn {
  border-top: 1px solid var(--border-default);
}
.map-stage-light .map-custom-nav-ctrl .map-nav-btn + .map-nav-btn,
.map-custom-nav-ctrl.map-nav-ctrl--light .map-nav-btn + .map-nav-btn {
  border-top-color: var(--surface-sunken);
}
.map-custom-nav-ctrl .map-nav-btn:hover {
  background: var(--surface-hover);
  color: var(--accent);
}
.map-stage-light .map-custom-nav-ctrl .map-nav-btn:hover,
.map-custom-nav-ctrl.map-nav-ctrl--light .map-nav-btn:hover {
  background: var(--surface-sunken);
  color: #0284c7;
}
.map-custom-nav-ctrl .map-nav-btn--compass {
  touch-action: none;
  cursor: grab;
}
.map-custom-nav-ctrl .map-nav-btn--compass.map-nav-btn--dragging {
  cursor: grabbing;
  background: rgba(56, 189, 248, 0.12);
}
.map-custom-nav-ctrl .compass-needle-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  transition: transform 0.1s linear;
  pointer-events: none;
}
.map-custom-nav-ctrl .map-nav-btn--dragging .compass-needle-wrapper {
  transition: none;
}
.map-custom-nav-ctrl .map-nav-btn--rotated {
  color: var(--accent);
}
.map-custom-nav-ctrl .map-nav-btn--loading svg {
  animation: cgda-nav-locate-spin 1s linear infinite;
}
@keyframes cgda-nav-locate-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
`

/** 注入导航控件样式（幂等；会清掉旧版含比例尺覆盖的样式标签） */
export function ensureMapChromeControlStyles(): void {
  if (typeof document === 'undefined') return
  const legacy = document.getElementById('cgda-map-chrome-controls-style')
  legacy?.remove()
  let style = document.getElementById(STYLE_ELEMENT_ID) as HTMLStyleElement | null
  if (!style) {
    style = document.createElement('style')
    style.id = STYLE_ELEMENT_ID
    document.head.appendChild(style)
  }
  style.textContent = CHROME_CONTROL_CSS
}

function pointerAngleDeg(clientX: number, clientY: number, el: HTMLElement): number {
  const rect = el.getBoundingClientRect()
  const cx = rect.left + rect.width / 2
  const cy = rect.top + rect.height / 2
  return (Math.atan2(clientX - cx, cy - clientY) * 180) / Math.PI
}

function normalizeDeltaDeg(delta: number): number {
  let d = delta
  while (d > 180) d -= 360
  while (d < -180) d += 360
  return d
}

/**
 * 自定义导航控件：放大 / 指南针(拖拽旋转+点击归北) / 缩小 / 定位
 */
export class MapChromeNavigationControl implements IControl {
  private _map?: MapLibreMap
  private _container?: HTMLElement
  private _compassNeedle?: HTMLElement
  private _compassBtn?: HTMLButtonElement
  private _locateBtn?: HTMLButtonElement
  private _options: MapChromeNavigationOptions
  private _dragging = false
  private _dragMoved = false
  private _activePointerId: number | null = null
  private _startBearing = 0
  private _startAngle = 0
  private _boundPointerMove = (event: PointerEvent) => this._onCompassPointerMove(event)
  private _boundPointerUp = (event: PointerEvent) => this._onCompassPointerUp(event)

  constructor(options: MapChromeNavigationOptions = {}) {
    this._options = options
    this._onRotate = this._onRotate.bind(this)
  }

  onAdd(map: MapLibreMap): HTMLElement {
    ensureMapChromeControlStyles()
    this._map = map
    const container = document.createElement('div')
    container.className = 'maplibregl-ctrl maplibregl-ctrl-group map-custom-nav-ctrl'
    container.setAttribute('aria-label', '地图导航与视角控制')
    this._container = container

    const zoomInBtn = this._createIconButton({
      className: 'map-nav-btn map-nav-btn--zoom-in',
      title: '放大视角 (Zoom In)',
      html: `
        <svg viewBox="0 0 20 20" aria-hidden="true" width="16" height="16">
          <path fill="currentColor" d="M9 4a1 1 0 0 1 2 0v4h4a1 1 0 1 1 0 2h-4v4a1 1 0 1 1-2 0v-4H5a1 1 0 1 1 0-2h4V4z"/>
        </svg>
      `,
      onClick: () => this._map?.zoomIn(),
    })

    const compassBtn = document.createElement('button')
    compassBtn.type = 'button'
    compassBtn.className = 'map-nav-btn map-nav-btn--compass'
    compassBtn.title = '拖拽旋转地图；点击复位正北'
    this._compassBtn = compassBtn

    const compassNeedle = document.createElement('div')
    compassNeedle.className = 'compass-needle-wrapper'
    compassNeedle.innerHTML = `
      <svg class="compass-dial-svg" viewBox="0 0 32 32" aria-hidden="true" width="22" height="22">
        <circle cx="16" cy="16" r="14.2" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.35" />
        <polygon points="16,3.5 20,15 16,13 12,15" fill="var(--danger)" />
        <text x="16" y="9.5" font-size="5" font-weight="900" text-anchor="middle" fill="var(--text-strong)" style="user-select:none;">N</text>
        <polygon points="16,28.5 20,17 16,19 12,17" fill="var(--text-secondary)" />
        <text x="16" y="25" font-size="5" font-weight="900" text-anchor="middle" fill="var(--text-strong)" style="user-select:none;">S</text>
        <circle cx="16" cy="16" r="2" fill="var(--accent)" />
      </svg>
    `
    this._compassNeedle = compassNeedle
    compassBtn.appendChild(compassNeedle)
    compassBtn.addEventListener('pointerdown', (event) => this._onCompassPointerDown(event))
    compassBtn.addEventListener('dragstart', (event) => event.preventDefault())

    const zoomOutBtn = this._createIconButton({
      className: 'map-nav-btn map-nav-btn--zoom-out',
      title: '缩小视角 (Zoom Out)',
      html: `
        <svg viewBox="0 0 20 20" aria-hidden="true" width="16" height="16">
          <path fill="currentColor" d="M4 9a1 1 0 0 1 1-1h10a1 1 0 1 1 0 2H5a1 1 0 0 1-1-1z"/>
        </svg>
      `,
      onClick: () => this._map?.zoomOut(),
    })

    const locateBtn = this._createIconButton({
      className: 'map-nav-btn map-nav-btn--locate',
      title: '自动定位坐标 / 复位视角',
      html: `
        <svg viewBox="0 0 24 24" aria-hidden="true" width="16" height="16">
          <circle cx="12" cy="12" r="3.5" fill="currentColor" />
          <path fill="currentColor" d="M12 2a1 1 0 0 1 1 1v2.05A7.002 7.002 0 0 1 18.95 11H21a1 1 0 1 1 0 2h-2.05A7.002 7.002 0 0 1 13 18.95V21a1 1 0 1 1-2 0v-2.05A7.002 7.002 0 0 1 5.05 13H3a1 1 0 1 1 0-2h2.05A7.002 7.002 0 0 1 11 5.05V3a1 1 0 0 1 1-1zm0 5a5 5 0 1 0 0 10 5 5 0 0 0 0-10z"/>
        </svg>
      `,
      onClick: () => {
        if (this._options.onLocate && this._map) {
          void this._options.onLocate(this._map)
        } else if (this._map) {
          this._defaultLocate(this._map)
        }
      },
    })
    this._locateBtn = locateBtn

    container.appendChild(zoomInBtn)
    container.appendChild(compassBtn)
    container.appendChild(zoomOutBtn)
    container.appendChild(locateBtn)

    map.on('rotate', this._onRotate)
    map.on('pitch', this._onRotate)
    this._onRotate()

    return container
  }

  onRemove(): void {
    this._endCompassDrag()
    if (this._map) {
      this._map.off('rotate', this._onRotate)
      this._map.off('pitch', this._onRotate)
    }
    if (this._container?.parentNode) {
      this._container.parentNode.removeChild(this._container)
    }
    this._map = undefined
    this._container = undefined
    this._compassNeedle = undefined
    this._compassBtn = undefined
    this._locateBtn = undefined
  }

  private _createIconButton(options: {
    className: string
    title: string
    html: string
    onClick: () => void
  }): HTMLButtonElement {
    const btn = document.createElement('button')
    btn.type = 'button'
    btn.className = options.className
    btn.title = options.title
    btn.innerHTML = options.html
    btn.addEventListener('click', options.onClick)
    return btn
  }

  private _onCompassPointerDown(event: PointerEvent): void {
    if (!this._map || !this._compassBtn) return
    if (event.button !== 0 && event.pointerType === 'mouse') return

    event.preventDefault()
    event.stopPropagation()

    this._dragging = true
    this._dragMoved = false
    this._activePointerId = event.pointerId
    this._startBearing = this._map.getBearing()
    this._startAngle = pointerAngleDeg(event.clientX, event.clientY, this._compassBtn)
    this._compassBtn.classList.add('map-nav-btn--dragging')

    try {
      this._compassBtn.setPointerCapture(event.pointerId)
    } catch {
      /* ignore */
    }

    if (typeof window !== 'undefined') {
      window.addEventListener('pointermove', this._boundPointerMove)
      window.addEventListener('pointerup', this._boundPointerUp)
      window.addEventListener('pointercancel', this._boundPointerUp)
    }
  }

  private _onCompassPointerMove(event: PointerEvent): void {
    if (!this._dragging || !this._map || !this._compassBtn) return
    if (this._activePointerId !== null && event.pointerId !== this._activePointerId) return

    event.preventDefault()
    const angle = pointerAngleDeg(event.clientX, event.clientY, this._compassBtn)
    const delta = normalizeDeltaDeg(angle - this._startAngle)
    if (Math.abs(delta) >= DRAG_ANGLE_THRESHOLD_DEG) {
      this._dragMoved = true
    }
    if (!this._dragMoved) return

    const sensitivity = this._options.rotateSensitivity ?? 1
    this._map.setBearing(this._startBearing + delta * sensitivity)
  }

  private _onCompassPointerUp(event: PointerEvent): void {
    if (!this._dragging) return
    if (this._activePointerId !== null && event.pointerId !== this._activePointerId) return

    const moved = this._dragMoved
    this._endCompassDrag()

    if (!moved) {
      this._map?.easeTo({ bearing: 0, pitch: 0, duration: 500 })
    }
  }

  private _endCompassDrag(): void {
    this._dragging = false
    this._dragMoved = false
    this._activePointerId = null
    this._compassBtn?.classList.remove('map-nav-btn--dragging')
    if (typeof window === 'undefined') return
    window.removeEventListener('pointermove', this._boundPointerMove)
    window.removeEventListener('pointerup', this._boundPointerUp)
    window.removeEventListener('pointercancel', this._boundPointerUp)
  }

  private _onRotate(): void {
    if (!this._map || !this._compassNeedle) return
    const bearing = this._map.getBearing()
    const pitch = this._map.getPitch()
    this._compassNeedle.style.transform = `rotate(${-bearing}deg)`

    if (this._compassBtn) {
      const roundedBearing = Math.round(((bearing % 360) + 360) % 360)
      if (roundedBearing === 0 && Math.round(pitch) === 0) {
        this._compassBtn.title = '拖拽旋转地图；点击复位正北'
        this._compassBtn.classList.remove('map-nav-btn--rotated')
      } else {
        this._compassBtn.title = `当前航向 ${roundedBearing}° / 俯仰 ${Math.round(pitch)}° · 拖拽旋转 / 点击归北`
        this._compassBtn.classList.add('map-nav-btn--rotated')
      }
    }
  }

  private _defaultLocate(map: MapLibreMap): void {
    this._locateBtn?.classList.add('map-nav-btn--loading')

    const finishLoading = () => {
      this._locateBtn?.classList.remove('map-nav-btn--loading')
    }

    if (typeof navigator !== 'undefined' && 'geolocation' in navigator) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          map.flyTo({
            center: [pos.coords.longitude, pos.coords.latitude],
            zoom: 13,
            duration: 1200,
          })
          finishLoading()
        },
        () => {
          map.flyTo({
            center: [113.26, 23.13],
            zoom: 9,
            duration: 1000,
          })
          finishLoading()
        },
        { timeout: 5000, maximumAge: 60000 },
      )
    } else {
      map.flyTo({
        center: [113.26, 23.13],
        zoom: 9,
        duration: 1000,
      })
      finishLoading()
    }
  }
}

/** 创建比例尺：沿用 MapLibre 默认朴素样式，不做外观覆盖 */
export function createMapChromeScaleControl(
  options: { unit?: 'metric' | 'imperial' | 'nautical' } = {},
): IControl {
  return new maplibregl.ScaleControl({
    unit: options.unit ?? 'metric',
  })
}

/** 一次性挂载导航 + 比例尺 */
export function addMapChromeControls(
  map: MapLibreMap,
  options: AddMapChromeControlsOptions = {},
): { navigation: MapChromeNavigationControl; scale: IControl } {
  ensureMapChromeControlStyles()
  const navigation = new MapChromeNavigationControl({
    onLocate: options.onLocate,
    rotateSensitivity: options.rotateSensitivity,
  })
  const scale = createMapChromeScaleControl({ unit: options.scaleUnit })
  map.addControl(navigation, options.navigationPosition ?? 'bottom-right')
  map.addControl(scale, options.scalePosition ?? 'bottom-left')
  return { navigation, scale }
}
