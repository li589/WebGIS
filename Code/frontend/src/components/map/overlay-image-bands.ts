/**
 * Overlay PNG 的 Mercator 条带化渲染（P3，2026-08-23）。
 *
 * MapLibre image source 在四角经纬度间**线性插值**；Web Mercator 的
 * 纬度→屏幕间距是非线性的（高纬拉伸）。小纬度跨度近似成立，大跨度
 * （如中国区 15–59°N）时中间纬度明显错位——高纬（日本/朝鲜）偏移且
 * 纵向拉伸、低纬（东南亚）近似对齐。
 *
 * 解法：把单张等经纬度网格 PNG 按纬度切成 N 条带（BAND_DEG 上限），
 * 每带独立 image source——带内线性近似误差 < 像素级可见阈值。
 * 主 layer 保留占位契约（存在性检查/清理路径不变），渲染由条带 layer
 * 承担（主 layer 隐藏）。
 */

/** 单带最大纬度跨度（度）——4° 带内 Mercator 线性误差 <0.2%。 */
const BAND_DEG = 4

/** 触发条带化的最小总纬度跨度（度）——小于此跨度线性近似已足够。 */
const MIN_SPAN_FOR_BANDING = 8

/** 条带 layer/source 的 id 后缀模式（清理时识别）。 */
export const BAND_ID_INFIX = '__b'

/** 判断 bounds 是否需要条带化（大纬度跨度才需要）。 */
export function needsBanding(bounds: [number, number, number, number]): boolean {
  return bounds[3] - bounds[1] >= MIN_SPAN_FOR_BANDING
}

/**
 * 判断 PNG 是否已是 Mercator 线性网格（行按 Mercator y 均匀，如
 * export_overlay_assets._reproject_to_mercator_linear 的产物——全球层
 * 1440x1440，行距为 Mercator y 均匀）。这类 PNG 直接按 bounds 贴四角
 * 即地理精确，**不得条带化**（条带化会把 Mercator 线性行误当等纬度行
 * 切带 → 南北大范围拉伸错位，2026-08-23 smap-aux-* 回归教训）。
 *
 * 判据：等经纬网格期望高 = 宽 × lat_span / lon_span；实际高明显偏离
 *（全球层实际 1440 vs 等经纬期望 ~680）即 Mercator 线性。
 */
export function isMercatorLinearPng(
  bounds: [number, number, number, number],
  imgW: number,
  imgH: number,
): boolean {
  const lonSpan = bounds[2] - bounds[0]
  const latSpan = bounds[3] - bounds[1]
  if (lonSpan <= 0 || latSpan <= 0 || !imgW || !imgH) return false
  const eqLatHeight = (imgW * latSpan) / lonSpan
  if (eqLatHeight <= 0) return false
  return Math.abs(imgH - eqLatHeight) / imgH > 0.12
}

function _loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error(`overlay image load failed: ${url}`))
    img.src = url
  })
}

export interface BandPaintSpec {
  opacity: number
  /** MapLibre 附加 paint（与主 raster layer 保持一致，如 raster-resampling）。 */
  extraPaint?: Record<string, unknown>
}

/**
 * 为大跨度 overlay PNG 建立条带 source+layer。
 *
 * 条带 layer 插到主 rasterLayerId **之前**（渲染顺序紧邻主 layer 原位置），
 * 随后隐藏主 layer——所有对主 layer 的存在性/契约检查保持有效。
 * 返回建立的条带数（0 = 无需/失败，调用方维持单图渲染）。
 */
