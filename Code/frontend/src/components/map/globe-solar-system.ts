/**
 * 太阳系深空背景：相机联动天球投影 + 时间联动太阳盘（纯函数，可单测）。
 *
 * 地心系远景观感（接近 Universe Sandbox 远距视角），不改晨昏线逻辑。
 * 星表复用 globe-starfield 的 BRIGHT_STARS；背景星用确定性伪随机加密。
 */
import { BRIGHT_STARS, type BrightStar } from './globe-starfield'
import { lngLatToGlobeSphere } from './canvas-utils'
import { subsolarDeclination, subsolarLongitude } from './globe-scene-utils'

export interface SolarSystemCamera {
  lng: number
  lat: number
  bearing: number
  pitch: number
  zoom: number
}

export interface SolarSystemRenderOptions {
  width: number
  height: number
  camera: SolarSystemCamera
  /** 本地时间轴小时（与晨昏线同一模型） */
  hour: number
  date?: Date
  /** 关闭日冕闪烁等动效 */
  reducedMotion?: boolean
  /** 动画相位（秒），reducedMotion 时忽略 */
  timeSec?: number
  seed?: number
}

export interface Vec3 {
  x: number
  y: number
  z: number
}

export interface ScreenPoint {
  x: number
  y: number
  /** 相对视向：1=朝向相机一侧，-1=远侧 */
  depth: number
}

const DEG2RAD = Math.PI / 180

function mulberry32(seed: number): () => number {
  let t = seed >>> 0
  return () => {
    t += 0x6d2b79f5
    let r = Math.imul(t ^ (t >>> 15), 1 | t)
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r)
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296
  }
}

export function celestialUnitVector(raHours: number, decDeg: number): Vec3 {
  const [x, y, z] = lngLatToGlobeSphere(raHours * 15, decDeg)
  return { x, y, z }
}

export function geographicUnitVector(lng: number, lat: number): Vec3 {
  const [x, y, z] = lngLatToGlobeSphere(lng, lat)
  return { x, y, z }
}

function cross(a: Vec3, b: Vec3): Vec3 {
  return {
    x: a.y * b.z - a.z * b.y,
    y: a.z * b.x - a.x * b.z,
    z: a.x * b.y - a.y * b.x,
  }
}

function normalize(v: Vec3): Vec3 {
  const len = Math.hypot(v.x, v.y, v.z) || 1
  return { x: v.x / len, y: v.y / len, z: v.z / len }
}

function dot(a: Vec3, b: Vec3): number {
  return a.x * b.x + a.y * b.y + a.z * b.z
}

/**
 * 视向极点（与 canvas-utils.getGlobeViewPole 同几何，纯数据版便于单测）。
 */
export function viewPoleFromCamera(camera: SolarSystemCamera): Vec3 {
  let pole = geographicUnitVector(camera.lng, camera.lat)
  if (camera.pitch <= 0.5) return pole
  const lat = camera.lat * DEG2RAD
  const lon = camera.lng * DEG2RAD
  const north = {
    x: -Math.sin(lat) * Math.sin(lon),
    y: Math.cos(lat),
    z: -Math.sin(lat) * Math.cos(lon),
  }
  const east = { x: Math.cos(lon), y: 0, z: -Math.sin(lon) }
  const bearingR = camera.bearing * DEG2RAD
  const cosB = Math.cos(bearingR)
  const sinB = Math.sin(bearingR)
  const up = {
    x: cosB * north.x + sinB * east.x,
    y: cosB * north.y + sinB * east.y,
    z: cosB * north.z + sinB * east.z,
  }
  const pitchR = camera.pitch * DEG2RAD
  const cosP = Math.cos(pitchR)
  const sinP = Math.sin(pitchR)
  pole = {
    x: cosP * pole.x + sinP * up.x,
    y: cosP * pole.y + sinP * up.y,
    z: cosP * pole.z + sinP * up.z,
  }
  return normalize(pole)
}

export interface ViewBasis {
  forward: Vec3
  right: Vec3
  up: Vec3
}

