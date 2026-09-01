/**
 * Node progress row display helpers (dedupe message vs structured detail).
 */
import {
  formatDownloadProgressDetail,
  hasDownloadProgressDetail,
  type DownloadProgressDetailLike,
} from './workflow-download-display'

export type NodeProgressMessageInput = {
  message?: string
  detail?: DownloadProgressDetailLike & {
    chunksDone?: number
    chunksTotal?: number
    pixelsDone?: number
    pixelsTotal?: number
    phase?: string
  }
}

/** Hide message line when detail row already conveys the same facts. */
export function nodeMessageRedundantWithDetail(np: NodeProgressMessageInput): boolean {
  const message = np.message?.trim()
  if (!message || !np.detail) return false

  if (hasDownloadProgressDetail(np.detail)) {
    const line = formatDownloadProgressDetail(np.detail)?.trim()
    if (!line) return false
    if (message === line || message.includes(line) || line.includes(message)) return true
    if (np.detail.phase === 'skipping' && /skip|跳过/i.test(message)) return true
    if (np.detail.phase === 'complete' && /complete|完成|downloaded/i.test(message)) return true
  }

  const d = np.detail
  if (
    typeof d.chunksTotal === 'number' &&
    d.chunksTotal > 0 &&
    message.includes(`${d.chunksDone ?? 0}/${d.chunksTotal}`)
  ) {
    return true
  }
  if (
    typeof d.pixelsTotal === 'number' &&
    d.pixelsTotal > 0 &&
    message.includes(`${d.pixelsDone ?? 0}/${d.pixelsTotal}`)
  ) {
    return true
  }
  if (d.phase && message.toLowerCase().includes(String(d.phase).toLowerCase())) {
    return true
  }
  return false
}
