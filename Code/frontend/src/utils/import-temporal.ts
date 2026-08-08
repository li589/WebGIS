import {
  formatTimeStep,
  parseInstant,
  parseTimeStep,
  type TemporalFollowPolicy,
  type TimeStep,
} from './temporal-interval'

export type ImportTemporalMode = 'auto' | 'static' | 'point' | 'range'

export interface GuessedTemporal {
  kind: 'point' | 'range'
  timeList: string[]
  defaultTime: string
  nativeStep: string
  label: string
}

function pad2(n: number) {
  return String(n).padStart(2, '0')
}

function fmtYmd(y: number, m: number, d: number): string | null {
  const dt = new Date(y, m - 1, d)
  if (dt.getFullYear() !== y || dt.getMonth() !== m - 1 || dt.getDate() !== d) return null
  return `${y}${pad2(m)}${pad2(d)}`
}

function nativeStepForRange(start: string, end: string): string {
  const a = parseInstant(start)
  const b = parseInstant(end)
  if (!a || !b) return '8d'
  const days = Math.round((b.getTime() - a.getTime()) / 86400000) + 1
  if (days <= 1) return '1d'
  if (days >= 6 && days <= 10) return '8d'
  if (days >= 28 && days <= 31) return '1m'
  return `${days}d`
}

/** 从文件名猜时间点（YYYYMMDD）或时间段（YYYYMMDD_YYYYMMDD） */
export function guessTimeLabelFromFilename(name: string): GuessedTemporal | null {
  const stem = String(name || '').replace(/\.[^.]+$/, '')

  const range =
    stem.match(/(?<!\d)(\d{4})(\d{2})(\d{2})[_-](\d{4})(\d{2})(\d{2})(?!\d)/) ||
    stem.match(/(?<!\d)(\d{4})-(\d{2})-(\d{2})[_~-](\d{4})-(\d{2})-(\d{2})(?!\d)/)
  if (range) {
    const a = fmtYmd(Number(range[1]), Number(range[2]), Number(range[3]))
    const b = fmtYmd(Number(range[4]), Number(range[5]), Number(range[6]))
    if (a && b) {
      const [start, end] = a <= b ? [a, b] : [b, a]
      const label = `${start}_${end}`
      return {
        kind: 'range',
        timeList: [label],
        defaultTime: label,
        nativeStep: nativeStepForRange(start, end),
        label,
      }
    }
  }

  const point = stem.match(/(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)/)
  if (point) {
    const label = fmtYmd(Number(point[1]), Number(point[2]), Number(point[3]))
    if (label) {
      return {
        kind: 'point',
        timeList: [label],
        defaultTime: label,
        nativeStep: '1d',
        label,
      }
    }
  }

  const dotted = stem.match(/(?<!\d)(\d{4})[.-](\d{1,2})[.-](\d{1,2})(?!\d)/)
  if (dotted) {
    const label = fmtYmd(Number(dotted[1]), Number(dotted[2]), Number(dotted[3]))
    if (label) {
      return {
        kind: 'point',
        timeList: [label],
        defaultTime: label,
        nativeStep: '1d',
        label,
      }
    }
  }

  return null
}

export function normalizeYmdInput(raw: string): string | null {
  const s = String(raw || '').trim()
  if (!s) return null
  const compact = s.replace(/[-./]/g, '')
  if (!/^\d{8}$/.test(compact)) return null
  return fmtYmd(
    Number(compact.slice(0, 4)),
    Number(compact.slice(4, 6)),
    Number(compact.slice(6, 8)),
  )
}

export function buildImportTemporalPayload(opts: {
  mode: ImportTemporalMode
  fileName?: string | null
  timePoint?: string
  timeStart?: string
  timeEnd?: string
  nativeStep?: string
}): {
  temporalMode: ImportTemporalMode
  timeLabel?: string | null
  timeStart?: string | null
  timeEnd?: string | null
  nativeStep?: string | null
  preview: { kind: string; label: string; nativeStep: string | null } | null
} {
  const mode = opts.mode
  if (mode === 'static') {
    return {
      temporalMode: 'static',
      preview: { kind: 'static', label: '静态（无时间）', nativeStep: null },
    }
  }
  if (mode === 'point') {
    const label = normalizeYmdInput(opts.timePoint || '')
    const step = opts.nativeStep?.trim() || '1d'
    return {
      temporalMode: 'point',
      timeLabel: label,
      timeStart: label,
      nativeStep: step,
      preview: label ? { kind: 'point', label, nativeStep: step } : null,
    }
  }
  if (mode === 'range') {
    const a = normalizeYmdInput(opts.timeStart || '')
    const b = normalizeYmdInput(opts.timeEnd || '')
    if (!a || !b) {
      return { temporalMode: 'range', preview: null }
    }
    const [start, end] = a <= b ? [a, b] : [b, a]
    const label = `${start}_${end}`
    const step = opts.nativeStep?.trim() || nativeStepForRange(start, end)
    return {
      temporalMode: 'range',
      timeLabel: label,
      timeStart: start,
      timeEnd: end,
      nativeStep: step,
      preview: { kind: 'range', label, nativeStep: step },
    }
  }
  const guessed = guessTimeLabelFromFilename(opts.fileName || '')
  if (!guessed) {
    return {
      temporalMode: 'auto',
      preview: { kind: 'static', label: '未识别到日期 → 静态', nativeStep: null },
    }
  }
  const step = opts.nativeStep?.trim() || guessed.nativeStep
  return {
    temporalMode: 'auto',
    timeLabel: guessed.label,
    nativeStep: step,
    preview: { kind: guessed.kind, label: guessed.label, nativeStep: step },
  }
}

export function describeNativeStep(raw: string | null | undefined): string {
  const step = parseTimeStep(raw)
  if (!step) return raw || '—'
  return formatTimeStep(step as TimeStep)
}

export type { TemporalFollowPolicy }
