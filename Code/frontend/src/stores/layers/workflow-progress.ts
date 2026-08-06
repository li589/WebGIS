/**
 * Normalize workflow/node progress to 0–100, preferring chunk ratios when available.
 */

export type WorkflowProgressDetail = {
  chunksDone?: number
  chunksTotal?: number
  pixelsDone?: number
  pixelsTotal?: number
}

export function normalizeWorkflowProgress(
  raw: number | null | undefined,
  detail?: WorkflowProgressDetail | null,
): number {
  let pct = 0
  if (typeof raw === 'number' && Number.isFinite(raw)) {
    pct = raw >= 0 && raw <= 1 ? raw * 100 : raw
  }
  if (
    detail &&
    typeof detail.chunksTotal === 'number' &&
    detail.chunksTotal > 0 &&
    typeof detail.chunksDone === 'number' &&
    Number.isFinite(detail.chunksDone)
  ) {
    pct = Math.max(pct, (detail.chunksDone / detail.chunksTotal) * 100)
  } else if (
    detail &&
    typeof detail.pixelsTotal === 'number' &&
    detail.pixelsTotal > 0 &&
    typeof detail.pixelsDone === 'number' &&
    Number.isFinite(detail.pixelsDone)
  ) {
    pct = Math.max(pct, (detail.pixelsDone / detail.pixelsTotal) * 100)
  }
  return Math.max(0, Math.min(100, Math.round(pct)))
}
