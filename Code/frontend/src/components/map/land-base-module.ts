/**
 * 全球陆地底衬（world-land-fill）—— 栅格贴图版
 *
 * 为什么需要：
 *   数据是**全球**栅格，高德底图的陆地是米白 #fcf9f2，而 ylgnbu 色带最浅一档
 *   #ffffd9 亮度与之几乎相同 ⇒ 低值区和陆地融成一片。
 *   做法：底图之上、数据层之下铺一层半透明灰，陆地变灰、海洋保持底图原本的蓝。
 *
 * ── 为什么最终用"图片"而不是 GeoJSON 矢量面 ────────────────────────────────
 *   ⚠ 本部署里 **maplibre 的 worker 文件 404**（`GET /assets/maplibre-gl-worker.mjs`），
 *     导致 maplibre **所有 GeoJSON 数据源都加载不了**（系统自带的省界、足迹框一样中招），
 *     栅格源不受影响。所以任何 fill/line 矢量方案在这个构建里都画不出来。
 *     实测：`isSourceLoaded('admin-boundaries') === false`、渲染要素数恒为 0。
 *   ⇒ 只能走 image source（纯像素采样，不走 worker）。
 *
 * ⚠ 掩膜图必须是 **EPSG:3857（Web Mercator）**：
 *   image source 把图片四角映射到地图平面、中间做仿射插值，而地图是墨卡托
 *   （y ∝ ln(tan(45°+φ/2))）。若按纬度线性烤，只有四角对得上、中间纬度全错位
 *   （45°N 会显示在 68.5°N，整块陆地向北偏约 20°）。
 *
 * ⚠ 文件名必须带版本/尺寸：图片按 URL 缓存，改内容不改名的话浏览器会一直用旧图
 *   （踩过：换了投影但沿用旧文件名，页面上一直是错位的那张）。
 *
 * ⚠ 只用 4096：8192² 超过这台机器显卡的 MAX_TEXTURE_SIZE，会贴图失败再降级。
 *
 * 数据：
 *   /data/boundaries/world-land-merc-4096.png（4096²，0.19 MB，墨卡托）
 *   由 Tools/build_world_land_mask.py 生成：
 *     陆地 = (Natural Earth 10m 全球国家面 − 中国标准省界) ∪ 中国标准省界
 */

const SOURCE_ID = 'world-land'
const LAYER_ID = 'world-land-fill'
/** 名字带 merc + 尺寸：换实现后必须换名，否则浏览器吃旧缓存 */
const DATA_URL = '/data/boundaries/world-land-merc-4096.png'

/** 陆地灰（与省界 admin-fill 同色，保证两套灰一致） */
export const WORLD_LAND_FILL_COLOR = '#0c2238'
/**
 * 浓度：0.10 叠在高德陆地 #fcf9f2 上 ⇒ #E5E5E1（极淡，仅剩一点"脏白"的层次感），
 * 与底图几乎融在一起，只有大片陆地轮廓还能看出一点点边界。
 * 这基本是"能看见的最淡一档"，再往下就与底图完全不可区分了。
 * 要更深/更浅只改这一个数（0.42 深，0.36 中，0.32 浅，0.25 中浅，
 * 0.20 很浅，0.15 极浅，0.10 当前）。
 */
export const WORLD_LAND_FILL_OPACITY = 0.1

/** Web Mercator 世界正方形的纬度边界，与掩膜图范围严格对应 */
const MERCATOR_LAT = 85.05112877980659

type MapInstance = import('maplibre-gl').Map

/** 底图自身和本图层不算"数据层"，其余第一个即插入锚点 */
const NON_ANCHOR_LAYER_IDS = new Set([LAYER_ID, 'tile-base-raster', 'tile-base-overlay-raster'])

const loadedMaps = new WeakSet<MapInstance>()
const loadingPromises = new WeakMap<MapInstance, Promise<void>>()

function findInsertAnchor(map: MapInstance): string | undefined {
  for (const layer of map.getStyle()?.layers ?? []) {
    if (layer.type === 'background') continue
    if (NON_ANCHOR_LAYER_IDS.has(layer.id)) continue
    return layer.id
  }
  return undefined
}

function applyVisible(map: MapInstance, visible: boolean) {
  if (!map.getLayer(LAYER_ID)) return
  map.setLayoutProperty(LAYER_ID, 'visibility', visible ? 'visible' : 'none')
}

