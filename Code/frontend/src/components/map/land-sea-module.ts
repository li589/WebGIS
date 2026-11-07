/**
 * 海陆底图叠加（land-sea）—— 栅格贴图版
 *
 * 用途：用户明确要一张「只有海陆分界、没有国界线」的底图（原先只画了国界/地名
 * 的底图挡不住这些要素）。它是**叠加**在现有底图之上的一层，不改变「底图选哪家」：
 * 高德仍是默认底图，勾上这一项就把底下的地名和国界整片盖掉。
 *
 * 为什么不做成新的 TileSource：
 *   做成底图源要动 TILE_SOURCES、故障转移、熔断、风格分组一整套，牵一发动全身；
 *   而这一项本质就是「一张全球图」，用 image source 一行就够。
 *
 * ⚠ 与 land-base-module 相同的三条约束（踩过的坑，别改）：
 *   1) maplibre 的 worker 文件在本部署里 404 ⇒ **GeoJSON 源一律加载不了**，
 *      只能用 image source（纯像素采样，不走 worker）。
 *   2) 掩膜必须是 EPSG:3857（Web Mercator）烤制，image source 四角映射到地图
 *      平面中间做仿射插值，按纬度线性烤会让中纬度整块错位约 20°。
 *   3) 文件名必须带版本/尺寸：图片按 URL 缓存，改内容不改名浏览器会一直用旧图。
 *
 * 数据：/data/boundaries/world-landsea-merc-4096.png（4096², 0.20 MB, 全不透明）
 *   由 Tools/build_land_sea_basemap.py 生成（陆地=掩膜 alpha，海洋=其余）。
 */

const SOURCE_ID = 'land-sea-base'
const LAYER_ID = 'land-sea-base-raster'
/** 名字带 merc + 尺寸：换配色后必须换名，否则浏览器吃旧缓存 */
const DATA_URL = '/data/boundaries/world-landsea-merc-4096.png'

/** Web Mercator 世界正方形的纬度边界，与掩膜图范围严格对应 */
const MERCATOR_LAT = 85.05112877980659

type MapInstance = import('maplibre-gl').Map

/**
 * 不作为「插入锚点」的图层：
 *   - 本层自己
 *   - 陆地灰底衬（world-land-fill，0.1 半透明）：本层要盖在它上面
 *   - 底图主栅格与注记栅格：凡是从底图开始的都不算数据层
 * 其余第一个图层即数据层 ⇒ 本层插在它之前，就正好在底图之上、数据之下。
 */
const NON_ANCHOR_LAYER_IDS = new Set([
  LAYER_ID,
  'world-land-fill',
  'tile-base-raster',
  'tile-base-overlay-raster',
])

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

/** 数据层可能在本层之后才加进来 ⇒ 每次都自愈一次栈位，别停在栈顶盖住数据 */
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
    console.warn('[land-sea] 移动到数据层之下失败:', err)
  }
}

/** 幂等：加/切显隐。失败只 warn，不阻断地图初始化。 */
export async function ensureLandSeaBase(map: MapInstance, visible: boolean): Promise<void> {
  if (loadedMaps.has(map)) {
    applyVisible(map, visible)
    repositionUnderData(map)
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
          // 角点顺序固定为 左上 → 右上 → 右下 → 左下
          coordinates: [
            [-180, MERCATOR_LAT],
            [180, MERCATOR_LAT],
            [180, -MERCATOR_LAT],
            [-180, -MERCATOR_LAT],
          ],
        })
      }
      if (!map.getLayer(LAYER_ID)) {
        // 插在底图之上、数据层之下：找不到数据层就追加到栈顶（后续 reposition 会纠正）
        const beforeLayerId = findInsertAnchor(map)
        map.addLayer(
          {
            id: LAYER_ID,
            type: 'raster',
            source: SOURCE_ID,
            layout: { visibility: visible ? 'visible' : 'none' },
            paint: {
              'raster-opacity': 1,
              'raster-fade-duration': 0,
              'raster-resampling': 'linear',
            },
          },
          beforeLayerId,
        )
      }
      applyVisible(map, visible)
      repositionUnderData(map)
      loadedMaps.add(map)
    } catch (err) {
      console.warn('[land-sea] 海陆底图加载失败（不影响地图使用）:', err)
    } finally {
      loadingPromises.delete(map)
    }
  })()

  loadingPromises.set(map, task)
  await task
}

export function setLandSeaBaseVisible(map: MapInstance | null, visible: boolean): void {
  if (!map || !map.getLayer(LAYER_ID)) return
  applyVisible(map, visible)
}

export const LAND_SEA_LAYER_ID = LAYER_ID