export function buildViewBasis(camera: SolarSystemCamera): ViewBasis {
  const forward = viewPoleFromCamera(camera)
  const worldUp = { x: 0, y: 1, z: 0 }
  let right = cross(worldUp, forward)
  if (Math.hypot(right.x, right.y, right.z) < 1e-6) {
    right = { x: 1, y: 0, z: 0 }
  }
  right = normalize(right)
  const up = normalize(cross(forward, right))
  // 用地图 bearing 旋转 right/up，使拖动旋转时星空跟转
  const bearingR = camera.bearing * DEG2RAD
  const cosB = Math.cos(bearingR)
  const sinB = Math.sin(bearingR)
  const right2 = {
    x: cosB * right.x + sinB * up.x,
    y: cosB * right.y + sinB * up.y,
    z: cosB * right.z + sinB * up.z,
  }
  const up2 = {
    x: -sinB * right.x + cosB * up.x,
    y: -sinB * right.y + cosB * up.y,
    z: -sinB * right.z + cosB * up.z,
  }
  return { forward, right: normalize(right2), up: normalize(up2) }
}

/**
 * 将单位方向投影到屏幕。depth>0.85（几乎正对相机、地球圆盘中心）可跳过绘制。
 */
export function projectSkyDirection(
  dir: Vec3,
  basis: ViewBasis,
  width: number,
  height: number,
  zoom: number,
): ScreenPoint | null {
  const depth = dot(dir, basis.forward)
  // 紧贴镜头方向的星被地球遮挡，不必画
  if (depth > 0.88) return null
  const x = dot(dir, basis.right)
  const y = dot(dir, basis.up)
  const persp = 1 / Math.max(0.22, 1.28 - Math.min(depth, 0.85))
  // zoom 越小（越远）天球铺满越多
  const zoomFactor = Math.max(0.55, Math.min(1.35, 1.15 - (zoom - 1.2) * 0.08))
  const scale = Math.min(width, height) * 0.62 * persp * zoomFactor
  return {
    x: width * 0.5 + x * scale,
    y: height * 0.5 - y * scale,
    depth,
  }
}

export function sunDirection(hour: number, date?: Date): Vec3 {
  const lon = subsolarLongitude(hour)
  const lat = subsolarDeclination(date)
  return geographicUnitVector(lon, lat)
}

/** 粗略月球方位：相对太阳黄道偏移（非精密星历） */
export function moonDirectionApprox(hour: number, date?: Date): Vec3 {
  const sun = sunDirection(hour, date)
  const d = date ?? new Date()
  const day = Math.floor(d.getTime() / 86400000)
  const phase = ((day % 30) / 30) * Math.PI * 2
  // 绕地轴近似旋转太阳方向
  const cosP = Math.cos(phase)
  const sinP = Math.sin(phase)
  return normalize({
    x: sun.x * cosP - sun.z * sinP,
    y: sun.y * 0.92,
    z: sun.x * sinP + sun.z * cosP,
  })
}

const PLANETS: Array<{ name: string; lonOffset: number; lat: number; color: string; size: number }> =
  [
    { name: 'Venus', lonOffset: 48, lat: 2, color: 'rgba(255,230,180,0.95)', size: 2.2 },
    { name: 'Mars', lonOffset: -75, lat: -4, color: 'rgba(255,140,90,0.9)', size: 1.8 },
    { name: 'Jupiter', lonOffset: 130, lat: 1, color: 'rgba(255,210,150,0.85)', size: 2.6 },
    { name: 'Saturn', lonOffset: -155, lat: 3, color: 'rgba(240,220,170,0.8)', size: 2.0 },
  ]

function spectralColor(spectral: string): string {
  switch (spectral[0]) {
    case 'O':
    case 'B':
      return 'rgba(170,200,255,1)'
    case 'A':
      return 'rgba(220,235,255,1)'
    case 'F':
      return 'rgba(255,255,245,1)'
    case 'G':
      return 'rgba(255,245,210,1)'
    case 'K':
      return 'rgba(255,210,160,1)'
    case 'M':
      return 'rgba(255,170,130,1)'
    default:
      return 'rgba(240,245,255,1)'
  }
}