/** 把灰层挪到第一个数据图层之下；锚点若在底图之下则拒绝（否则会沉到看不见） */
function repositionUnderData(map: MapInstance) {
  if (!map.getLayer(LAYER_ID)) return
  const anchor = findInsertAnchor(map)
  if (!anchor || anchor === LAYER_ID) return
  const stack = (map.getStyle()?.layers ?? []).map((l) => l.id)
  const self = stack.indexOf(LAYER_ID)
  const target = stack.indexOf(anchor)
  if (self === -1 || target === -1 || self === target - 1) return
  const baseIdx = stack.reduce((acc, id, i) => (NON_ANCHOR_LAYER_IDS.has(id) ? i : acc), -1)
  if (target <= baseIdx) return
  try {
    map.moveLayer(LAYER_ID, anchor)
  } catch (err) {
    console.warn('[land-base] 移动到数据层之下失败:', err)
  }
}

/**
 * 把运行时状态打到网关访问日志里（该路径不存在，返回 404 无妨）。
 * 目的：页面出问题时不必依赖用户开控制台，直接 `docker logs cgda-gateway-nginx`
 * 就能读到图层栈、显隐、透明度，定位"加了但看不见"卡在哪。
 */
function diag(map: MapInstance, payload: Record<string, unknown>) {
  try {
    const stack = (map.getStyle()?.layers ?? []).map((l) => l.id)
    const body = {
      ...payload,
      at: stack.indexOf(LAYER_ID),
      total: stack.length,
      vis: map.getLayer(LAYER_ID) ? map.getLayoutProperty(LAYER_ID, 'visibility') : 'no-layer',
    }
    void fetch(
      `/data/boundaries/__landdiag?d=${encodeURIComponent(JSON.stringify(body)).slice(0, 900)}`,
      {
        cache: 'no-store',
      },
    ).catch(() => {})
  } catch {
    /* 诊断失败不影响功能 */
  }
}

/**
 * 幂等：加陆地底衬图层。失败只 warn，不阻断地图初始化。
 * @param visible 初始是否可见（卫星/影像底图应传 false）
 */
export async function ensureWorldLandBase(map: MapInstance, visible = true): Promise<void> {
  if (loadedMaps.has(map)) {
    applyVisible(map, visible)
    // 数据图层可能在建层之后才加进来，那时灰层会停在栈顶把数据盖住 ⇒ 每次调用都自愈一次
    repositionUnderData(map)
    diag(map, { stage: 'again', want: visible, op: WORLD_LAND_FILL_OPACITY })
    return
  }
  const inflight = loadingPromises.get(map)
  if (inflight) {
    await inflight
    applyVisible(map, visible)
    repositionUnderData(map)
    return
  }

  const task = (async () => {
    try {
      if (!map.getSource(SOURCE_ID)) {
        map.addSource(SOURCE_ID, {
          type: 'image',
          url: DATA_URL,
          // 角点顺序固定为 左上 → 右上 → 右下 → 左下；
          // 纬度用墨卡托边界 ±85.05112877980659，才与墨卡托光栅化的掩膜对齐
          coordinates: [
            [-180, MERCATOR_LAT],
            [180, MERCATOR_LAT],
            [180, -MERCATOR_LAT],
            [-180, -MERCATOR_LAT],
          ],
        })
      }
      if (!map.getLayer(LAYER_ID)) {
        map.addLayer({
          id: LAYER_ID,
          type: 'raster',
          source: SOURCE_ID,
          layout: { visibility: 'visible' },
          paint: {
            'raster-opacity': WORLD_LAND_FILL_OPACITY,
            'raster-fade-duration': 0,
            'raster-resampling': 'linear',
          },
        })
      }
      applyVisible(map, visible)
      repositionUnderData(map)
      loadedMaps.add(map)
      diag(map, {
        stage: 'ok',
        want: visible,
        op: WORLD_LAND_FILL_OPACITY,
        hasSrc: Boolean(map.getSource(SOURCE_ID)),
      })
      // 临时调试句柄：便于在页面里检查该图层的实际渲染情况
      ;(window as unknown as Record<string, unknown>).__land = {
        map,
        layer: LAYER_ID,
        source: SOURCE_ID,
      }
    } catch (err) {
      console.warn('[land-base] 全球陆地底衬加载失败（不影响地图使用）:', err)
      diag(map, { stage: 'err', msg: String(err).slice(0, 160) })
    } finally {
      loadingPromises.delete(map)
    }
  })()

  loadingPromises.set(map, task)
  await task
}

/** 底图切换时调用：卫星/影像/深色/空白底图上不该盖灰 */
export function setWorldLandBaseVisible(map: MapInstance | null, visible: boolean): void {
  if (!map || !map.getLayer(LAYER_ID)) return
  applyVisible(map, visible)
}

export function setWorldLandBaseOpacity(map: MapInstance | null, opacity: number): void {
  if (!map || !map.getLayer(LAYER_ID)) return
  map.setPaintProperty(LAYER_ID, 'raster-opacity', Math.max(0, Math.min(1, opacity)))
}

export const WORLD_LAND_LAYER_ID = LAYER_ID
