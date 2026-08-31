/**
 * SHP/ZIP 解析 Worker（P3，2026-08-23）。
 *
 * 大文件（可达 80MB）的 shpjs 解析是重 CPU+解压任务，主线程执行会
 * 冻结 UI（地图交互/动画全部卡死）。此 Worker 在后台线程完成
 * 解析+规范化，仅传回轻量 GeoJSON 结构。
 *
 * arrayBuffer 经 postMessage transferable 零拷贝传入。
 * Worker 不可用的环境（node 测试环境）由调用方回退主线程动态 import。
 */
import { normalizeShpResult } from '../services/shp-normalize'

self.onmessage = async (event: MessageEvent<ArrayBuffer>) => {
  try {
    const shpjs = (await import('shpjs')).default
    const result = await shpjs(event.data)
    const normalized = normalizeShpResult(result)
    self.postMessage({ ok: true, ...normalized })
  } catch (error) {
    self.postMessage({
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    })
  }
}