function rgba(r: number, g: number, b: number, a: number): string {
  return `rgba(${Math.round(r)},${Math.round(g)},${Math.round(b)},${Math.max(0, Math.min(1, a))})`
}

function drawGlow(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  radius: number,
  color: string,
  alpha: number,
) {
  const g = ctx.createRadialGradient(x, y, 0, x, y, radius)
  g.addColorStop(0, color.replace(/[\d.]+\)$/, `${alpha})`))
  g.addColorStop(0.35, color.replace(/[\d.]+\)$/, `${alpha * 0.35})`))
  g.addColorStop(1, color.replace(/[\d.]+\)$/, '0)'))
  ctx.fillStyle = g
  ctx.beginPath()
  ctx.arc(x, y, radius, 0, Math.PI * 2)
  ctx.fill()
}

/** 太阳附近眩光衰减：越近星点越被洗掉（接近真实镜头/人眼） */
export function solarGlareFactor(distPx: number, glareRadius: number): number {
  if (glareRadius <= 1) return 1
  const t = distPx / glareRadius
  if (t >= 1) return 1
  // 核心几乎全灭，外圈缓升
  return Math.max(0, Math.pow(t, 1.65))
}

/**
 * 黄道光：沿黄道（近似：太阳方向 × 视平面）的极淡尘埃散射锥。
 */
function drawZodiacalLight(
  ctx: CanvasRenderingContext2D,
  sunScr: ScreenPoint,
  sunDir: Vec3,
  basis: ViewBasis,
  width: number,
  height: number,
  intensity: number,
) {
  // 黄道在屏幕上的切向：太阳方向与视向叉积再投到 right/up
  const eclipticTangent = normalize(cross(sunDir, basis.forward))
  const tx = dot(eclipticTangent, basis.right)
  const ty = -dot(eclipticTangent, basis.up)
  const tLen = Math.hypot(tx, ty) || 1
  const ux = tx / tLen
  const uy = ty / tLen
  // 垂直于黄道的屏幕方向（用于做扁带）
  const vx = -uy
  const vy = ux

  const span = Math.max(width, height) * 0.72
  const halfWidth = Math.min(width, height) * 0.11

  ctx.save()
  ctx.globalCompositeOperation = 'lighter'
  for (const side of [-1, 1] as const) {
    for (let i = 0; i < 5; i++) {
      const along = (0.18 + i * 0.16) * span * side
      const fall = Math.exp(-Math.abs(along) / (span * 0.55))
      const cx = sunScr.x + ux * along
      const cy = sunScr.y + uy * along
      const rx = halfWidth * (1.1 - i * 0.08)
      const ry = halfWidth * (0.35 + i * 0.04)
      const alpha = intensity * 0.045 * fall * (1 - i * 0.12)
      if (alpha < 0.002) continue
      // 画旋转椭圆带：变换坐标系
      ctx.save()
      ctx.translate(cx, cy)
      ctx.transform(ux, uy, vx, vy, 0, 0)
      const g = ctx.createRadialGradient(0, 0, 0, 0, 0, 1)
      g.addColorStop(0, rgba(255, 232, 190, alpha))
      g.addColorStop(0.45, rgba(255, 210, 150, alpha * 0.35))
      g.addColorStop(1, rgba(255, 180, 100, 0))
      ctx.fillStyle = g
      ctx.beginPath()
      // 扁椭圆带：优先 ellipse，退化用 scale+arc
      if (typeof ctx.ellipse === 'function') {
        ctx.ellipse(0, 0, rx, ry, 0, 0, Math.PI * 2)
      } else {
        ctx.save()
        ctx.scale(rx, Math.max(ry, 0.001))
        ctx.arc(0, 0, 1, 0, Math.PI * 2)
        ctx.restore()
      }
      ctx.fill()
      ctx.restore()
    }
  }
  ctx.restore()
}

