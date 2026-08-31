/**
 * Format unified download progress detail for WorkflowStatusPanel.
 */

export type DownloadProgressDetailLike = {
  download_mode?: 'single_file' | 'multi_file' | 'byte_stream' | string
  downloaded_items?: number | null
  total_items?: number | null
  downloaded_bytes?: number | null
  total_bytes?: number | null
  speed_bps?: number | null
  current_item_name?: string | null
  active_workers?: number | null
  phase?: string | null
  items_display?: 'index' | 'filename' | string
}

const MANY_FILES_THRESHOLD = 20
const SMALL_FILE_AVG_BYTES = 64 * 1024

export function formatSpeed(bps: number | null | undefined): string {
  if (!bps || bps <= 0) return ''
  if (bps >= 1024 * 1024) return `${(bps / 1024 / 1024).toFixed(1)} MB/s`
  if (bps >= 1024) return `${(bps / 1024).toFixed(0)} KB/s`
  return `${bps.toFixed(0)} B/s`
}

export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = bytes
  let idx = 0
  while (size >= 1024 && idx < units.length - 1) {
    size /= 1024
    idx++
  }
  return `${idx === 0 ? size : size.toFixed(1)} ${units[idx]}`
}

function truncateName(name: string, max = 40): string {
  const trimmed = name.trim()
  if (trimmed.length <= max) return trimmed
  return `${trimmed.slice(0, max - 1)}…`
}

/** Human-readable download line; empty string if not download detail. */
export function formatDownloadProgressDetail(
  detail: DownloadProgressDetailLike | null | undefined,
): string {
  if (!detail) return ''
  const phase = String(detail.phase || '').trim()
  if (phase === 'scanning') {
    const found = detail.total_items
    return found != null && found > 0 ? `正在扫描… 已发现 ${found} 个文件` : '正在扫描远程目录…'
  }
  if (phase === 'skipping' || phase === 'complete') {
    const total = detail.total_items
    const done = detail.downloaded_items ?? total
    if (total != null && done != null) {
      return phase === 'skipping' ? `全部跳过 (${done}/${total})` : `下载完成 (${done}/${total})`
    }
  }

  const mode = detail.download_mode || (detail.total_items != null ? 'multi_file' : 'byte_stream')
  const speed = formatSpeed(detail.speed_bps ?? undefined)
  const speedPart = speed ? ` · ${speed}` : ''
  const workers =
    typeof detail.active_workers === 'number' && detail.active_workers > 1
      ? `并发 ${detail.active_workers} · `
      : ''

  if (mode === 'byte_stream' || mode === 'single_file') {
    const name = detail.current_item_name ? truncateName(detail.current_item_name) : '文件'
    const got = formatBytes(detail.downloaded_bytes ?? 0)
    const total =
      detail.total_bytes != null && detail.total_bytes > 0 ? formatBytes(detail.total_bytes) : '?'
    return `${name} · ${got} / ${total}${speedPart}`
  }

  const current = detail.downloaded_items ?? 0
  const total = detail.total_items
  const bytes = detail.downloaded_bytes != null ? formatBytes(detail.downloaded_bytes) : ''

  const useIndexOnly =
    detail.items_display === 'index' ||
    (total != null && total > MANY_FILES_THRESHOLD) ||
    (total != null &&
      total > 0 &&
      detail.downloaded_bytes != null &&
      detail.downloaded_bytes / Math.max(current, 1) < SMALL_FILE_AVG_BYTES)

  if (useIndexOnly) {
    const countPart = total != null ? `文件 ${current}/${total}` : `文件 ${current}/?`
    if (total != null && total > MANY_FILES_THRESHOLD && current > 0 && !bytes) {
      return `${workers}批量下载 · ${countPart}${speedPart}`
    }
    return `${workers}${countPart}${bytes ? ` · 累计 ${bytes}` : ''}${speedPart}`
  }

  const fileName = detail.current_item_name ? truncateName(detail.current_item_name) : ''
  const countPart = total != null ? `文件 ${current}/${total}` : `文件 ${current}`
  if (fileName) {
    return `${workers}${countPart} · ${fileName}${bytes ? ` · ${bytes}` : ''}${speedPart}`
  }
  return `${workers}${countPart}${bytes ? ` · ${bytes}` : ''}${speedPart}`
}

export function hasDownloadProgressDetail(
  detail: DownloadProgressDetailLike | null | undefined,
): boolean {
  if (!detail) return false
  return Boolean(
    detail.download_mode ||
    detail.downloaded_items != null ||
    detail.downloaded_bytes != null ||
    detail.phase === 'scanning' ||
    detail.phase === 'skipping' ||
    detail.phase === 'complete' ||
    detail.speed_bps,
  )
}