export async function addBandedImageSources(
  map: maplibregl.Map,
  sourceId: string,
  rasterLayerId: string,
  url: string,
  bounds: [number, number, number, number],
  spec: BandPaintSpec,
): Promise<number> {
  if (!needsBanding(bounds)) return 0
  const [w, s, e, n] = bounds
  const span = n - s
  const bandCount = Math.ceil(span / BAND_DEG)
  if (bandCount < 2) return 0

  let img: HTMLImageElement
  try {
    img = await _loadImage(url)
  } catch {
    return 0 // 图加载失败：保持主 layer 单图渲染（现状降级）
  }

  const imgW = img.naturalWidth
  const imgH = img.naturalHeight
  if (!imgW || !imgH) return 0

  // Mercator 线性 PNG（后端已重投影）：直接贴 bounds 即精确，跳过条带化
  if (isMercatorLinearPng(bounds, imgW, imgH)) return 0

  const masterLayer = map.getLayer(rasterLayerId)
  if (!masterLayer) return 0

  let created = 0
  for (let i = 0; i < bandCount; i++) {
    const lat0 = s + (span * i) / bandCount
    const lat1 = s + (span * (i + 1)) / bandCount
    const y0 = Math.floor((imgH * i) / bandCount)
    const y1 = i === bandCount - 1 ? imgH : Math.ceil((imgH * (i + 1)) / bandCount)
    const bandH = y1 - y0
    if (bandH <= 0) continue

    const canvas = document.createElement('canvas')
    canvas.width = imgW
    canvas.height = bandH
    const ctx = canvas.getContext('2d')
    if (!ctx) continue
    ctx.drawImage(img, 0, y0, imgW, bandH, 0, 0, imgW, bandH)
    const dataUrl = canvas.toDataURL('image/png')

    const bid = `${sourceId}${BAND_ID_INFIX}${i}`
    const blid = `${rasterLayerId}${BAND_ID_INFIX}${i}`
    if (!map.getSource(bid)) {
      map.addSource(bid, {
        type: 'image',
        url: dataUrl,
        coordinates: [
          [w, lat1],
          [e, lat1],
          [e, lat0],
          [w, lat0],
        ],
      } as maplibregl.ImageSourceSpecification)
    }
    if (!map.getLayer(blid)) {
      map.addLayer(
        {
          id: blid,
          type: 'raster',
          source: bid,
          paint: {
            'raster-opacity': Math.max(0, Math.min(1, spec.opacity)),
            ...(spec.extraPaint ?? {}),
          },
        },
        // 插在主 layer 之前：渲染顺序紧贴主 layer 原位置（主 layer 隐藏）
        rasterLayerId,
      )
    }
    created++
  }

  if (created > 0) {
    // 主 layer 隐藏（占位契约保留，渲染由条带承担）
    map.setLayoutProperty(rasterLayerId, 'visibility', 'none')
  }
  return created
}

/** 同步 opacity / visibility 到全部条带 layer（setOverlayOpacity/Visibility 后调用）。 */
export function syncBandedLayerPaint(
  map: maplibregl.Map,
  rasterLayerId: string,
  update: { opacity?: number; visible?: boolean },
): void {
  const style = map.getStyle()
  if (!style?.layers) return
  for (const layer of style.layers) {
    if (layer.id.startsWith(`${rasterLayerId}${BAND_ID_INFIX}`) && map.getLayer(layer.id)) {
      if (typeof update.opacity === 'number') {
        map.setPaintProperty(layer.id, 'raster-opacity', Math.max(0, Math.min(1, update.opacity)))
      }
      if (typeof update.visible === 'boolean') {
        map.setLayoutProperty(layer.id, 'visibility', update.visible ? 'visible' : 'none')
      }
    }
  }
}

/** 清除全部条带 source+layer（主 layer 清理路径顺带调用）。 */
export function removeBandedLayers(
  map: maplibregl.Map,
  sourceId: string,
  rasterLayerId: string,
): void {
  const style = map.getStyle()
  if (!style?.layers) return
  const bandLayerIds = style.layers
    .map((l) => l.id)
    .filter((id) => id.startsWith(`${rasterLayerId}${BAND_ID_INFIX}`))
  for (const id of bandLayerIds) {
    if (map.getLayer(id)) map.removeLayer(id)
  }
  const bandSourceIds = Object.keys(style.sources ?? {}).filter((id) =>
    id.startsWith(`${sourceId}${BAND_ID_INFIX}`),
  )
  for (const id of bandSourceIds) {
    if (map.getSource(id)) map.removeSource(id)
  }
}