function drawSunDiskAndAtmosphere(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  pulse: number,
  width: number,
  height: number,
) {
  const minDim = Math.min(width, height)
  const core = 11 * pulse
  const coronaOuter = minDim * 0.55 * pulse
  const coronaMid = minDim * 0.28 * pulse
  const coronaInner = minDim * 0.14 * pulse

  ctx.save()
  ctx.globalCompositeOperation = 'lighter'

  // 1) 极外层冷色散射（空间中太阳周围极弱的蓝白晕）
  {
    const g = ctx.createRadialGradient(x, y, core * 0.5, x, y, coronaOuter)
    g.addColorStop(0, rgba(255, 248, 230, 0.12))
    g.addColorStop(0.15, rgba(255, 220, 160, 0.08))
    g.addColorStop(0.4, rgba(180, 200, 255, 0.035))
    g.addColorStop(0.7, rgba(120, 150, 220, 0.012))
    g.addColorStop(1, rgba(40, 60, 120, 0))
    ctx.fillStyle = g
    ctx.beginPath()
    ctx.arc(x, y, coronaOuter, 0, Math.PI * 2)
    ctx.fill()
  }

  // 2) 暖色日冕（K 冕感：黄橙衰减）
  {
    const g = ctx.createRadialGradient(x, y, core * 0.2, x, y, coronaMid)
    g.addColorStop(0, rgba(255, 245, 210, 0.55))
    g.addColorStop(0.25, rgba(255, 210, 120, 0.28))
    g.addColorStop(0.55, rgba(255, 150, 60, 0.1))
    g.addColorStop(1, rgba(255, 100, 30, 0))
    ctx.fillStyle = g
    ctx.beginPath()
    ctx.arc(x, y, coronaMid, 0, Math.PI * 2)
    ctx.fill()
  }

  // 3) 内冕高亮
  {
    const g = ctx.createRadialGradient(x, y, 0, x, y, coronaInner)
    g.addColorStop(0, rgba(255, 252, 245, 0.95))
    g.addColorStop(0.35, rgba(255, 236, 170, 0.55))
    g.addColorStop(0.7, rgba(255, 190, 90, 0.18))
    g.addColorStop(1, rgba(255, 160, 50, 0))
    ctx.fillStyle = g
    ctx.beginPath()
    ctx.arc(x, y, coronaInner, 0, Math.PI * 2)
    ctx.fill()
  }

  // 4) 软核高光（lighter 叠在内冕上）：不要硬光球盘，避免中心出现橙红实心小圆
  {
    const g = ctx.createRadialGradient(x, y, 0, x, y, core * 1.35)
    g.addColorStop(0, rgba(255, 255, 252, 0.92))
    g.addColorStop(0.4, rgba(255, 248, 220, 0.45))
    g.addColorStop(0.75, rgba(255, 230, 160, 0.12))
    g.addColorStop(1, rgba(255, 210, 120, 0))
    ctx.fillStyle = g
    ctx.beginPath()
    ctx.arc(x, y, core * 1.35, 0, Math.PI * 2)
    ctx.fill()
  }

  ctx.restore()
}

/**
 * 在已有 canvas 上绘制太阳系背景（调用方负责尺寸 / DPR）。
 */
