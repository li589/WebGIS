/**
 * Format workflow progress for status chips / computing groups.
 * Gracefully omits missing tile/time dimensions.
 */

export type ProgressShellDetail = {
  chunksDone?: number
  chunksTotal?: number
  pixelsDone?: number
  pixelsTotal?: number
  phase?: string
  blocksDone?: number
  blocksTotal?: number
  dateStart?: string
  dateEnd?: string
  blockIdx?: number
  blockDir?: string
  timeKey?: string
  tileId?: string
  chunkId?: string
  blockId?: string
  productTag?: string
  moduleName?: string
}

export type ProgressShellInput = {
  progress?: number | null
  message?: string | null
  stage?: string | null
  nodeLabel?: string | null
  detail?: ProgressShellDetail | null
}

function pickStr(...values: Array<string | null | undefined>): string | null {
  for (const v of values) {
    if (typeof v === 'string' && v.trim()) return v.trim()
  }
  return null
}

/** Build a short human label: "节点 · 时间 · 块 · 42%" */
export function formatProgressShell(input: ProgressShellInput): string {
  const parts: string[] = []
  const detail = input.detail

  const node = pickStr(input.nodeLabel, detail?.moduleName, input.stage)
  if (node) parts.push(node)

  const timeKey = pickStr(detail?.timeKey, detail?.dateStart)
  if (timeKey) {
    if (detail?.dateEnd && detail.dateEnd !== timeKey) {
      parts.push(`${timeKey}–${detail.dateEnd}`)
    } else {
      parts.push(timeKey)
    }
  }

  const chunkId = pickStr(detail?.chunkId, detail?.tileId, detail?.blockId)
  if (chunkId) {
    parts.push(chunkId)
  } else if (
    typeof detail?.chunksDone === 'number' &&
    typeof detail?.chunksTotal === 'number' &&
    detail.chunksTotal > 0
  ) {
    parts.push(`块 ${detail.chunksDone}/${detail.chunksTotal}`)
  } else if (
    typeof detail?.blocksDone === 'number' &&
    typeof detail?.blocksTotal === 'number' &&
    detail.blocksTotal > 0
  ) {
    parts.push(`块 ${detail.blocksDone}/${detail.blocksTotal}`)
  }

  const product = pickStr(detail?.productTag)
  if (product) parts.push(product)

  if (typeof input.progress === 'number' && Number.isFinite(input.progress)) {
    const pct = Math.max(0, Math.min(100, Math.round(input.progress)))
    parts.push(`${pct}%`)
  }

  if (parts.length > 0) return parts.join(' · ')

  const msg = pickStr(input.message)
  return msg ?? ''
}

/** Prefer the newest node progress entry for shell display (by updatedAt, then progress). */
export function pickLatestNodeProgress<
  T extends { progress: number; message?: string; updatedAt?: string },
>(nodes: T[] | undefined | null): T | null {
  if (!nodes?.length) return null
  return nodes.reduce((best, cur) => {
    const bestAt = best.updatedAt ? Date.parse(best.updatedAt) : NaN
    const curAt = cur.updatedAt ? Date.parse(cur.updatedAt) : NaN
    if (Number.isFinite(curAt) && Number.isFinite(bestAt)) {
      return curAt >= bestAt ? cur : best
    }
    if (Number.isFinite(curAt) && !Number.isFinite(bestAt)) return cur
    if (!Number.isFinite(curAt) && Number.isFinite(bestAt)) return best
    return cur.progress >= best.progress ? cur : best
  }, nodes[0]!)
}