export function paintSolarSystemBackdrop(
  ctx: CanvasRenderingContext2D,
  options: SolarSystemRenderOptions,
): void {
  const { width, height, camera, hour, date, reducedMotion, timeSec = 0, seed = 42 } = options
  ctx.clearRect(0, 0, width, height)

  // ── 深空底：近黑，仅极弱冷色天光，避免「蓝雾幕」感 ──
  ctx.fillStyle = '#010206'
  ctx.fillRect(0, 0, width, height)
  {
    const bg = ctx.createRadialGradient(
      width * 0.42,
      height * 0.38,
      0,
      width * 0.5,
      height * 0.5,
      Math.max(width, height) * 0.85,
    )
    bg.addColorStop(0, 'rgba(8, 12, 22, 0.55)')
    bg.addColorStop(0.45, 'rgba(3, 6, 14, 0.35)')
    bg.addColorStop(1, 'rgba(0, 0, 0, 0)')
    ctx.fillStyle = bg
    ctx.fillRect(0, 0, width, height)
  }
  // 纵向极淡色温差（上冷下略暖褐），贴近真实天光照片
  {
    const sky = ctx.createLinearGradient(0, 0, 0, height)
    sky.addColorStop(0, 'rgba(12, 20, 40, 0.22)')
    sky.addColorStop(0.55, 'rgba(0, 0, 0, 0)')
    sky.addColorStop(1, 'rgba(18, 10, 8, 0.16)')
    ctx.fillStyle = sky
    ctx.fillRect(0, 0, width, height)
  }

  const basis = buildViewBasis(camera)
  const rng = mulberry32(seed)
  const sunDir = sunDirection(hour, date)
  const sunScr = projectSkyDirection(sunDir, basis, width, height, camera.zoom)
  const glareRadius = Math.min(width, height) * 0.42

  // ── 银河：暖尘 + 冷蓝，强度压低，避免霓虹紫雾 ──
  const milky = celestialUnitVector(17.75, -29)
  const milkyScr = projectSkyDirection(milky, basis, width, height, camera.zoom)
  if (milkyScr && milkyScr.depth < 0.72) {
    const gx = milkyScr.x
    const gy = milkyScr.y
    const r = Math.min(width, height) * 0.62
    ctx.save()
    ctx.globalCompositeOperation = 'lighter'
    const warm = ctx.createRadialGradient(gx, gy, 0, gx, gy, r * 0.55)
    warm.addColorStop(0, 'rgba(255, 236, 210, 0.07)')
    warm.addColorStop(0.35, 'rgba(200, 170, 140, 0.035)')
    warm.addColorStop(1, 'rgba(0, 0, 0, 0)')
    ctx.fillStyle = warm
    ctx.fillRect(0, 0, width, height)
    const cool = ctx.createRadialGradient(gx + r * 0.12, gy - r * 0.08, 0, gx, gy, r)
    cool.addColorStop(0, 'rgba(140, 165, 220, 0.05)')
    cool.addColorStop(0.5, 'rgba(90, 110, 170, 0.02)')
    cool.addColorStop(1, 'rgba(0, 0, 0, 0)')
    ctx.fillStyle = cool
    ctx.fillRect(0, 0, width, height)
    ctx.restore()
  }

  // ── 背景星场：色温分散 + 太阳眩光区衰减 ──
  const faintCount = 1100
  for (let i = 0; i < faintCount; i++) {
    const ra = rng() * 24
    const dec = Math.asin(rng() * 2 - 1) * (180 / Math.PI)
    const dir = celestialUnitVector(ra, dec)
    const scr = projectSkyDirection(dir, basis, width, height, camera.zoom)
    if (!scr) continue
    const mag = 3.4 + rng() * 3.2
    let a = Math.max(0.08, 0.72 - mag * 0.11)
    const r = Math.max(0.35, 1.9 - mag * 0.32)
    if (sunScr) {
      const d = Math.hypot(scr.x - sunScr.x, scr.y - sunScr.y)
      a *= solarGlareFactor(d, glareRadius)
      if (a < 0.02) continue
    }
    // 光谱随机：多数冷白，少量暖橙
    const tint = rng()
    const color =
      tint < 0.12
        ? rgba(255, 200, 160, a)
        : tint < 0.35
          ? rgba(255, 245, 220, a)
          : tint < 0.75
            ? rgba(220, 230, 255, a)
            : rgba(180, 205, 255, a)
    ctx.fillStyle = color
    ctx.beginPath()
    ctx.arc(scr.x, scr.y, r, 0, Math.PI * 2)
    ctx.fill()
  }

  // ── 亮星：软晕 + 眩光区衰减 ──
  for (const star of BRIGHT_STARS as ReadonlyArray<BrightStar>) {
    const dir = celestialUnitVector(star.raHours, star.decDeg)
    const scr = projectSkyDirection(dir, basis, width, height, camera.zoom)
    if (!scr) continue
    let glowA = 0.38
    if (sunScr) {
      const d = Math.hypot(scr.x - sunScr.x, scr.y - sunScr.y)
      const f = solarGlareFactor(d, glareRadius * 0.85)
      if (f < 0.08) continue
      glowA *= f
    }
    const size = Math.max(1.15, 3.6 - star.mag)
    const color = spectralColor(star.spectral)
    drawGlow(ctx, scr.x, scr.y, size * 5.2, color, glowA)
    ctx.fillStyle = color.replace(/[\d.]+\)$/, `${Math.min(1, glowA + 0.45)})`)
    ctx.beginPath()
    ctx.arc(scr.x, scr.y, size * 0.5, 0, Math.PI * 2)
    ctx.fill()
  }

  // ── 行星光点 ──
  const sunLon = subsolarLongitude(hour)
  for (const p of PLANETS) {
    let lon = sunLon + p.lonOffset
    while (lon > 180) lon -= 360
    while (lon < -180) lon += 360
    const dir = geographicUnitVector(lon, p.lat)
    const scr = projectSkyDirection(dir, basis, width, height, camera.zoom)
    if (!scr || scr.depth > 0.75) continue
    let a = 0.48
    if (sunScr) {
      a *= solarGlareFactor(Math.hypot(scr.x - sunScr.x, scr.y - sunScr.y), glareRadius * 0.7)
      if (a < 0.06) continue
    }
    drawGlow(ctx, scr.x, scr.y, p.size * 5, p.color, a)
    ctx.fillStyle = p.color
    ctx.beginPath()
    ctx.arc(scr.x, scr.y, p.size, 0, Math.PI * 2)
    ctx.fill()
  }

  // ── 月球：冷白月晕，略压饱和 ──
  const moonDir = moonDirectionApprox(hour, date)
  const moonScr = projectSkyDirection(moonDir, basis, width, height, camera.zoom)
  if (moonScr && moonScr.depth < 0.82) {
    drawGlow(ctx, moonScr.x, moonScr.y, 22, 'rgba(200,215,255,1)', 0.22)
    drawGlow(ctx, moonScr.x, moonScr.y, 10, 'rgba(235,240,255,1)', 0.4)
    const moonDisc = ctx.createRadialGradient(
      moonScr.x - 1.2,
      moonScr.y - 1.5,
      0,
      moonScr.x,
      moonScr.y,
      4.2,
    )
    moonDisc.addColorStop(0, 'rgba(245,248,255,0.95)')
    moonDisc.addColorStop(0.7, 'rgba(210,220,235,0.85)')
    moonDisc.addColorStop(1, 'rgba(160,170,190,0.55)')
    ctx.fillStyle = moonDisc
    ctx.beginPath()
    ctx.arc(moonScr.x, moonScr.y, 4.2, 0, Math.PI * 2)
    ctx.fill()
  }

  // ── 黄道光（太阳可见时）──
  if (sunScr) {
    drawZodiacalLight(ctx, sunScr, sunDir, basis, width, height, 1)
  }

  // ── 太阳盘 + 多层大气散射 ──
  if (sunScr) {
    const pulse = reducedMotion ? 1 : 1 + Math.sin(timeSec * 0.55) * 0.025
    drawSunDiskAndAtmosphere(ctx, sunScr.x, sunScr.y, pulse, width, height)
  }

  // ── 轻微 vignette：压边，让中心深空更「空」──
  {
    const v = ctx.createRadialGradient(
      width * 0.5,
      height * 0.5,
      Math.min(width, height) * 0.35,
      width * 0.5,
      height * 0.5,
      Math.max(width, height) * 0.72,
    )
    v.addColorStop(0, 'rgba(0,0,0,0)')
    v.addColorStop(1, 'rgba(0,0,0,0.38)')
    ctx.fillStyle = v
    ctx.fillRect(0, 0, width, height)
  }
}

/** 便捷：创建并绘制 canvas（测试 / 静态导出） */
export function renderSolarSystemCanvas(options: SolarSystemRenderOptions): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.floor(options.width))
  canvas.height = Math.max(1, Math.floor(options.height))
  const ctx = canvas.getContext('2d')
  if (ctx) paintSolarSystemBackdrop(ctx, { ...options, width: canvas.width, height: canvas.height })
  return canvas
}
